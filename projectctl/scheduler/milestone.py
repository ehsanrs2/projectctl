from __future__ import annotations

import re

from projectctl.schemas.project_state import ProjectState
from projectctl.schemas.task import NormalizedTask


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().casefold())


def milestone_relevance(task: NormalizedTask, state: ProjectState | None) -> float:
    if state is None or state.active_milestone is None or not task.milestone:
        return 0.0
    milestone = state.active_milestone
    accepted = {_normalize(milestone.id)}
    if milestone.title:
        accepted.add(_normalize(milestone.title))
    accepted.update(_normalize(alias) for alias in milestone.aliases if alias.strip())
    return 8.0 if _normalize(task.milestone) in accepted else 0.0
