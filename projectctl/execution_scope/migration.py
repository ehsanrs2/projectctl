"""Explicit, journaled migration from parallel scope to generic scope authority.

The two policy files cannot be atomically replaced together. A durable request
records exact source/target bytes before the first policy mutation; readers fail
closed while both files exist. Recovery is explicit, never guessed.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path

import yaml

from projectctl.core.enums import RunStatus
from projectctl.core.errors import ConfigurationError
from projectctl.execution_scope.catalog import (
    EXECUTION_SCOPE_PATH,
    LEGACY_PARALLEL_SCOPE_PATH,
    resolve_execution_scope_catalog,
)
from projectctl.project.locking import execution_authority_gated, project_lock
from projectctl.storage.runs import RunStore

_BLOCKING_RUN_STATUSES = {
    RunStatus.PLANNED, RunStatus.PREPARING, RunStatus.CLAIMED,
    RunStatus.RUNNING, RunStatus.VERIFYING, RunStatus.READY_TO_INTEGRATE,
    RunStatus.INTEGRATING, RunStatus.AWAITING_REVIEW, RunStatus.NEEDS_DECISION,
}


@dataclass(frozen=True)
class ScopeMigrationPreview:
    old_path: str
    new_path: str
    source_sha256: str
    target_sha256: str
    target_yaml: str


def _hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _fsync_dir(path: Path) -> None:
    # POSIX directory durability; on platforms without directory handles,
    # the atomic file fsync still applies but power-loss durability is weaker.
    if os.name != "posix":
        return
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _atomic_write(path: Path, payload: bytes) -> None:
    missing = []
    folder = path.parent
    while not folder.exists():
        missing.append(folder)
        folder = folder.parent
    path.parent.mkdir(parents=True, exist_ok=True)
    for created in reversed(missing):
        # The parent entry of every newly-created journal directory must be
        # durable before a policy file may be mutated.
        _fsync_dir(created.parent)
    fd, name = tempfile.mkstemp(prefix=".projectctl-scope-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
        _fsync_dir(path.parent)
    finally:
        Path(name).unlink(missing_ok=True)


def _json_bytes(value: dict) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=2) + "\n").encode("utf-8")


def _read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise ConfigurationError(f"Invalid scope migration journal {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigurationError(f"Scope migration journal is not a mapping: {path}")
    return data


def _assert_safe_to_mutate(root: Path) -> None:
    db = root / ".projectctl" / "state.sqlite"
    if db.exists():
        active = [
            row for row in RunStore(root).list(limit=100000)
            if row.status in _BLOCKING_RUN_STATUSES
        ]
        if active:
            raise ConfigurationError(
                "Scope migration blocked by active/unresolved run(s): "
                + ", ".join(f"{r.run_id}:{r.status.value}" for r in active[:12])
            )
    adopted = root / ".projectctl" / "context" / "adoptions"
    if adopted.exists():
        for request in adopted.glob("**/request.json"):
            if not (request.parent / "receipt.json").is_file():
                raise ConfigurationError(
                    f"Pending scope adoption must be resolved before migration: {request}"
                )


def _assert_clean_repo(root: Path) -> None:
    result = subprocess.run(
        ["git", "-C", str(root), "status", "--porcelain", "--untracked-files=all"],
        text=True, capture_output=True, check=False,
    )
    if result.returncode != 0:
        raise ConfigurationError(
            "Git status failed before migration: " + (result.stderr or result.stdout)
        )
    if result.stdout.strip():
        raise ConfigurationError(
            "Commit or stash repository changes before scope migration."
        )


def _journal_root(root: Path) -> Path:
    return root / ".projectctl" / "scope-migrations"


def _pending_journals(root: Path) -> list[tuple[Path, dict]]:
    folder = _journal_root(root)
    if folder.is_symlink():
        raise ConfigurationError("Symlinked scope migration journal is unsafe.")
    if not folder.exists():
        return []
    pending = []
    for child in sorted(folder.iterdir()):
        if child.is_symlink() or not child.is_dir():
            raise ConfigurationError("Unexpected non-directory/symlink in scope migration journal.")
        request = child / "request.json"
        receipt = child / "receipt.json"
        if request.is_symlink() or receipt.is_symlink() or not request.is_file():
            raise ConfigurationError(f"Incomplete or unsafe scope migration journal: {child}")
        data = _read_json(request)
        _validate_request(data)
        if child.name != data["migration_id"]:
            raise ConfigurationError("Scope migration journal directory identity mismatch.")
        if receipt.exists():
            value = _read_json(receipt)
            expected = {
                "schema_kind": "projectctl.scope_migration_receipt",
                "schema_version": 1,
                "migration_id": data["migration_id"],
                "source_sha256": data["source_sha256"],
                "target_sha256": data["target_sha256"],
                "canonical_path": EXECUTION_SCOPE_PATH,
                "applied": True,
            }
            if value != expected:
                raise ConfigurationError("Completed scope migration receipt is invalid.")
        else:
            pending.append((child, data))
    return pending


def assert_no_pending_scope_migration(root: Path) -> None:
    if _pending_journals(root.resolve()):
        raise ConfigurationError(
            "A scope migration is pending; complete explicit --recover before "
            "reviewing or mutating canonical scope authority."
        )


def _validate_request(request: dict) -> bytes:
    required = {
        "schema_kind", "schema_version", "migration_id", "old_path",
        "new_path", "source_sha256", "target_sha256", "target_yaml",
    }
    if set(request) != required:
        raise ConfigurationError("Migration journal has unexpected/missing request fields.")
    if (
        request["schema_kind"] != "projectctl.scope_migration_request"
        or request["schema_version"] != 1
        or request["old_path"] != LEGACY_PARALLEL_SCOPE_PATH
        or request["new_path"] != EXECUTION_SCOPE_PATH
        or not isinstance(request["migration_id"], str)
        or not request["migration_id"].startswith("scope-migration-")
        or not isinstance(request["target_yaml"], str)
    ):
        raise ConfigurationError("Migration journal identity is invalid.")
    raw = request["target_yaml"].encode("utf-8")
    if _hash(raw) != request["target_sha256"]:
        raise ConfigurationError("Migration journal target bytes changed; manual audit required.")
    if not (
        isinstance(request["source_sha256"], str)
        and len(request["source_sha256"]) == 64
    ):
        raise ConfigurationError("Migration journal source digest is invalid.")
    # Journal target must itself be a valid canonical scope authority.
    from projectctl.execution_scope.catalog import parse_execution_scope_catalog_bytes
    parse_execution_scope_catalog_bytes(raw)
    return raw


def _safe_policy_path(root: Path, name: str) -> Path:
    declared = root / name
    if declared.is_symlink() or (declared.exists() and not declared.is_file()):
        raise ConfigurationError(f"Unsafe scope migration policy path: {name}")
    return declared


def preview_scope_migration(project_root: Path) -> ScopeMigrationPreview:
    """Read-only preview. No implicit conversion or mutation is authorized."""
    root = project_root.resolve()
    if _pending_journals(root):
        raise ConfigurationError(
            "Pending scope migration must be recovered before a new preview."
        )
    source = resolve_execution_scope_catalog(root)
    if source.source != "legacy" or source.catalog is None or source.raw_bytes is None:
        raise ConfigurationError(
            "Migration requires one valid legacy-only projectctl.parallel.yaml authority."
        )
    target_yaml = (
        yaml.safe_dump(
            source.catalog.model_dump(mode="json"),
            sort_keys=False,
            allow_unicode=True,
        ).rstrip() + "\n"
    )
    return ScopeMigrationPreview(
        old_path=LEGACY_PARALLEL_SCOPE_PATH,
        new_path=EXECUTION_SCOPE_PATH,
        source_sha256=_hash(source.raw_bytes),
        target_sha256=_hash(target_yaml.encode("utf-8")),
        target_yaml=target_yaml,
    )


def _resume_request(root: Path, child: Path, request: dict) -> dict:
    new_bytes = _validate_request(request)
    if child.name != request["migration_id"]:
        raise ConfigurationError("Scope migration journal directory identity mismatch.")
    old = _safe_policy_path(root, LEGACY_PARALLEL_SCOPE_PATH)
    new = _safe_policy_path(root, EXECUTION_SCOPE_PATH)

    # Only three exact states are recognized: before / dual / after.
    if old.exists() and _hash(old.read_bytes()) != request["source_sha256"]:
        raise ConfigurationError("Legacy migration source was edited; manual audit required.")
    if new.exists() and new.read_bytes() != new_bytes:
        raise ConfigurationError("Canonical migration target was edited; manual audit required.")
    if not old.exists() and not new.exists():
        raise ConfigurationError("Both scope authorities are missing; manual audit required.")

    if not new.exists():
        if not old.exists():
            raise ConfigurationError("Cannot reconstruct migration source.")
        _atomic_write(new, new_bytes)
    # Both-policy state is intentionally unexecutable until legacy is retired.
    if old.exists():
        if _hash(old.read_bytes()) != request["source_sha256"]:
            raise ConfigurationError("Legacy source changed during migration; manual audit.")
        old.unlink()
        _fsync_dir(root)

    effective = resolve_execution_scope_catalog(root, allow_pending_migration=True)
    if (
        effective.source != "canonical"
        or effective.raw_bytes != new_bytes
        or old.exists()
    ):
        raise ConfigurationError("Scope migration postcondition is not proven.")

    receipt = {
        "schema_kind": "projectctl.scope_migration_receipt",
        "schema_version": 1,
        "migration_id": request["migration_id"],
        "source_sha256": request["source_sha256"],
        "target_sha256": request["target_sha256"],
        "canonical_path": EXECUTION_SCOPE_PATH,
        "applied": True,
    }
    _atomic_write(child / "receipt.json", _json_bytes(receipt))
    return receipt


@execution_authority_gated
def apply_scope_migration(project_root: Path, *, recover: bool = False) -> dict:
    """Perform an explicit migration, or resume exactly one recorded request."""
    root = project_root.resolve()
    with project_lock(root, "scope-migration"):
        _assert_safe_to_mutate(root)
        pending = _pending_journals(root)
        if len(pending) > 1:
            raise ConfigurationError("Competing pending migrations require manual audit.")
        if recover:
            if not pending:
                raise ConfigurationError("No pending scope migration requires recovery.")
            child, request = pending[0]
            return _resume_request(root, child, request)
        if pending:
            raise ConfigurationError(
                "Pending scope migration exists; run projectctl scope migrate --recover."
            )

        _assert_clean_repo(root)
        preview = preview_scope_migration(root)
        migration_id = "scope-migration-" + uuid.uuid4().hex
        child = _journal_root(root) / migration_id
        request = {
            "schema_kind": "projectctl.scope_migration_request",
            "schema_version": 1,
            "migration_id": migration_id,
            "old_path": preview.old_path,
            "new_path": preview.new_path,
            "source_sha256": preview.source_sha256,
            "target_sha256": preview.target_sha256,
            "target_yaml": preview.target_yaml,
        }
        # Validate the exact intended transition before the durable write.
        _validate_request(request)
        _atomic_write(child / "request.json", _json_bytes(request))
        return _resume_request(root, child, request)
