from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import ValidationError

from projectctl.core.errors import ConfigurationError
from projectctl.core.paths import resolve_inside_repo
from projectctl.schemas.parallel import ParallelScopeCatalog, ParallelTaskScope

PARALLEL_SCOPE_PATH = "projectctl.parallel.yaml"


def load_parallel_scope_catalog(project_root: Path) -> ParallelScopeCatalog:
    root = project_root.resolve()
    path = resolve_inside_repo(root, PARALLEL_SCOPE_PATH, must_exist=False)
    if not path.exists():
        raise ConfigurationError(
            f"Missing human-managed parallel scope catalog: {PARALLEL_SCOPE_PATH}. "
            "Parallel planning fails closed until task input/write/resource scopes are declared."
        )
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ConfigurationError("Parallel scope catalog must be a YAML mapping.")
        return ParallelScopeCatalog.model_validate(raw)
    except (yaml.YAMLError, ValidationError) as exc:
        raise ConfigurationError(f"Invalid parallel scope catalog: {exc}") from exc


def task_parallel_scope(
    project_root: Path,
    task_id: str,
) -> ParallelTaskScope:
    catalog = load_parallel_scope_catalog(project_root)
    scope = catalog.tasks.get(task_id)
    if scope is None:
        raise ConfigurationError(
            f"Task {task_id!r} has no explicit parallel scope in {PARALLEL_SCOPE_PATH}; "
            "parallel planning is not proven safe."
        )
    return scope
