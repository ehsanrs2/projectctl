from __future__ import annotations

import json
import subprocess
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from projectctl.cli.entry import app
from projectctl.core.digest import digest
from projectctl.core.enums import ModelProfile, ReasoningLevel, RunStatus
from projectctl.core.errors import IntegrationError
from projectctl.parallel import runtime
from projectctl.schemas.evidence import EvidenceManifest
from projectctl.schemas.parallel import (
    ParallelInputEvidence,
    ParallelIntegrationQueue,
    ParallelPathScope,
    ParallelPlan,
    ParallelQueueEntry,
    ParallelRunBinding,
)
from projectctl.schemas.run import RunManifest, WorkerDescriptor
from projectctl.storage.runs import RunStore

NOW = datetime(2026, 10, 7, 9, 30, tzinfo=timezone.utc)
runner = CliRunner()


def git(root: Path, *args: str, input_bytes: bytes | None = None):
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        input=input_bytes,
        capture_output=True,
        check=True,
    )
    return result.stdout.decode().strip()


def worker() -> WorkerDescriptor:
    return WorkerDescriptor(
        provider="codex",
        model_profile=ModelProfile.BALANCED,
        reasoning=ReasoningLevel.MEDIUM,
    )


def parallel_plan(
    task_id: str,
    *,
    base: str = "a" * 40,
    target: str = "main",
    writes: list[ParallelPathScope] | None = None,
    inputs: list[ParallelPathScope] | None = None,
) -> ParallelPlan:
    input_scopes = inputs or [ParallelPathScope(path=f"src/{task_id}.py")]
    return ParallelPlan(
        plan_id=f"parallel-{task_id}",
        project_id="repo",
        task_id=task_id,
        integration_target_ref=target,
        base_commit=base,
        project_state_digest="state",
        scoped_task_digest=f"task-{task_id}",
        scoped_task_ids=[task_id],
        scope_digest=f"scope-{task_id}",
        inputs=[
            ParallelInputEvidence(scope=item, digest=f"input-{index}")
            for index, item in enumerate(input_scopes)
        ],
        writes=writes or [ParallelPathScope(path=f"src/{task_id}.py")],
        resources=[],
        created_at=NOW,
    )


def binding(run_id: str, task_id: str, *, base: str = "a" * 40) -> ParallelRunBinding:
    admitted = parallel_plan(task_id, base=base)
    return ParallelRunBinding(
        run_id=run_id,
        task_id=task_id,
        preclaim_plan_digest="preclaim",
        admitted_plan=admitted,
        bound_at=NOW,
    )


def init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.email", "test@example.com"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.name", "Test"],
        check=True,
    )
    result = runner.invoke(app, ["init", str(repo)])
    assert result.exit_code == 0, result.output
    return repo


def create_run(
    repo: Path,
    run_id: str,
    task_id: str,
    *,
    status: RunStatus,
    created_at: datetime,
    base: str = "a" * 40,
    candidate: str | None = None,
) -> None:
    manifest = RunManifest(
        run_id=run_id,
        task_id=task_id,
        execution_plan_digest=f"exec-{run_id}",
        status=status,
        base_commit=base,
        candidate_commit=candidate,
        branch_name=f"projectctl/run/{run_id}",
        worktree_id=run_id,
        worker=worker(),
    )
    worktree = repo.parent / f"worktree-{run_id}"
    worktree.mkdir(exist_ok=True)
    RunStore(repo).create(
        manifest,
        worktree_path=worktree,
        now=created_at,
    )
    run_dir = repo / ".projectctl" / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "parallel-binding.json").write_text(
        json.dumps(binding(run_id, task_id, base=base).model_dump(mode="json")),
        encoding="utf-8",
    )


def test_run_store_rebind_clears_candidate_and_requires_fresh_verification(tmp_path: Path):
    repo = init_repo(tmp_path)
    create_run(
        repo,
        "run-a",
        "task-a",
        status=RunStatus.READY_TO_INTEGRATE,
        created_at=NOW,
        base="a" * 40,
        candidate="b" * 40,
    )

    rebound = RunStore(repo).rebind_for_reverification(
        "run-a",
        expected={RunStatus.READY_TO_INTEGRATE},
        execution_plan_digest="new-plan-digest",
        base_commit="c" * 40,
        now=NOW + timedelta(seconds=1),
    )

    assert rebound.status == RunStatus.VERIFYING
    assert rebound.base_commit == "c" * 40
    assert rebound.candidate_commit is None
    assert rebound.execution_plan_digest == "new-plan-digest"
    manifest = RunStore(repo).manifest("run-a")
    assert manifest.status == RunStatus.VERIFYING
    assert manifest.candidate_commit is None
    assert manifest.base_commit == "c" * 40
    assert any(
        item.event_type == "run.rebound_for_reverification"
        for item in RunStore(repo).events("run-a")
    )


def test_parallel_integration_queue_uses_creation_order_not_ready_time(
    tmp_path: Path,
    monkeypatch,
):
    repo = init_repo(tmp_path)
    create_run(
        repo,
        "run-first",
        "task-a",
        status=RunStatus.CLAIMED,
        created_at=NOW,
    )
    create_run(
        repo,
        "run-second",
        "task-b",
        status=RunStatus.READY_TO_INTEGRATE,
        created_at=NOW + timedelta(seconds=2),
    )
    monkeypatch.setattr(
        runtime,
        "load_project_config",
        lambda root: SimpleNamespace(project=SimpleNamespace(id="repo")),
    )
    monkeypatch.setattr(runtime, "current_branch", lambda root: "main")

    queue = runtime.build_parallel_integration_queue(repo, persist=False)

    assert [item.run_id for item in queue.entries] == [
        "run-first",
        "run-second",
    ]
    assert queue.entries[0].status == RunStatus.CLAIMED
    assert queue.entries[1].status == RunStatus.READY_TO_INTEGRATE


def test_candidate_outside_declared_write_scope_is_blocked(
    tmp_path: Path,
    monkeypatch,
):
    repo = init_repo(tmp_path)
    create_run(
        repo,
        "run-a",
        "task-a",
        status=RunStatus.READY_TO_INTEGRATE,
        created_at=NOW,
        candidate="b" * 40,
    )
    run_dir = repo / ".projectctl" / "runs" / "run-a"
    evidence = EvidenceManifest(
        run_id="run-a",
        task_id="task-a",
        base_commit="a" * 40,
        candidate_commit="b" * 40,
        diff_digest="diff",
        workspace_state_digest="workspace",
        worker_result_digest="worker",
        verification_manifest_digest="verification",
        verification_profile_digest="profile",
        changed_paths=["src/outside.py"],
        overall_pass=True,
        generated_at=NOW,
    )
    (run_dir / "evidence-manifest.json").write_text(
        json.dumps(evidence.model_dump(mode="json")),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        runtime,
        "reconcile_terminal_task",
        lambda *args, **kwargs: RunStore(repo).get("run-a"),
    )

    with pytest.raises(IntegrationError, match="outside"):
        runtime.validate_parallel_candidate_scope(repo, "run-a")

    record = RunStore(repo).get("run-a")
    assert record.status == RunStatus.NEEDS_DECISION


def test_target_advance_conflict_checks_inputs_and_writes():
    plan = parallel_plan(
        "task-a",
        inputs=[ParallelPathScope(path="src/read", kind="tree")],
        writes=[ParallelPathScope(path="src/write", kind="tree")],
    )

    conflicts = runtime._advance_conflicts_with_plan(
        plan,
        ["docs/ok.md", "src/read/config.py", "src/write/output.py"],
    )

    assert conflicts == ["src/read/config.py", "src/write/output.py"]


def test_patch_preflight_accepts_disjoint_target_advance(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@example.com"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "Test"], check=True)
    (repo / "a.txt").write_text("a1\n", encoding="utf-8")
    (repo / "b.txt").write_text("b1\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "base"], check=True)
    base = git(repo, "rev-parse", "HEAD")

    subprocess.run(["git", "-C", str(repo), "checkout", "-q", "-b", "candidate"], check=True)
    (repo / "a.txt").write_text("a2\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "commit", "-qam", "candidate"], check=True)
    candidate = git(repo, "rev-parse", "HEAD")
    patch = subprocess.run(
        ["git", "-C", str(repo), "diff", "--binary", base, candidate, "--"],
        capture_output=True,
        check=True,
    ).stdout

    subprocess.run(["git", "-C", str(repo), "checkout", "-q", "-B", "main", base], check=True)
    (repo / "b.txt").write_text("b2\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "commit", "-qam", "advance"], check=True)
    target = git(repo, "rev-parse", "HEAD")

    runtime._preflight_patch(repo, target_base=target, patch=patch)


def test_parallel_integrate_refuses_non_head(monkeypatch, tmp_path: Path):
    root = tmp_path
    item = ParallelQueueEntry(
        position=1,
        run_id="run-first",
        task_id="task-first",
        status=RunStatus.READY_TO_INTEGRATE,
        created_at=NOW,
        base_commit="a" * 40,
        target_ref="main",
    )
    queue = ParallelIntegrationQueue(
        generated_at=NOW,
        project_id="repo",
        target_ref="main",
        entries=[item],
    )
    monkeypatch.setattr(runtime, "project_lock", lambda *args, **kwargs: nullcontext())
    monkeypatch.setattr(
        runtime,
        "load_parallel_run_binding",
        lambda *args, **kwargs: binding("run-second", "task-second"),
    )
    monkeypatch.setattr(
        runtime,
        "build_parallel_integration_queue",
        lambda *args, **kwargs: queue,
    )

    with pytest.raises(IntegrationError, match="queue head"):
        runtime.integrate_parallel_run(root, "run-second")


def test_parallel_integrate_reapplies_and_reverifies_before_integration(
    monkeypatch,
    tmp_path: Path,
):
    root = tmp_path
    b = binding("run-a", "task-a")
    queue = ParallelIntegrationQueue(
        generated_at=NOW,
        project_id="repo",
        target_ref="main",
        entries=[
            ParallelQueueEntry(
                position=1,
                run_id="run-a",
                task_id="task-a",
                status=RunStatus.READY_TO_INTEGRATE,
                created_at=NOW,
                base_commit="a" * 40,
                target_ref="main",
            )
        ],
    )
    record = SimpleNamespace(status=RunStatus.READY_TO_INTEGRATE)
    calls: list[str] = []

    monkeypatch.setattr(runtime, "project_lock", lambda *args, **kwargs: nullcontext())
    monkeypatch.setattr(runtime, "load_parallel_run_binding", lambda *args, **kwargs: b)
    monkeypatch.setattr(runtime, "build_parallel_integration_queue", lambda *args, **kwargs: queue)
    monkeypatch.setattr(runtime, "RunStore", lambda root: SimpleNamespace(get=lambda run_id: record))
    monkeypatch.setattr(runtime, "validate_parallel_candidate_scope", lambda *args: calls.append("scope"))
    monkeypatch.setattr(
        runtime,
        "_load_json_model",
        lambda *args, **kwargs: SimpleNamespace(
            integration_target_ref="main",
            base_commit="a" * 40,
        ),
    )
    monkeypatch.setattr(runtime, "resolve_commit", lambda *args: "b" * 40)
    monkeypatch.setattr(runtime, "_reapply_locked", lambda *args: calls.append("reapply"))
    monkeypatch.setattr(
        runtime,
        "verify_run",
        lambda *args: SimpleNamespace(
            record=SimpleNamespace(status=RunStatus.READY_TO_INTEGRATE)
        ),
    )
    monkeypatch.setattr(runtime, "_integrate_run_locked", lambda *args: "integrated")

    result = runtime.integrate_parallel_run(root, "run-a")

    assert result == "integrated"
    assert calls == ["scope", "reapply", "scope"]


def test_parallel_cli_exposes_runtime_commands():
    result = runner.invoke(app, ["parallel", "--help"])
    assert result.exit_code == 0, result.output
    for command in ("run", "queue", "integrate", "recover"):
        assert command in result.output
