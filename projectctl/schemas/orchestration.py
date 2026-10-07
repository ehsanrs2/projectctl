from __future__ import annotations

from typing import Literal

from pydantic import AwareDatetime, Field

from projectctl.core.enums import QuotaMode, ResourceClass, RunStatus
from projectctl.schemas.base import ProjectCtlModel


WorkerTurnAction = Literal["resume_run", "start_run", "admit_task"]


class ProjectTurnEnvelope(ProjectCtlModel):
    schema_kind: Literal["projectctl.project_turn_envelope"] = (
        "projectctl.project_turn_envelope"
    )
    schema_version: Literal[1] = 1
    envelope_id: str = Field(min_length=1)
    observed_at: AwareDatetime
    project_instance_id: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    project_root: str = Field(min_length=1)
    account_id: str = Field(min_length=1)
    eligible: bool = False
    action: WorkerTurnAction | None = None
    run_id: str | None = None
    run_status: RunStatus | None = None
    task_id: str | None = None
    resource_class: ResourceClass | None = None
    project_state_digest: str | None = None
    task_snapshot_digest: str | None = None
    quota_snapshot_digest: str | None = None
    quota_mode: QuotaMode | None = None
    quota_stale: bool | None = None
    active_run_ids: list[str] = Field(default_factory=list)
    active_run_count: int = Field(default=0, ge=0)
    max_active_runs: int = Field(default=1, ge=1, le=8)
    parallel_admission: bool = False
    non_worker_run_ids: list[str] = Field(default_factory=list)
    integration_queue_head_run_id: str | None = None
    exclusion_reasons: list[str] = Field(default_factory=list)
    details: list[str] = Field(default_factory=list)


class ProjectTurnResult(ProjectCtlModel):
    schema_kind: Literal["projectctl.project_turn_result"] = (
        "projectctl.project_turn_result"
    )
    schema_version: Literal[1] = 1
    envelope: ProjectTurnEnvelope
    run_id: str
    run_status: RunStatus
    prepared_new_run: bool = False


class OrchestrationStatus(ProjectCtlModel):
    schema_kind: Literal["projectctl.orchestration_status"] = (
        "projectctl.orchestration_status"
    )
    schema_version: Literal[1] = 1
    generated_at: AwareDatetime
    project_instance_id: str
    project_id: str
    project_root: str
    account_id: str
    active_run_ids: list[str] = Field(default_factory=list)
    active_run_count: int = Field(ge=0)
    max_active_runs: int = Field(ge=1, le=8)
    non_worker_run_ids: list[str] = Field(default_factory=list)
    integration_queue_head_run_id: str | None = None
    next_worker_turn: ProjectTurnEnvelope | None = None
    account_admission_run_id: str | None = None
    account_admission_project_instance_id: str | None = None
    account_busy: bool = False
