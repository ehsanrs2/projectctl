from __future__ import annotations

from pathlib import Path

from projectctl.core.errors import TaskStoreError
from projectctl.integrations.task_authority import resolve_task_authority
from projectctl.schemas.task import TaskSnapshot


def task_store_for_project(project_root: Path):
    return resolve_task_authority(project_root).reader


def capture_task_snapshot(project_root: Path, state: str = "all") -> TaskSnapshot:
    store = task_store_for_project(project_root)
    if state == "all":
        tasks = store.list_all()
    elif state == "ready":
        tasks = store.list_ready()
    elif state == "blocked":
        tasks = store.list_blocked()
    else:
        raise TaskStoreError(f"Unsupported task state filter: {state}")
    return store.snapshot(tasks=tasks)
