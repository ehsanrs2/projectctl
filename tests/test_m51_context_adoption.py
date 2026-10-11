from __future__ import annotations

import json
import subprocess
import threading
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from projectctl.application import execution
from projectctl.cli.entry import app
from projectctl.context import adoption
from projectctl.core.digest import digest
from projectctl.core.enums import ResourceClass, TaskStatus
from projectctl.core.errors import ConfigurationError, ProjectLockError, StaleSnapshotError
from projectctl.parallel.catalog import parse_parallel_scope_catalog_bytes
from projectctl.project.locking import execution_authority_gate
from projectctl.schema_export import PUBLIC_SCHEMAS
from projectctl.schemas.context_adoption import (
    ContextScopeAdoptionReceipt,
    ContextScopeAdoptionRequest,
    ContextScopeReview,
)
from projectctl.schemas.context_discovery import (
    ContextDiscoveryReport,
    ContextScopeSuggestion,
)
from projectctl.schemas.execution_input import ExecutionPathScope
from projectctl.schemas.task import (
    NormalizedTask,
    TaskSnapshot,
    TaskSource,
)


NOW = datetime(2026, 10, 7, 15, 0, tzinfo=timezone.utc)
runner = CliRunner()


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(
        ["git", "init", "-b", "main", str(root)],
        check=True,
        capture_output=True,
    )
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "user.name", "ProjectCTL Test")
    (root / "src").mkdir()
    (root / "tests").mkdir()
    (root / "src" / "service.py").write_text("VALUE = 1\n", encoding="utf-8")
    (root / "src" / "helper.py").write_text("HELPER = 1\n", encoding="utf-8")
    (root / "tests" / "test_service.py").write_text(
        "def test_value():\n    assert True\n",
        encoding="utf-8",
    )
    _git(root, "add", ".")
    _git(root, "commit", "-m", "fixture")
    return root


def _task(title: str = "Update service") -> NormalizedTask:
    return NormalizedTask(
        id="TASK-1",
        title=title,
        source=TaskSource(provider="test", external_id="TASK-1"),
        status=TaskStatus.READY,
        resource_class=ResourceClass.SMALL,
    )


def _snapshot(task: NormalizedTask) -> TaskSnapshot:
    return TaskSnapshot(
        provider="test",
        captured_at=NOW,
        source_revision="rev-1",
        tasks=[task],
    )


def _seed_suggestion(
    root: Path,
    *,
    task: NormalizedTask | None = None,
) -> tuple[ContextDiscoveryReport, ContextScopeSuggestion]:
    task = task or _task()
    base = _git(root, "rev-parse", "HEAD")
    report = ContextDiscoveryReport(
        discovery_id="context-discovery-test",
        generated_at=NOW,
        project_id="demo",
        task_id=task.id,
        integration_target_ref="main",
        base_commit=base,
        task_digest=adoption.semantic_task_digest(task),
        repository_file_count=3,
        indexed_python_files=0,
        candidates=[],
        evidence=[],
    )
    discovery_dir = root / ".projectctl" / "context" / "discovery" / task.id
    discovery_dir.mkdir(parents=True, exist_ok=True)
    (discovery_dir / f"{report.discovery_id}.json").write_text(
        json.dumps(report.model_dump(mode="json"), indent=2),
        encoding="utf-8",
    )

    suggestion = ContextScopeSuggestion(
        suggestion_id="context-scope-test",
        generated_at=NOW,
        project_id="demo",
        task_id=task.id,
        base_commit=base,
        discovery_digest=digest(report),
        input_scopes=[
            ExecutionPathScope(path="src/service.py", kind="exact"),
            ExecutionPathScope(path="src/helper.py", kind="exact"),
            ExecutionPathScope(path="tests/test_service.py", kind="exact"),
        ],
        write_scopes=[
            ExecutionPathScope(path="src/service.py", kind="exact"),
            ExecutionPathScope(path="tests/test_service.py", kind="exact"),
        ],
    )
    suggestion_dir = root / ".projectctl" / "context" / "suggestions" / task.id
    suggestion_dir.mkdir(parents=True, exist_ok=True)
    (suggestion_dir / f"{suggestion.suggestion_id}.json").write_text(
        json.dumps(suggestion.model_dump(mode="json"), indent=2),
        encoding="utf-8",
    )
    return report, suggestion


def _patch_project(monkeypatch, task: NormalizedTask | None = None) -> NormalizedTask:
    task = task or _task()
    monkeypatch.setattr(
        adoption,
        "load_project_config",
        lambda root: SimpleNamespace(project=SimpleNamespace(id="demo")),
    )
    monkeypatch.setattr(
        adoption,
        "capture_task_snapshot",
        lambda *args, **kwargs: _snapshot(task),
    )
    monkeypatch.setattr(adoption, "_assert_no_active_runs", lambda root: None)
    return task


def _review(root: Path, monkeypatch) -> ContextScopeReview:
    _patch_project(monkeypatch)
    _, suggestion = _seed_suggestion(root)
    return adoption.create_scope_review(
        root,
        "TASK-1",
        suggestion_id=suggestion.suggestion_id,
        resources=["service-registry"],
    )


def test_review_is_additive_and_preserves_existing_scope(
    tmp_path: Path,
    monkeypatch,
):
    root = _repo(tmp_path)
    catalog = root / "projectctl.parallel.yaml"
    catalog.write_text(
        "schema_kind: projectctl.parallel_scope_catalog\n"
        "schema_version: 1\n"
        "tasks:\n"
        "  TASK-1:\n"
        "    task_id: TASK-1\n"
        "    inputs:\n"
        "      - path: src/service.py\n"
        "        kind: exact\n"
        "    writes:\n"
        "      - path: src/service.py\n"
        "        kind: exact\n"
        "    resources:\n"
        "      - existing-resource\n",
        encoding="utf-8",
    )
    _patch_project(monkeypatch)
    _, suggestion = _seed_suggestion(root)

    review = adoption.create_scope_review(
        root,
        "TASK-1",
        suggestion_id=suggestion.suggestion_id,
        input_paths=["src/helper.py"],
        write_paths=["tests/test_service.py"],
        resources=["new-resource"],
    )

    assert review.mutation_mode == "additive"
    assert {item.path for item in review.proposed_scope.inputs} == {
        "src/service.py",
        "src/helper.py",
    }
    assert {item.path for item in review.proposed_scope.writes} == {
        "src/service.py",
        "tests/test_service.py",
    }
    assert review.proposed_scope.resources == [
        "existing-resource",
        "new-resource",
    ]
    assert review.added_inputs == ["src/helper.py"]
    assert review.added_writes == ["tests/test_service.py"]
    assert "src/service.py" in adoption.render_review_diff(review)
    assert catalog.read_text(encoding="utf-8").startswith(
        "schema_kind: projectctl.parallel_scope_catalog"
    )


def test_adoption_requires_exact_review_digest_and_does_not_mutate_on_mismatch(
    tmp_path: Path,
    monkeypatch,
):
    root = _repo(tmp_path)
    review = _review(root, monkeypatch)
    catalog = root / "projectctl.parallel.yaml"
    assert not catalog.exists()

    with pytest.raises(ConfigurationError, match="Approval digest"):
        adoption.adopt_scope_review(
            root,
            "TASK-1",
            review_id=review.review_id,
            approval_digest="sha256:not-the-review",
        )

    assert not catalog.exists()


def test_catalog_drift_after_review_fails_closed(
    tmp_path: Path,
    monkeypatch,
):
    root = _repo(tmp_path)
    review = _review(root, monkeypatch)
    catalog = root / "projectctl.parallel.yaml"
    catalog.write_text(
        "schema_kind: projectctl.parallel_scope_catalog\n"
        "schema_version: 1\n"
        "tasks: {}\n",
        encoding="utf-8",
    )

    with pytest.raises(StaleSnapshotError, match="catalog changed"):
        adoption.adopt_scope_review(
            root,
            "TASK-1",
            review_id=review.review_id,
            approval_digest=digest(review),
        )


def test_target_advance_after_review_fails_closed(
    tmp_path: Path,
    monkeypatch,
):
    root = _repo(tmp_path)
    review = _review(root, monkeypatch)
    (root / "README.md").write_text("advance\n", encoding="utf-8")
    _git(root, "add", "README.md")
    _git(root, "commit", "-m", "advance")

    with pytest.raises(StaleSnapshotError, match="integration target advanced"):
        adoption.adopt_scope_review(
            root,
            "TASK-1",
            review_id=review.review_id,
            approval_digest=digest(review),
        )


def test_active_run_guard_blocks_authority_mutation(
    tmp_path: Path,
    monkeypatch,
):
    root = _repo(tmp_path)
    review = _review(root, monkeypatch)
    monkeypatch.setattr(
        adoption,
        "_assert_no_active_runs",
        lambda root: (_ for _ in ()).throw(
            ConfigurationError("Scope authority cannot change while project runs are active")
        ),
    )

    with pytest.raises(ConfigurationError, match="runs are active"):
        adoption.adopt_scope_review(
            root,
            "TASK-1",
            review_id=review.review_id,
            approval_digest=digest(review),
        )


def test_adoption_writes_exact_review_and_persists_request_receipt(
    tmp_path: Path,
    monkeypatch,
):
    root = _repo(tmp_path)
    review = _review(root, monkeypatch)

    receipt = adoption.adopt_scope_review(
        root,
        "TASK-1",
        review_id=review.review_id,
        approval_digest=digest(review),
    )

    catalog = root / "projectctl.parallel.yaml"
    assert catalog.read_text(encoding="utf-8") == review.proposed_catalog_yaml
    assert isinstance(receipt, ContextScopeAdoptionReceipt)
    assert receipt.review_digest == digest(review)
    assert receipt.catalog_after_digest == review.proposed_catalog_digest

    adoption_dir = (
        root
        / ".projectctl"
        / "context"
        / "adoptions"
        / "TASK-1"
        / receipt.adoption_id
    )
    request = ContextScopeAdoptionRequest.model_validate_json(
        (adoption_dir / "request.json").read_text(encoding="utf-8")
    )
    persisted = ContextScopeAdoptionReceipt.model_validate_json(
        (adoption_dir / "receipt.json").read_text(encoding="utf-8")
    )
    assert request.review_digest == digest(review)
    assert persisted.adoption_id == receipt.adoption_id


def test_retry_recovers_receipt_after_crash_post_policy_write(
    tmp_path: Path,
    monkeypatch,
):
    root = _repo(tmp_path)
    review = _review(root, monkeypatch)
    real_atomic_json = adoption._atomic_json
    crashed = {"done": False}

    def crash_before_receipt(path, value):
        if path.name == "receipt.json" and not crashed["done"]:
            crashed["done"] = True
            raise RuntimeError("simulated receipt crash")
        return real_atomic_json(path, value)

    monkeypatch.setattr(adoption, "_atomic_json", crash_before_receipt)
    with pytest.raises(RuntimeError, match="simulated receipt crash"):
        adoption.adopt_scope_review(
            root,
            "TASK-1",
            review_id=review.review_id,
            approval_digest=digest(review),
        )

    catalog = root / "projectctl.parallel.yaml"
    assert catalog.read_text(encoding="utf-8") == review.proposed_catalog_yaml

    monkeypatch.setattr(adoption, "_atomic_json", real_atomic_json)
    receipt = adoption.adopt_scope_review(
        root,
        "TASK-1",
        review_id=review.review_id,
        approval_digest=digest(review),
    )

    assert receipt.applied is True
    assert receipt.catalog_after_digest == review.proposed_catalog_digest


def test_review_selection_must_be_subset_of_suggestion(
    tmp_path: Path,
    monkeypatch,
):
    root = _repo(tmp_path)
    _patch_project(monkeypatch)
    _, suggestion = _seed_suggestion(root)

    with pytest.raises(ConfigurationError, match="outside the suggestion"):
        adoption.create_scope_review(
            root,
            "TASK-1",
            suggestion_id=suggestion.suggestion_id,
            write_paths=["src/not-suggested.py"],
        )


def test_m51_public_schema_and_cli_surface():
    assert PUBLIC_SCHEMAS["context-scope-review.v1.schema.json"] is ContextScopeReview
    assert (
        PUBLIC_SCHEMAS["context-scope-adoption-request.v1.schema.json"]
        is ContextScopeAdoptionRequest
    )
    assert (
        PUBLIC_SCHEMAS["context-scope-adoption-receipt.v1.schema.json"]
        is ContextScopeAdoptionReceipt
    )

    result = runner.invoke(app, ["context", "--help"])
    assert result.exit_code == 0, result.output
    assert "review-scope" in result.output
    assert "adopt-scope" in result.output


def test_existing_tree_scope_covers_exact_suggestion_without_redundant_addition(
    tmp_path: Path,
    monkeypatch,
):
    root = _repo(tmp_path)
    (root / "projectctl.parallel.yaml").write_text(
        "schema_kind: projectctl.parallel_scope_catalog\n"
        "schema_version: 1\n"
        "tasks:\n"
        "  TASK-1:\n"
        "    task_id: TASK-1\n"
        "    inputs:\n"
        "      - path: src\n"
        "        kind: tree\n"
        "    writes:\n"
        "      - path: src\n"
        "        kind: tree\n"
        "    resources: []\n",
        encoding="utf-8",
    )
    _patch_project(monkeypatch)
    _, suggestion = _seed_suggestion(root)

    review = adoption.create_scope_review(
        root,
        "TASK-1",
        suggestion_id=suggestion.suggestion_id,
        input_paths=["tests/test_service.py"],
        write_paths=["tests/test_service.py"],
    )

    assert review.added_inputs == ["tests/test_service.py"]
    assert review.added_writes == ["tests/test_service.py"]
    assert not any(
        item.path == "src/service.py" and item.kind == "exact"
        for item in review.proposed_scope.inputs
    )


def test_review_rejects_noop_selection(
    tmp_path: Path,
    monkeypatch,
):
    root = _repo(tmp_path)
    (root / "projectctl.parallel.yaml").write_text(
        "schema_kind: projectctl.parallel_scope_catalog\n"
        "schema_version: 1\n"
        "tasks:\n"
        "  TASK-1:\n"
        "    task_id: TASK-1\n"
        "    inputs:\n"
        "      - path: src\n"
        "        kind: tree\n"
        "      - path: tests\n"
        "        kind: tree\n"
        "    writes:\n"
        "      - path: src\n"
        "        kind: tree\n"
        "      - path: tests\n"
        "        kind: tree\n"
        "    resources: []\n",
        encoding="utf-8",
    )
    _patch_project(monkeypatch)
    _, suggestion = _seed_suggestion(root)

    with pytest.raises(ConfigurationError, match="adds nothing"):
        adoption.create_scope_review(
            root,
            "TASK-1",
            suggestion_id=suggestion.suggestion_id,
        )


def test_adoption_refuses_scope_authority_symlink(
    tmp_path: Path,
    monkeypatch,
):
    root = _repo(tmp_path)
    target = root / "actual-scope.yaml"
    target.write_text(
        "schema_kind: projectctl.parallel_scope_catalog\n"
        "schema_version: 1\n"
        "tasks: {}\n",
        encoding="utf-8",
    )
    (root / "projectctl.parallel.yaml").symlink_to(target.name)
    _patch_project(monkeypatch)
    _, suggestion = _seed_suggestion(root)

    with pytest.raises(ConfigurationError, match="symlink"):
        adoption.create_scope_review(
            root,
            "TASK-1",
            suggestion_id=suggestion.suggestion_id,
        )


def test_catalog_state_parses_the_exact_bytes_it_digests(
    tmp_path: Path,
    monkeypatch,
):
    root = _repo(tmp_path)
    catalog_path = root / "projectctl.parallel.yaml"
    raw = (
        "schema_kind: projectctl.parallel_scope_catalog\\n"
        "schema_version: 1\\n"
        "tasks: {}\\n"
    ).encode("utf-8")
    catalog_path.write_bytes(raw)
    original_read_bytes = Path.read_bytes
    reads = []

    def counted_read_bytes(path: Path):
        if path == catalog_path:
            reads.append(path)
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", counted_read_bytes)
    path, captured, before_digest, catalog = adoption._catalog_state(root)

    assert path == catalog_path
    assert captured == raw
    assert len(reads) == 1
    assert before_digest == adoption._sha256_bytes(raw)
    assert catalog.tasks == {}


def test_scope_adoption_gate_excludes_new_run_admission(
    tmp_path: Path,
    monkeypatch,
):
    root = _repo(tmp_path)
    review = _review(root, monkeypatch)
    validation_entered = threading.Event()
    continue_validation = threading.Event()
    validation_calls = 0
    adoption_errors = []
    original_validate = adoption._validate_review_before_apply

    def pause_validation(project_root: Path, current_review: ContextScopeReview):
        nonlocal validation_calls
        validation_calls += 1
        if validation_calls == 1:
            validation_entered.set()
            if not continue_validation.wait(timeout=5):
                raise AssertionError("Timed out waiting to resume adoption validation.")
        return original_validate(project_root, current_review)

    monkeypatch.setattr(adoption, "_validate_review_before_apply", pause_validation)
    preflight_calls = []
    monkeypatch.setattr(
        execution,
        "_assert_task_store_execution_capable",
        lambda project_root: preflight_calls.append(project_root),
    )
    monkeypatch.setattr(
        execution,
        "build_next_execution_bundle",
        lambda *args, **kwargs: pytest.fail(
            "Run planning must not begin while scope adoption owns the authority gate."
        ),
    )

    def adopt():
        try:
            adoption.adopt_scope_review(
                root,
                "TASK-1",
                review_id=review.review_id,
                approval_digest=digest(review),
            )
        except BaseException as exc:
            adoption_errors.append(exc)

    worker = threading.Thread(target=adopt)
    worker.start()
    assert validation_entered.wait(timeout=5)

    with pytest.raises(ProjectLockError, match="execution-authority"):
        execution.prepare_next_run(root)
    assert preflight_calls == []
    assert not (root / "projectctl.parallel.yaml").exists()

    continue_validation.set()
    worker.join(timeout=5)
    assert not worker.is_alive()
    assert adoption_errors == []
    assert (root / "projectctl.parallel.yaml").read_text(encoding="utf-8") == (
        review.proposed_catalog_yaml
    )


def test_run_admission_gate_wins_and_adoption_rechecks_active_runs(
    tmp_path: Path,
    monkeypatch,
):
    root = _repo(tmp_path)
    review = _review(root, monkeypatch)
    gate_entered = threading.Event()
    release_gate = threading.Event()
    gate_errors = []

    def hold_run_admission_gate():
        try:
            with execution_authority_gate(root):
                gate_entered.set()
                if not release_gate.wait(timeout=5):
                    raise AssertionError("Timed out waiting to release run-admission gate.")
        except BaseException as exc:
            gate_errors.append(exc)

    worker = threading.Thread(target=hold_run_admission_gate)
    worker.start()
    assert gate_entered.wait(timeout=5)

    with pytest.raises(ProjectLockError, match="execution-authority"):
        adoption.adopt_scope_review(
            root,
            "TASK-1",
            review_id=review.review_id,
            approval_digest=digest(review),
        )
    assert not (root / "projectctl.parallel.yaml").exists()

    release_gate.set()
    worker.join(timeout=5)
    assert not worker.is_alive()
    assert gate_errors == []

    monkeypatch.setattr(
        adoption,
        "_assert_no_active_runs",
        lambda project_root: (_ for _ in ()).throw(
            ConfigurationError(
                "Scope authority cannot change while project runs are active: run-1:claimed"
            )
        ),
    )
    with pytest.raises(ConfigurationError, match="runs are active"):
        adoption.adopt_scope_review(
            root,
            "TASK-1",
            review_id=review.review_id,
            approval_digest=digest(review),
        )
    assert not (root / "projectctl.parallel.yaml").exists()
