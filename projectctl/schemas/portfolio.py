from __future__ import annotations

from typing import Literal

from pydantic import AwareDatetime, Field

from projectctl.core.enums import QuotaMode, ResourceClass, RunStatus
from projectctl.schemas.base import ProjectCtlModel


PortfolioAction = Literal["resume_run", "start_run", "new_task"]


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
    exclusion_reasons: list[str] = Field(default_factory=list)
    details: list[str] = Field(default_factory=list)


class PortfolioDecision(ProjectCtlModel):
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
    selected_action: PortfolioAction | None = None
    selected_run_id: str | None = None
    selected_task_id: str | None = None
    candidates: list[PortfolioCandidate] = Field(default_factory=list)


class PortfolioTurnResult(ProjectCtlModel):
    schema_kind: Literal["projectctl.portfolio_turn_result"] = (
        "projectctl.portfolio_turn_result"
    )
    schema_version: Literal[1] = 1
    decision: PortfolioDecision
    project_instance_id: str
    project_id: str
    project_root: str
    action: PortfolioAction
    run_id: str
    run_status: RunStatus
