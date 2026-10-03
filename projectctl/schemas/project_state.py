from typing import Literal

from pydantic import AwareDatetime, Field

from projectctl.schemas.base import ProjectCtlModel


class MilestoneState(ProjectCtlModel):
    id: str = Field(min_length=1)
    title: str | None = None
    aliases: list[str] = Field(default_factory=list)


class ProjectState(ProjectCtlModel):
    schema_kind: Literal["projectctl.project_state"] = "projectctl.project_state"
    schema_version: Literal[1] = 1
    project_id: str = Field(min_length=1)
    current_goal: str | None = None
    active_milestone: MilestoneState | None = None
    updated_at: AwareDatetime | None = None
