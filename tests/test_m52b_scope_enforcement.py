"""M5.2b Slice B: execution policy is a durable, fail-closed run input."""
from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

from projectctl.application.execution_inputs import (
    build_execution_input_manifest,
    execution_input_semantic_digest,
    load_execution_input,
    validate_execution_scope_authority,
    validate_preclaim_execution_input,
)
from projectctl.application.verification import _scope_authority_violations
from projectctl.core.enums import ResourceClass, TaskStatus
from projectctl.core.errors import ConfigurationError, StaleSnapshotError
from projectctl.project.state import load_project_state, semantic_project_state_digest
from projectctl.schemas.config import ProjectConfig, ProjectIdentity
from projectctl.schemas.execution_input import (
    ExecutionInputManifest,
    ExecutionInputManifestV1,
    parse_execution_input_manifest,
)
from projectctl.schemas.task import NormalizedTask, TaskSnapshot, TaskSource
from projectctl.verification.diff import SYSTEM_PROTECTED_PATHS

NOW = datetime(2026, 10, 12, 9, 0, tzinfo=timezone.utc)


def _git(root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(root), *args],
        check=True, text=True, capture_output=True,
    )
    return completed.stdout.strip()


def _set_policy(root: Path, mode: str) -> None:
    config = ProjectConfig(
        project=ProjectIdentity(id="demo"),
        scope_governance={"mode": mode},
    )
    path = root / ".projectctl" / "config.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(config.model_dump(mode="json"), sort_keys=False),
        encoding="utf-8",
    )


def _init(root: Path, *, mode: str = "optional") -> str:
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "user.name", "ProjectCTL test")
    (root / "src").mkdir()
    (root / "src" / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    _set_policy(root, mode)
    _git(root, "add", "src/app.py")
    _git(root, "commit", "-q", "-m", "baseline")
    return _git(root, "rev-parse", "HEAD")


def _scope(root: Path, *, filename: str = "projectctl.scope.yaml") -> None:
    kind = (
        "projectctl.parallel_scope_catalog"
        if filename == "projectctl.parallel.yaml"
        else "projectctl.execution_scope_catalog"
    )
    data = {
        "schema_kind": kind,
        "schema_version": 1,
        "tasks": {
            "task-a": {
                "task_id": "task-a",
                "inputs": [{"path": "src/app.py", "kind": "exact"}],
                "writes": [{"path": "src/app.py", "kind": "exact"}],
                "resources": [],
            },
        },
    }
    (root / filename).write_text(
        yaml.safe_dump(data, sort_keys=False), encoding="utf-8"
    )


def _snapshot() -> TaskSnapshot:
    task = NormalizedTask(
        id="task-a",
        title="Task A",
        source=TaskSource(
            provider="test", external_id="task-a", revision="rev-a"
        ),
        status=TaskStatus.READY,
        resource_class=ResourceClass.SMALL,
        dependencies=[],
    )
    return TaskSnapshot(
        provider="test",
        captured_at=NOW,
        source_revision="snapshot",
        tasks=[task],
    )


def _manifest(root: Path, base: str, *, explicit_scope=None):
    return build_execution_input_manifest(
        root,
        task_id="task-a",
        tasks=_snapshot(),
        scheduler_task_snapshot_digest="scheduler-observation",
        project_state_digest=semantic_project_state_digest(
            load_project_state(root, allow_missing=True)
        ),
        integration_target_ref=_git(root, "branch", "--show-current"),
        base_commit=base,
        now=NOW,
        explicit_scope=explicit_scope,
    )


def test_required_without_task_scope_fails_before_run_admission(tmp_path):
    root = tmp_path / "repo"
    base = _init(root, mode="required")
    with pytest.raises(ConfigurationError, match="scope_governance.mode=required"):
        _manifest(root, base)
    assert not (root / ".projectctl" / "runs").exists()


@pytest.mark.parametrize("file", ["projectctl.scope.yaml", "projectctl.parallel.yaml"])
def test_required_declared_scope_is_pinned_for_serial_execution(tmp_path, file):
    root = tmp_path / "repo"
    base = _init(root, mode="required")
    _scope(root, filename=file)
    manifest = _manifest(root, base)
    assert isinstance(manifest, ExecutionInputManifest)
    assert manifest.schema_version == 2
    assert manifest.scope_governance_mode == "required"
    assert manifest.scope_catalog_source == (
        "legacy" if file.endswith("parallel.yaml") else "canonical"
    )
    assert len(manifest.code_inputs) == 1
    assert len(manifest.write_scopes) == 1
    assert manifest.scope_policy_digest
    validate_execution_scope_authority(root, manifest)
    assert _scope_authority_violations(root, manifest) == []


def test_optional_serial_without_scope_keeps_legacy_behavior(tmp_path):
    root = tmp_path / "repo"
    base = _init(root)
    manifest = _manifest(root, base)
    assert manifest.scope_governance_mode == "optional"
    assert manifest.scope_catalog_source == "absent"
    assert manifest.scope_policy_digest is None
    assert manifest.write_scopes == []
    validate_execution_scope_authority(root, manifest)


def test_optional_missing_task_can_build_but_explicit_fake_scope_is_rejected(tmp_path):
    root = tmp_path / "repo"
    base = _init(root)
    _scope(root)
    content = yaml.safe_load((root / "projectctl.scope.yaml").read_text())
    scope = content["tasks"].pop("task-a")
    content["tasks"]["other"] = {**scope, "task_id": "other"}
    (root / "projectctl.scope.yaml").write_text(yaml.safe_dump(content))
    manifest = _manifest(root, base)
    assert manifest.scope_policy_digest is None
    with pytest.raises(ConfigurationError, match="must match"):
        _manifest(root, base, explicit_scope=scope)


def test_mode_change_invalidates_admitted_scope_even_when_path_is_same(tmp_path):
    root = tmp_path / "repo"
    base = _init(root, mode="required")
    _scope(root)
    manifest = _manifest(root, base)
    _set_policy(root, "optional")
    with pytest.raises(StaleSnapshotError, match="mode changed"):
        validate_execution_scope_authority(root, manifest)
    assert _scope_authority_violations(root, manifest)


def test_catalog_switch_with_identical_scope_still_invalidates_plan(tmp_path):
    root = tmp_path / "repo"
    base = _init(root, mode="required")
    _scope(root)
    manifest = _manifest(root, base)
    (root / "projectctl.scope.yaml").unlink()
    _scope(root, filename="projectctl.parallel.yaml")
    with pytest.raises(StaleSnapshotError, match="catalog authority changed"):
        validate_execution_scope_authority(root, manifest)


def test_scope_disappearance_and_dual_source_fail_closed(tmp_path):
    root = tmp_path / "repo"
    base = _init(root, mode="required")
    _scope(root)
    manifest = _manifest(root, base)
    (root / "projectctl.scope.yaml").unlink()
    with pytest.raises(StaleSnapshotError, match="catalog authority changed"):
        validate_execution_scope_authority(root, manifest)
    _scope(root)
    _scope(root, filename="projectctl.parallel.yaml")
    assert _scope_authority_violations(root, manifest)


def test_scope_mutation_invalidates_existing_manifest(tmp_path):
    root = tmp_path / "repo"
    base = _init(root, mode="required")
    _scope(root)
    manifest = _manifest(root, base)
    file = root / "projectctl.scope.yaml"
    content = yaml.safe_load(file.read_text())
    content["tasks"]["task-a"]["writes"] = [{"path": "src", "kind": "tree"}]
    file.write_text(yaml.safe_dump(content))
    with pytest.raises(StaleSnapshotError, match="scope declaration changed"):
        validate_execution_scope_authority(root, manifest)


def test_versioned_roundtrip_preserves_historical_v1_digest(tmp_path):
    root = tmp_path / "repo"
    base = _init(root)
    current = _manifest(root, base)
    raw = current.model_dump(mode="json")
    raw["schema_version"] = 1
    raw.pop("scope_governance_mode")
    raw.pop("scope_catalog_source")
    historical = parse_execution_input_manifest(raw)
    assert isinstance(historical, ExecutionInputManifestV1)
    assert execution_input_semantic_digest(historical) != execution_input_semantic_digest(
        current
    )
    path = root / "old-input.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    assert load_execution_input(path) == historical

    _set_policy(root, "required")
    with pytest.raises(StaleSnapshotError, match="Historical v1"):
        validate_execution_scope_authority(root, historical)
    assert _scope_authority_violations(root, historical)


def test_preclaim_rejects_changed_scope_without_claim(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    base = _init(root, mode="required")
    _scope(root)
    manifest = _manifest(root, base)
    monkeypatch.setattr(
        "projectctl.application.execution_inputs.capture_task_snapshot",
        lambda *_args, **_kwargs: _snapshot(),
    )
    validate_preclaim_execution_input(root, manifest)
    _set_policy(root, "optional")
    with pytest.raises(StaleSnapshotError, match="mode changed"):
        validate_preclaim_execution_input(root, manifest)


def test_required_policy_is_rejected_if_manifest_is_missing_at_verification(tmp_path):
    root = tmp_path / "repo"
    _init(root, mode="required")
    assert "required_scope_evidence_missing" in _scope_authority_violations(
        root, None
    )[0]
    _set_policy(root, "optional")
    assert _scope_authority_violations(root, None) == []


def test_scopes_are_system_protected_against_worker_edits():
    assert "projectctl.scope.yaml" in SYSTEM_PROTECTED_PATHS
    assert "projectctl.parallel.yaml" in SYSTEM_PROTECTED_PATHS


def test_new_manifest_schema_cannot_omit_governance_fields(tmp_path):
    root = tmp_path / "repo"
    base = _init(root)
    payload = _manifest(root, base).model_dump(mode="json")
    payload.pop("scope_governance_mode")
    with pytest.raises(Exception):
        parse_execution_input_manifest(payload)
    payload["schema_version"] = 100
    with pytest.raises(ValueError, match="Unsupported"):
        parse_execution_input_manifest(payload)


def test_required_scope_blocks_legacy_worker_start_and_direct_context(tmp_path):
    from types import SimpleNamespace
    from projectctl.application.execution import _load_admitted_execution_contract
    from projectctl.context.assembler import assemble_context

    root = tmp_path / "repo"
    _init(root, mode="required")
    legacy_plan = SimpleNamespace(execution_input_digest=None)
    with pytest.raises(StaleSnapshotError, match="Legacy run"):
        _load_admitted_execution_contract(root, root, legacy_plan)
    with pytest.raises(ConfigurationError, match="unscoped WorkerRequest"):
        assemble_context(
            root,
            worktree=root,
            run_id="run-test",
            plan=None,
            strategy=None,
            context_manifest_path=".projectctl/runs/run-test/context-manifest.json",
        )

    _set_policy(root, "optional")
    assert _load_admitted_execution_contract(root, root, legacy_plan) == (None, None)
