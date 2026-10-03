from __future__ import annotations

import os
import tempfile
from pathlib import Path

import yaml
from pydantic import ValidationError

from projectctl.core.digest import digest
from projectctl.core.errors import ConfigurationError
from projectctl.core.paths import resolve_inside_repo
from projectctl.core.time import utc_now
from projectctl.project.loader import load_project_config
from projectctl.project.locking import project_lock
from projectctl.schemas.project_state import MilestoneState, ProjectState

PROJECT_STATE_PATH = "docs/PROJECT_STATE.yaml"


def empty_project_state(project_id: str) -> ProjectState:
    return ProjectState(project_id=project_id)


def initial_project_state(project_id: str) -> ProjectState:
    return ProjectState(project_id=project_id, updated_at=utc_now())


def load_project_state(project_root: Path, *, allow_missing: bool = True) -> ProjectState:
    config = load_project_config(project_root)
    path = resolve_inside_repo(project_root, PROJECT_STATE_PATH, must_exist=False)
    if not path.exists():
        if allow_missing:
            return empty_project_state(config.project.id)
        raise ConfigurationError(
            f"Missing structured project state: {PROJECT_STATE_PATH}. "
            "Run projectctl state set or create the file."
        )
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ConfigurationError("Project state must be a YAML mapping.")
        state = ProjectState.model_validate(raw)
    except (yaml.YAMLError, ValidationError) as exc:
        raise ConfigurationError(f"Invalid project state: {exc}") from exc
    if state.project_id != config.project.id:
        raise ConfigurationError(
            f"Project state belongs to {state.project_id!r}, but config project id is {config.project.id!r}."
        )
    return state


def semantic_project_state_digest(state: ProjectState) -> str:
    payload = state.model_dump(mode="json", exclude={"updated_at"})
    return digest(payload)


def _write_project_state_unlocked(project_root: Path, state: ProjectState) -> Path:
    config = load_project_config(project_root)
    if state.project_id != config.project.id:
        raise ConfigurationError(
            f"Cannot write project state for {state.project_id!r} into project {config.project.id!r}."
        )
    state = state.model_copy(update={"updated_at": utc_now()})
    path = resolve_inside_repo(project_root, PROJECT_STATE_PATH, must_exist=False)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=".project-state-", suffix=".yaml", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            yaml.safe_dump(state.model_dump(mode="json"), handle, sort_keys=False, allow_unicode=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    finally:
        try:
            Path(tmp_name).unlink()
        except FileNotFoundError:
            pass
    return path


def write_project_state(project_root: Path, state: ProjectState) -> Path:
    with project_lock(project_root, "project-state"):
        return _write_project_state_unlocked(project_root, state)


def update_project_state(
    project_root: Path,
    *,
    goal: str | None = None,
    milestone_id: str | None = None,
    milestone_title: str | None = None,
    aliases: list[str] | None = None,
    clear_goal: bool = False,
    clear_milestone: bool = False,
) -> ProjectState:
    with project_lock(project_root, "project-state"):
        current = load_project_state(project_root, allow_missing=True)
        new_goal = current.current_goal
        new_milestone = current.active_milestone

        if clear_goal:
            new_goal = None
        elif goal is not None:
            new_goal = goal.strip() or None

        if clear_milestone:
            new_milestone = None
        elif milestone_id is not None:
            new_milestone = MilestoneState(
                id=milestone_id.strip(),
                title=(milestone_title.strip() if milestone_title else None),
                aliases=[a.strip() for a in (aliases or []) if a.strip()],
            )
        elif milestone_title is not None or aliases:
            if new_milestone is None:
                raise ConfigurationError("--milestone-title/--alias require an active --milestone or existing milestone.")
            new_milestone = new_milestone.model_copy(
                update={
                    "title": milestone_title.strip() if milestone_title is not None else new_milestone.title,
                    "aliases": [a.strip() for a in aliases] if aliases is not None else new_milestone.aliases,
                }
            )

        updated = current.model_copy(update={"current_goal": new_goal, "active_milestone": new_milestone})
        _write_project_state_unlocked(project_root, updated)
    return load_project_state(project_root, allow_missing=False)
