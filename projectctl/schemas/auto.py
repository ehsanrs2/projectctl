from __future__ import annotations

from typing import Literal

from pydantic import AwareDatetime, Field

from projectctl.core.enums import AutoStopReason, QuotaMode, RunStatus, WorkerStrategyKind
from projectctl.schemas.base import ProjectCtlModel


class AutoRunPolicy(ProjectCtlModel):
    schema_kind: Literal["projectctl.auto_run_policy"] = "projectctl.auto_run_policy"
    schema_version: Literal[1] = 1
    max_tasks: int = Field(default=1, ge=1, le=100)
    max_attempts_per_task: int = Field(default=1, ge=1, le=10)
    stop_on_critical_quota: bool = True
    stop_on_stale_quota: bool = True
    stop_on_material_project_state_change: bool = True
    requested_strategy: WorkerStrategyKind | None = None
    allow_goal_fallback: bool = False
    allow_plan_fallback: bool = False


class AutoRunStep(ProjectCtlModel):
    iteration: int = Field(ge=1)
    task_id: str | None = None
    run_id: str | None = None
    started_status: RunStatus | None = None
    final_status: RunStatus | None = None
    action: str = Field(min_length=1)
    project_state_digest_before: str | None = None
    project_state_digest_after: str | None = None
    quota_mode: QuotaMode | None = None
    quota_stale: bool | None = None
    details: list[str] = Field(default_factory=list)


class AutoRunReport(ProjectCtlModel):
    schema_kind: Literal["projectctl.auto_run_report"] = "projectctl.auto_run_report"
    schema_version: Literal[1] = 1
    auto_run_id: str = Field(min_length=1)
    started_at: AwareDatetime
    completed_at: AwareDatetime
    stop_reason: AutoStopReason
    completed_tasks: int = Field(ge=0)
    attempted_tasks: int = Field(ge=0)
    steps: list[AutoRunStep] = Field(default_factory=list)
