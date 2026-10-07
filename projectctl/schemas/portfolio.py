from __future__ import annotations

from typing import Literal

from pydantic import AwareDatetime, Field

from projectctl.core.enums import QuotaMode, ResourceClass, RunStatus
from projectctl.schemas.base import ProjectCtlModel
from projectctl.schemas.orchestration import (
    ProjectTurnEnvelope,
    ProjectTurnResult,
    WorkerTurnAction,
)


PortfolioActionV1 = Literal["resume_run", "start_run", "new_task"]
PortfolioAction = WorkerTurnAction


class PortfolioCandidateV1(ProjectCtlModel):
    project_instance_id: str
    project_id: str
    project_root: str
    registered_at: AwareDatetime
    last_seen_at: AwareDatetime
    observed_at: AwareDatetime
    account_id: str | None = None
    eligible: bool = False
    action: PortfolioActionV1V1 | None = None
    run_id: str | None = None
    run_status: RunStatus | None = None
    selected_task_id: str | None = None
    project_state_digest: str | None = None
    task_snapshot_digest: str | None = None
    quota_snapshot_digest: str | None = None
    quota_mode: QuotaMode | None = None
    quota_stale: bool | None = None
    resource_class: ResourceClass | None = None
    last_admitted_at: AwareDatetime | None = None
    exclusion_reasons: list[str] = Field(default_factory=list)
    details: list[str] = Field(default_factory=list)


class PortfolioDecisionV1(ProjectCtlModel):
    schema_kind: Literal["projectctl.portfolio_decision"] = (
        "projectctl.portfolio_decision"
    )
    schema_version: Literal[1] = 1
    decision_id: str
    evaluated_at: AwareDatetime
    account_id: str
    policy: Literal["continuation_then_fairness_v1"] = (
        "continuation_then_fairness_v1"
    )
    policy_version: Literal[1] = 1
    registry_digest: str
    account_busy: bool = False
    active_project_instance_id: str | None = None
    active_run_id: str | None = None
    selected_project_instance_id: str | None = None
    selected_project_id: str | None = None
    selected_project_root: str | None = None
    selected_action: PortfolioActionV1 | None = None
    selected_run_id: str | None = None
    selected_task_id: str | None = None
    candidates: list[PortfolioCandidateV1] = Field(default_factory=list)


class PortfolioTurnResultV1(ProjectCtlModel):
    schema_kind: Literal["projectctl.portfolio_turn_result"] = (
        "projectctl.portfolio_turn_result"
    )
    schema_version: Literal[1] = 1
    decision: PortfolioDecisionV1
    project_instance_id: str
    project_id: str
    project_root: str
    action: PortfolioAction
    run_id: str
    run_status: RunStatus



class PortfolioCandidate(ProjectCtlModel):
    project_instance_id: str
    project_id: str
    project_root: str
    registered_at: AwareDatetime
    last_seen_at: AwareDatetime
    observed_at: AwareDatetime
    account_id: str | None = None
    eligible: bool = False
    action: PortfolioAction | None = None
    run_id: str | None = None
    run_status: RunStatus | None = None
    selected_task_id: str | None = None
    project_state_digest: str | None = None
    task_snapshot_digest: str | None = None
    quota_snapshot_digest: str | None = None
    quota_mode: QuotaMode | None = None
    quota_stale: bool | None = None
    resource_class: ResourceClass | None = None
    last_admitted_at: AwareDatetime | None = None
    active_run_ids: list[str] = Field(default_factory=list)
    active_run_count: int = Field(default=0, ge=0)
    max_active_runs: int = Field(default=1, ge=1, le=8)
    parallel_admission: bool = False
    non_worker_run_ids: list[str] = Field(default_factory=list)
    integration_queue_head_run_id: str | None = None
    turn: ProjectTurnEnvelope | None = None
    exclusion_reasons: list[str] = Field(default_factory=list)
    details: list[str] = Field(default_factory=list)


class PortfolioDecision(ProjectCtlModel):
    schema_kind: Literal["projectctl.portfolio_decision"] = (
        "projectctl.portfolio_decision"
    )
    schema_version: Literal[2] = 2
    decision_id: str
    evaluated_at: AwareDatetime
    account_id: str
    policy: Literal["continuation_then_fairness_v2"] = (
        "continuation_then_fairness_v2"
    )
    policy_version: Literal[2] = 2
    registry_digest: str
    account_busy: bool = False
    active_project_instance_id: str | None = None
    active_run_id: str | None = None
    selected_project_instance_id: str | None = None
    selected_project_id: str | None = None
    selected_project_root: str | None = None
    selected_action: PortfolioAction | None = None
    selected_run_id: str | None = None
    selected_task_id: str | None = None
    candidates: list[PortfolioCandidate] = Field(default_factory=list)


class PortfolioTurnResult(ProjectCtlModel):
    schema_kind: Literal["projectctl.portfolio_turn_result"] = (
        "projectctl.portfolio_turn_result"
    )
    schema_version: Literal[2] = 2
    decision: PortfolioDecision
    project_instance_id: str
    project_id: str
    project_root: str
    action: PortfolioAction
    run_id: str
    run_status: RunStatus
    project_turn: ProjectTurnResult
