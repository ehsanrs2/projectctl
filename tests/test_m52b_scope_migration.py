from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from projectctl.cli.entry import app
from projectctl.context.adoption import _catalog_state
from projectctl.core.errors import ConfigurationError
from projectctl.execution_scope.catalog import resolve_execution_scope_catalog
from projectctl.execution_scope.migration import (
    _pending_journals,
    apply_scope_migration,
    preview_scope_migration,
)
from projectctl.schemas.context_adoption import (
    ContextScopeReview,
    ContextScopeReviewV1,
    ContextScopeAdoptionRequestV1,
    ContextScopeAdoptionReceiptV1,
    parse_context_scope_review,
    parse_context_scope_adoption_request,
    parse_context_scope_adoption_receipt,
)
from projectctl.schema_export import PUBLIC_SCHEMAS


def git(root: Path, *args: str):
    return subprocess.run(
        ["git", "-C", str(root), *args],
        text=True, capture_output=True, check=True,
    ).stdout.strip()


def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-q")
    git(root, "config", "user.email", "test@example.com")
    git(root, "config", "user.name", "ProjectCTL Test")
    (root / ".projectctl").mkdir()
    (root / ".gitignore").write_text(".projectctl/\n", encoding="utf-8")
    (root / "projectctl.parallel.yaml").write_text(
        "schema_kind: projectctl.parallel_scope_catalog\n"
        "schema_version: 1\n"
        "tasks:\n"
        "  task-a:\n"
        "    task_id: task-a\n"
        "    inputs:\n"
        "      - path: src/app.py\n"
        "        kind: exact\n"
        "    writes:\n"
        "      - path: src/app.py\n"
        "        kind: exact\n"
        "    resources: []\n",
        encoding="utf-8",
    )
    git(root, "add", ".gitignore", "projectctl.parallel.yaml")
    git(root, "commit", "-q", "-m", "legacy scope")
    return root


def test_preview_does_not_change_files_and_apply_produces_canonical(tmp_path):
    root = repo(tmp_path)
    before = (root / "projectctl.parallel.yaml").read_bytes()
    preview = preview_scope_migration(root)
    assert preview.target_yaml.startswith("schema_kind: projectctl.execution_scope_catalog")
    assert preview.old_path == "projectctl.parallel.yaml"
    assert preview.new_path == "projectctl.scope.yaml"
    assert not (root / "projectctl.scope.yaml").exists()
    assert (root / "projectctl.parallel.yaml").read_bytes() == before
    assert not _pending_journals(root)

    receipt = apply_scope_migration(root)
    assert receipt["schema_version"] == 1 and receipt["applied"] is True
    assert not (root / "projectctl.parallel.yaml").exists()
    assert resolve_execution_scope_catalog(root).source == "canonical"
    assert (root / "projectctl.scope.yaml").read_text() == preview.target_yaml
    assert not _pending_journals(root)
    assert git(root, "status", "--porcelain")  # operator must inspect/commit
    assert _catalog_state(root)[3].tasks["task-a"].task_id == "task-a"


def test_cli_is_read_only_by_default_and_requires_explicit_apply(tmp_path):
    root = repo(tmp_path)
    preview = CliRunner().invoke(
        app, ["scope", "migrate", "--project", str(root)]
    )
    assert preview.exit_code == 0, preview.output
    assert "read-only" in preview.output
    assert not (root / "projectctl.scope.yaml").exists()
    applied = CliRunner().invoke(
        app, ["scope", "migrate", "--project", str(root), "--apply"]
    )
    assert applied.exit_code == 0, applied.output
    assert "Inspect and commit" in applied.output


def test_migration_requires_clean_repo_and_unique_valid_legacy(tmp_path):
    root = repo(tmp_path)
    (root / "untracked.txt").write_text("dirty\n")
    with pytest.raises(ConfigurationError, match="Commit or stash"):
        apply_scope_migration(root)
    (root / "untracked.txt").unlink()

    (root / "projectctl.scope.yaml").write_text("invalid\n")
    with pytest.raises(ConfigurationError, match="Both"):
        preview_scope_migration(root)
    with pytest.raises(ConfigurationError):
        apply_scope_migration(root)


def test_legacy_only_cannot_be_reviewed_until_explicit_migration(tmp_path):
    root = repo(tmp_path)
    with pytest.raises(ConfigurationError, match="scope migrate"):
        _catalog_state(root)


def test_dual_file_crash_state_is_fail_closed_then_recoverable(tmp_path, monkeypatch):
    root = repo(tmp_path)
    original_unlink = Path.unlink

    def interrupt_legacy_unlink(self, *args, **kwargs):
        if self == root / "projectctl.parallel.yaml":
            raise RuntimeError("simulated crash after canonical write")
        return original_unlink(self, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "unlink", interrupt_legacy_unlink)
        with pytest.raises(RuntimeError, match="simulated crash"):
            apply_scope_migration(root)

    assert (root / "projectctl.scope.yaml").exists()
    assert (root / "projectctl.parallel.yaml").exists()
    with pytest.raises(ConfigurationError, match="Pending/ambiguous"):
        resolve_execution_scope_catalog(root)
    assert len(_pending_journals(root)) == 1

    with pytest.raises(ConfigurationError, match="Pending scope migration"):
        apply_scope_migration(root)
    receipt = apply_scope_migration(root, recover=True)
    assert receipt["applied"] is True
    assert resolve_execution_scope_catalog(root).source == "canonical"


def test_crash_after_legacy_retirement_is_recoverable(tmp_path, monkeypatch):
    import projectctl.execution_scope.migration as migration

    root = repo(tmp_path)
    original = migration._atomic_write

    def interrupt_receipt(path, payload):
        if path.name == "receipt.json":
            raise RuntimeError("simulated crash before receipt")
        return original(path, payload)

    with monkeypatch.context() as patch:
        patch.setattr(migration, "_atomic_write", interrupt_receipt)
        with pytest.raises(RuntimeError, match="simulated crash"):
            migration.apply_scope_migration(root)

    assert not (root / "projectctl.parallel.yaml").exists()
    assert (root / "projectctl.scope.yaml").exists()
    assert len(_pending_journals(root)) == 1
    with pytest.raises(ConfigurationError, match="Pending/ambiguous"):
        resolve_execution_scope_catalog(root)
    receipt = migration.apply_scope_migration(root, recover=True)
    assert receipt["applied"] is True


def test_crash_before_policy_write_is_recoverable(tmp_path, monkeypatch):
    import projectctl.execution_scope.migration as migration

    root = repo(tmp_path)
    original = migration._atomic_write

    def interrupt_canonical(path, payload):
        if path == root / "projectctl.scope.yaml":
            raise RuntimeError("simulated crash before canonical write")
        return original(path, payload)

    with monkeypatch.context() as patch:
        patch.setattr(migration, "_atomic_write", interrupt_canonical)
        with pytest.raises(RuntimeError, match="simulated crash"):
            migration.apply_scope_migration(root)

    assert not (root / "projectctl.scope.yaml").exists()
    assert (root / "projectctl.parallel.yaml").exists()
    receipt = migration.apply_scope_migration(root, recover=True)
    assert receipt["applied"] is True


def test_tampered_pending_state_requires_manual_audit(tmp_path, monkeypatch):
    import projectctl.execution_scope.migration as migration
    root = repo(tmp_path)
    original = migration._atomic_write

    def interrupt_canonical(path, payload):
        if path == root / "projectctl.scope.yaml":
            raise RuntimeError("injected crash")
        return original(path, payload)

    with monkeypatch.context() as patch:
        patch.setattr(migration, "_atomic_write", interrupt_canonical)
        with pytest.raises(RuntimeError):
            migration.apply_scope_migration(root)

    (root / "projectctl.parallel.yaml").write_text("tampered\n", encoding="utf-8")
    with pytest.raises(ConfigurationError, match="source was edited"):
        migration.apply_scope_migration(root, recover=True)


def test_pending_context_adoption_blocks_migration(tmp_path):
    root = repo(tmp_path)
    request = root / ".projectctl" / "context" / "adoptions" / "task-a" / "id" / "request.json"
    request.parent.mkdir(parents=True)
    request.write_text("{}\n")
    with pytest.raises(ConfigurationError, match="Pending scope adoption"):
        apply_scope_migration(root)


def test_symlink_policy_cannot_be_migrated(tmp_path):
    root = repo(tmp_path)
    old = root / "projectctl.parallel.yaml"
    old.unlink()
    old.symlink_to(root / "missing.yaml")
    with pytest.raises(ConfigurationError, match="symlinked"):
        preview_scope_migration(root)


def test_historical_review_request_and_receipt_schemas_are_preserved():
    assert PUBLIC_SCHEMAS["context-scope-review.v1.schema.json"] is ContextScopeReviewV1
    assert PUBLIC_SCHEMAS["context-scope-review.v2.schema.json"] is ContextScopeReview
    assert PUBLIC_SCHEMAS["context-scope-adoption-request.v1.schema.json"] is ContextScopeAdoptionRequestV1
    assert PUBLIC_SCHEMAS["context-scope-adoption-receipt.v1.schema.json"] is ContextScopeAdoptionReceiptV1
    with pytest.raises(ValueError, match="Unsupported"):
        parse_context_scope_review({"schema_version": 3})
    with pytest.raises(ValueError, match="Unsupported"):
        parse_context_scope_adoption_request({"schema_version": 3})
    with pytest.raises(ValueError, match="Unsupported"):
        parse_context_scope_adoption_receipt({"schema_version": 3})


def test_v1_review_can_be_read_but_not_adopted_into_new_catalog(tmp_path):
    from datetime import datetime, timezone
    from projectctl.core.digest import digest
    from projectctl.context.adoption import adopt_scope_review, _load_review

    root = repo(tmp_path)
    old = ContextScopeReviewV1(
        review_id="legacy-review",
        created_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
        project_id="demo",
        task_id="task-a",
        integration_target_ref="main",
        base_commit="a" * 40,
        task_digest="task",
        discovery_digest="discovery",
        suggestion_id="suggestion",
        suggestion_digest="suggestion-digest",
        suggestion_artifact=".projectctl/context/suggestions/task-a/suggestion.json",
        catalog_before_present=True,
        catalog_before_digest="before",
        proposed_scope={
            "task_id": "task-a",
            "inputs": [{"path": "src/app.py"}],
            "writes": [{"path": "src/app.py"}],
        },
        proposed_catalog_digest="after",
        proposed_catalog_yaml="schema_kind: projectctl.parallel_scope_catalog\\n",
    )
    path = root / ".projectctl" / "context" / "reviews" / "task-a" / "legacy-review.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(old.model_dump(mode="json")), encoding="utf-8")
    assert isinstance(_load_review(path), ContextScopeReviewV1)
    with pytest.raises(ConfigurationError, match="audit-only"):
        adopt_scope_review(
            root, "task-a",
            review_id=old.review_id,
            approval_digest=digest(old),
        )
