from __future__ import annotations

from pathlib import Path

from projectctl.core.errors import TaskStoreError
from projectctl.integrations.task_authority import resolve_task_authority
from projectctl.schemas.task import TaskSnapshot


def task_store_for_project(
    project_root: Path,
    *,
    read_cache_max_age_seconds: float | None = None,
):
    return resolve_task_authority(
        project_root,
        read_cache_max_age_seconds=read_cache_max_age_seconds,
    ).reader


def capture_task_snapshot(
    project_root: Path,
    state: str = "all",
    *,
    read_cache_max_age_seconds: float | None = None,
) -> TaskSnapshot:
    store = task_store_for_project(
        project_root,
        read_cache_max_age_seconds=read_cache_max_age_seconds,
    )
    if state == "all":
        tasks = store.list_all()
    elif state == "ready":
        tasks = store.list_ready()
    elif state == "blocked":
        tasks = store.list_blocked()
    else:
        raise TaskStoreError(f"Unsupported task state filter: {state}")
    return store.snapshot(tasks=tasks)
