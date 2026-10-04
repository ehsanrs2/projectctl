from __future__ import annotations

from pathlib import Path

from projectctl.core.errors import ConfigurationError, TaskStoreError
from projectctl.integrations.beads import BeadsTaskStore
from projectctl.integrations.github import GitHubIssuesTaskStore
from projectctl.project.loader import load_project_config
from projectctl.schemas.task import TaskSnapshot


def task_store_for_project(project_root: Path):
    config = load_project_config(project_root)
    provider = config.task_store.provider
    if provider == "beads":
        return BeadsTaskStore(project_root)
    if provider == "github":
        return GitHubIssuesTaskStore(
            project_root,
            repository=config.task_store.repository,
        )
    raise ConfigurationError(f"Task store provider `{provider}` is not implemented.")


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
