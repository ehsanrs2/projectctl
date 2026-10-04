from __future__ import annotations

from pathlib import Path

from projectctl.project.adoption import apply_adoption, plan_adoption
from projectctl.project.bootstrap import initialize_project
from projectctl.project.inspection import inspect_repository


def inspect_project(path: Path):
    return inspect_repository(path)


def build_adoption_plan(
    path: Path,
    *,
    task_store_provider: str | None = None,
    task_store_repository: str | None = None,
):
    inspection = inspect_repository(path)
    return plan_adoption(
        inspection,
        task_store_provider=task_store_provider,
        task_store_repository=task_store_repository,
    )


def adopt_project(
    path: Path,
    *,
    task_store_provider: str | None = None,
    task_store_repository: str | None = None,
    allow_dirty: bool = False,
):
    plan = build_adoption_plan(
        path,
        task_store_provider=task_store_provider,
        task_store_repository=task_store_repository,
    )
    return apply_adoption(plan, allow_dirty=allow_dirty)


def initialize_greenfield(path: Path):
    return initialize_project(path)
