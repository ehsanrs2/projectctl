from typing import Literal

from pydantic import AwareDatetime, Field

from projectctl.core.enums import (
    ExclusionReason,
    ModelProfile,
    QuotaMode,
    ReasoningLevel,
    RecommendationReason,
)
from projectctl.schemas.base import ProjectCtlModel


class EligibilityResult(ProjectCtlModel):
    task_id: str
    eligible: bool
    reasons: list[ExclusionReason] = Field(default_factory=list)


class ScoreBreakdown(ProjectCtlModel):
    priority: float = 0.0
    milestone_relevance: float = 0.0
    unblock_value: float = 0.0
    information_gain: float = 0.0
    urgency: float = 0.0
    age_bonus: float = 0.0
    risk_penalty: float = 0.0
    resource_penalty: float = 0.0
    quota_penalty: float = 0.0
    total: float


class ModelRecommendation(ProjectCtlModel):
    profile: ModelProfile
    reasoning: ReasoningLevel
    reasons: list[RecommendationReason] = Field(default_factory=list)
    quota_mode: QuotaMode


class SchedulerCandidate(ProjectCtlModel):
    task_id: str
    eligibility: EligibilityResult
    score: ScoreBreakdown | None = None
    model: ModelRecommendation | None = None


class SchedulerDecision(ProjectCtlModel):
    schema_kind: Literal["projectctl.scheduler_decision"] = "projectctl.scheduler_decision"
    schema_version: Literal[2] = 2
    evaluated_at: AwareDatetime
    project_id: str
    policy: str
    policy_version: int
    config_digest: str
    project_state_digest: str
    task_snapshot_digest: str
    quota_snapshot_digest: str
    active_milestone_id: str | None = None
    selected_task_id: str | None = None
    quota_mode: QuotaMode
    candidates: list[SchedulerCandidate] = Field(default_factory=list)
