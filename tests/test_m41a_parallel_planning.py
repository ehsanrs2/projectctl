from __future__ import annotations

import subprocess
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from projectctl.cli.entry import app
from projectctl.core.digest import digest
from projectctl.core.enums import ResourceClass, TaskStatus
from projectctl.parallel.catalog import load_parallel_scope_catalog
from projectctl.parallel.service import assess_parallel_safety, build_parallel_plan
from projectctl.scheduler.digests import semantic_task_scope_digest
from projectctl.schemas.parallel import (
    ParallelInputEvidence,
    ParallelPathScope,
    ParallelPlan,
    ParallelTaskScope,
)
from projectctl.schemas.project_state import ProjectState
from projectctl.schemas.task import NormalizedTask, TaskSnapshot, TaskSource

NOW = datetime(2026, 10, 7, 9, 0, tzinfo=timezone.utc)
runner = CliRunner()


def task(
    task_id: str,
    *,
    title: str | None = None,
    dependencies: list[str] | None = None,
) -> NormalizedTask:
    return NormalizedTask(
        id=task_id,
        title=title or task_id,
        source=TaskSource(provider="test", external_id=task_id),
        status=TaskStatus.READY,
        resource_class=ResourceClass.SMALL,
        dependencies=dependencies or [],
    )


def snapshot(*tasks: NormalizedTask) -> TaskSnapshot:
    return TaskSnapshot(
        provider="test",
        captured_at=NOW,
        source_revision="rev",
        tasks=list(tasks),
    )


def plan(
    task_id: str,
    *,
    project_id: str = "repo",
    target: str = "main",
    base: str = "a" * 40,
    project_state_digest: str = "state",
    scoped_task_ids: list[str] | None = None,
    inputs: list[ParallelPathScope] | None = None,
    writes: list[ParallelPathScope] | None = None,
    resources: list[str] | None = None,
) -> ParallelPlan:
    input_scopes = inputs or [
        ParallelPathScope(path=f"src/{task_id}.py", kind="exact")
    ]
    return ParallelPlan(
        plan_id=f"plan-{task_id}-{base[:7]}",
        project_id=project_id,
        task_id=task_id,
        integration_target_ref=target,
        base_commit=base,
        project_state_digest=project_state_digest,
        scoped_task_digest=f"task-digest-{task_id}",
        scoped_task_ids=scoped_task_ids or [task_id],
        scope_digest=f"scope-digest-{task_id}",
        inputs=[
            ParallelInputEvidence(scope=item, digest=f"digest-{index}")
            for index, item in enumerate(input_scopes)
        ],
        writes=writes or [
            ParallelPathScope(path=f"src/{task_id}.py", kind="exact")
        ],
        resources=resources or [],
        created_at=NOW,
    )


def git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def test_scoped_task_digest_ignores_unrelated_task_lifecycle_change():
    first = snapshot(
        task("a", dependencies=["b"]),
        task("b", title="dependency"),
        task("c", title="unrelated-v1"),
    )
    second = snapshot(
        task("a", dependencies=["b"]),
        task("b", title="dependency"),
        task("c", title="unrelated-v2"),
    )

    left_digest, left_ids = semantic_task_scope_digest(first, "a")
    right_digest, right_ids = semantic_task_scope_digest(second, "a")

    assert left_ids == ["a", "b"]
    assert right_ids == ["a", "b"]
    assert left_digest == right_digest


def test_scoped_task_digest_changes_when_local_dependency_changes():
    first = snapshot(
        task("a", dependencies=["b"]),
        task("b", title="dependency-v1"),
    )
    second = snapshot(
        task("a", dependencies=["b"]),
        task("b", title="dependency-v2"),
    )

    assert semantic_task_scope_digest(first, "a")[0] != semantic_task_scope_digest(
        second, "a"
    )[0]


def test_disjoint_same_base_plans_are_execution_independent_but_need_reverification():
    left = plan(
        "a",
        inputs=[ParallelPathScope(path="src/a.py")],
        writes=[ParallelPathScope(path="src/a.py")],
    )
    right = plan(
        "b",
        inputs=[ParallelPathScope(path="src/b.py")],
        writes=[ParallelPathScope(path="src/b.py")],
    )

    decision = assess_parallel_safety(left, right, now=NOW)

    assert decision.independent is True
    assert decision.shared_target is True
    assert decision.shared_base is True
    assert decision.integration_requires_reverification is True
    assert decision.conflicts == []


def test_write_tree_overlap_fails_closed():
    left = plan(
        "a",
        writes=[ParallelPathScope(path="src/pkg", kind="tree")],
    )
    right = plan(
        "b",
        inputs=[ParallelPathScope(path="tests/b.py")],
        writes=[ParallelPathScope(path="src/pkg/module.py", kind="exact")],
    )

    decision = assess_parallel_safety(left, right, now=NOW)

    assert decision.independent is False
    assert "write_write_overlap" in {item.reason for item in decision.conflicts}


def test_write_input_overlap_fails_closed():
    left = plan(
        "a",
        writes=[ParallelPathScope(path="src/shared.py")],
    )
    right = plan(
        "b",
        inputs=[ParallelPathScope(path="src/shared.py")],
        writes=[ParallelPathScope(path="src/b.py")],
    )

    decision = assess_parallel_safety(left, right, now=NOW)

    assert decision.independent is False
    assert "write_input_overlap" in {item.reason for item in decision.conflicts}


def test_resource_overlap_fails_closed():
    left = plan("a", resources=["db:schema"])
    right = plan("b", resources=["db:schema"])

    decision = assess_parallel_safety(left, right, now=NOW)

    assert decision.independent is False
    assert "resource_overlap" in {item.reason for item in decision.conflicts}


def test_task_dependency_fails_closed():
    left = plan("a", scoped_task_ids=["a", "b"])
    right = plan("b")

    decision = assess_parallel_safety(left, right, now=NOW)

    assert decision.independent is False
    assert "task_dependency" in {item.reason for item in decision.conflicts}


def test_shared_target_with_different_base_fails_closed():
    left = plan("a", base="a" * 40)
    right = plan("b", base="b" * 40)

    decision = assess_parallel_safety(left, right, now=NOW)

    assert decision.independent is False
    assert "target_base_mismatch" in {item.reason for item in decision.conflicts}


def test_scope_catalog_requires_explicit_task_scope(tmp_path: Path):
    (tmp_path / "projectctl.parallel.yaml").write_text(
        """
schema_kind: projectctl.parallel_scope_catalog
schema_version: 1
tasks:
  a:
    task_id: a
    inputs:
      - path: src/a.py
        kind: exact
    writes:
      - path: src/a.py
        kind: exact
    resources: []
""".strip()
        + "\n",
        encoding="utf-8",
    )

    catalog = load_parallel_scope_catalog(tmp_path)
    assert catalog.tasks["a"].task_id == "a"


def test_build_plan_hashes_recorded_git_base_not_dirty_workspace(
    tmp_path: Path,
    monkeypatch,
):
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "config", "user.email", "test@example.com")
    git(repo, "config", "user.name", "Test")
    (repo / "src").mkdir()
    (repo / "src" / "a.py").write_text("value = 1\n", encoding="utf-8")
    git(repo, "add", "src/a.py")
    git(repo, "commit", "-q", "-m", "base")
    base = git(repo, "rev-parse", "HEAD")

    # The generic execution-input builder now demands human-managed policy
    # authority even when a parallel planner supplies an explicit scope.
    from projectctl.schemas.config import ProjectConfig, ProjectIdentity
    import yaml

    ctl = repo / ".projectctl"
    ctl.mkdir()
    config = ProjectConfig(project=ProjectIdentity(id="repo"))
    (ctl / "config.yaml").write_text(
        yaml.safe_dump(config.model_dump(mode="json")),
        encoding="utf-8",
    )
    (repo / "projectctl.parallel.yaml").write_text(
        yaml.safe_dump(
            {
                "schema_kind": "projectctl.parallel_scope_catalog",
                "schema_version": 1,
                "tasks": {
                    "a": {
                        "task_id": "a",
                        "inputs": [{"path": "src/a.py", "kind": "exact"}],
                        "writes": [{"path": "src/a.py", "kind": "exact"}],
                        "resources": [],
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    current_snapshot = snapshot(task("a"))
    scope = ParallelTaskScope(
        task_id="a",
        inputs=[ParallelPathScope(path="src/a.py")],
        writes=[ParallelPathScope(path="src/a.py")],
    )
    monkeypatch.setattr(
        "projectctl.parallel.service.load_project_config",
        lambda root: SimpleNamespace(project=SimpleNamespace(id="repo")),
    )
    monkeypatch.setattr(
        "projectctl.parallel.service.load_project_state",
        lambda root, allow_missing=True: ProjectState(project_id="repo"),
    )
    monkeypatch.setattr(
        "projectctl.parallel.service.capture_task_snapshot",
        lambda *args, **kwargs: current_snapshot,
    )
    monkeypatch.setattr(
        "projectctl.parallel.service.task_parallel_scope",
        lambda root, task_id: scope,
    )
    monkeypatch.setattr(
        "projectctl.parallel.service.current_branch",
        lambda root: "main",
    )
    monkeypatch.setattr(
        "projectctl.parallel.service.resolve_commit",
        lambda root, ref: base,
    )

    first = build_parallel_plan(repo, "a", now=NOW, persist=False)
    (repo / "src" / "a.py").write_text("value = 999\n", encoding="utf-8")
    second = build_parallel_plan(repo, "a", now=NOW, persist=False)

    assert first.base_commit == base
    assert second.base_commit == base
    assert first.inputs == second.inputs


def test_parallel_scope_is_part_of_plan_digest_contract():
    scope = ParallelTaskScope(
        task_id="a",
        inputs=[ParallelPathScope(path="src/a.py")],
        writes=[ParallelPathScope(path="src/a.py")],
        resources=["db:schema"],
    )
    changed = scope.model_copy(update={"resources": ["cache:index"]})
    assert digest(scope) != digest(changed)


def test_parallel_cli_is_registered():
    result = runner.invoke(app, ["parallel", "--help"])
    assert result.exit_code == 0, result.output
    assert "plan" in result.output
    assert "assess" in result.output
