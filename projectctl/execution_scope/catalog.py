from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml
from pydantic import ValidationError

from projectctl.core.errors import ConfigurationError
from projectctl.core.paths import resolve_inside_repo
from projectctl.schemas.execution_scope import ExecutionScopeCatalog, ExecutionTaskScope
from projectctl.schemas.parallel import ParallelScopeCatalog

EXECUTION_SCOPE_PATH = "projectctl.scope.yaml"
LEGACY_PARALLEL_SCOPE_PATH = "projectctl.parallel.yaml"


@dataclass(frozen=True)
class ResolvedExecutionScopeCatalog:
    source: Literal["canonical", "legacy", "absent"]
    catalog: ExecutionScopeCatalog | None
    path: Path | None
    raw_bytes: bytes | None
    raw_digest: str | None


def _parse_catalog_bytes(raw_bytes: bytes, model, label: str):
    """Validate one immutable byte snapshot against one exact catalog schema."""
    try:
        raw = yaml.safe_load(raw_bytes.decode("utf-8"))
        if not isinstance(raw, dict):
            raise ConfigurationError(f"{label} catalog must be a YAML mapping.")
        return model.model_validate(raw)
    except (UnicodeDecodeError, yaml.YAMLError, ValidationError) as exc:
        raise ConfigurationError(f"Invalid {label} catalog: {exc}") from exc


def parse_execution_scope_catalog_bytes(raw_bytes: bytes) -> ExecutionScopeCatalog:
    return _parse_catalog_bytes(raw_bytes, ExecutionScopeCatalog, "execution scope")


def _policy_file(root: Path, relative: str) -> tuple[Path, bool]:
    declared = root / relative
    if declared.is_symlink():
        raise ConfigurationError(
            f"Refusing symlinked human-managed scope authority: {relative}."
        )
    path = resolve_inside_repo(root, relative, must_exist=False)
    present = path.exists()
    if present and not path.is_file():
        raise ConfigurationError(f"Scope authority is not a regular file: {relative}.")
    return path, present


def resolve_execution_scope_catalog(
    project_root: Path, *, allow_pending_migration: bool = False,
) -> ResolvedExecutionScopeCatalog:
    """Resolve exactly one authority; pending migrations are not executable."""
    root = project_root.resolve()
    if not allow_pending_migration:
        # The presence of receipt.json is not completion evidence by itself:
        # its content must match the recorded migration identity and digests.
        # Import lazily to keep the reader independent of mutation at import time.
        from projectctl.execution_scope.migration import (
            assert_no_pending_scope_migration,
        )

        assert_no_pending_scope_migration(root)
    canonical_path, canonical_present = _policy_file(root, EXECUTION_SCOPE_PATH)
    legacy_path, legacy_present = _policy_file(root, LEGACY_PARALLEL_SCOPE_PATH)

    if canonical_present and legacy_present:
        raise ConfigurationError(
            "Both projectctl.scope.yaml and projectctl.parallel.yaml exist; "
            "resolve the conflicting human-managed scope authorities explicitly."
        )
    if not canonical_present and not legacy_present:
        return ResolvedExecutionScopeCatalog("absent", None, None, None, None)

    path = canonical_path if canonical_present else legacy_path
    try:
        raw_bytes = path.read_bytes()
    except OSError as exc:
        raise ConfigurationError(f"Cannot read execution scope authority {path}: {exc}") from exc

    if canonical_present:
        catalog = parse_execution_scope_catalog_bytes(raw_bytes)
        source: Literal["canonical", "legacy", "absent"] = "canonical"
    else:
        legacy = _parse_catalog_bytes(raw_bytes, ParallelScopeCatalog, "legacy parallel scope")
        catalog = ExecutionScopeCatalog(
            tasks={
                key: ExecutionTaskScope.model_validate(scope.model_dump(mode="python"))
                for key, scope in legacy.tasks.items()
            }
        )
        source = "legacy"

    return ResolvedExecutionScopeCatalog(
        source=source,
        catalog=catalog,
        path=path,
        raw_bytes=raw_bytes,
        raw_digest=hashlib.sha256(raw_bytes).hexdigest(),
    )


def load_execution_scope_catalog(project_root: Path) -> ExecutionScopeCatalog | None:
    return resolve_execution_scope_catalog(project_root).catalog


def task_execution_scope(project_root: Path, task_id: str) -> ExecutionTaskScope:
    resolved = resolve_execution_scope_catalog(project_root)
    if resolved.catalog is None:
        raise ConfigurationError(
            f"Missing human-managed execution scope catalog for task {task_id!r}."
        )
    scope = resolved.catalog.tasks.get(task_id)
    if scope is None:
        raise ConfigurationError(
            f"Task {task_id!r} has no declared scope in "
            f"{resolved.path.name}; execution scope is not proven."
        )
    return scope
