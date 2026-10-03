from typing import Literal

from pydantic import AwareDatetime

from projectctl.core.enums import ModelProfile, QuotaMode, ReasoningLevel
from projectctl.schemas.base import ProjectCtlModel
from projectctl.schemas.project_state import MilestoneState


class TaskCounts(ProjectCtlModel):
    total: int = 0
    ready: int = 0
    blocked: int = 0
    running: int = 0
    done: int = 0
    failed: int = 0
    needs_decision: int = 0


class StatusSourceDigests(ProjectCtlModel):
    project_state: str
    tasks: str
    quota: str


class ProjectStatus(ProjectCtlModel):
    schema_kind: Literal["projectctl.project_status"] = "projectctl.project_status"
    schema_version: Literal[1] = 1
    generated_at: AwareDatetime
    project_id: str
    current_goal: str | None = None
    active_milestone: MilestoneState | None = None
    task_counts: TaskCounts
    quota_mode: QuotaMode
    quota_stale: bool
    next_task_id: str | None = None
    next_model_profile: ModelProfile | None = None
    next_reasoning: ReasoningLevel | None = None
    source_digests: StatusSourceDigests
