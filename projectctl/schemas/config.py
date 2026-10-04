from typing import Annotated, Literal

from pydantic import AfterValidator, Field

from projectctl.core.enums import ModelProfile, QuotaMode, ReasoningLevel
from projectctl.core.paths import validate_repo_path
from projectctl.schemas.base import ProjectCtlModel, Ratio

RepoRelativePath = Annotated[str, AfterValidator(validate_repo_path)]


class ProjectIdentity(ProjectCtlModel):
    id: str = Field(min_length=1, pattern=r"^[a-z0-9][a-z0-9._-]*$")
    name: str | None = None
    profile: str = "generic"


class TaskStoreConfigV1(ProjectCtlModel):
    provider: str = "beads"


class TaskStoreConfig(ProjectCtlModel):
    provider: str = "beads"
    repository: str | None = None


class ProjectPaths(ProjectCtlModel):
    project: RepoRelativePath = "docs/PROJECT.md"
    roadmap: RepoRelativePath = "docs/ROADMAP.md"
    constraints: RepoRelativePath = "docs/CONSTRAINTS.md"
    specs: RepoRelativePath = "specs"
    evidence: RepoRelativePath = "evidence"
    generated: RepoRelativePath = "docs/generated"


class KnowledgeRoleBinding(ProjectCtlModel):
    sources: list[RepoRelativePath] = Field(default_factory=list)


class KnowledgeConfig(ProjectCtlModel):
    project_overview: KnowledgeRoleBinding = Field(
        default_factory=lambda: KnowledgeRoleBinding(sources=["docs/PROJECT.md"])
    )
    roadmap: KnowledgeRoleBinding = Field(
        default_factory=lambda: KnowledgeRoleBinding(sources=["docs/ROADMAP.md"])
    )
    constraints: KnowledgeRoleBinding = Field(
        default_factory=lambda: KnowledgeRoleBinding(sources=["docs/CONSTRAINTS.md"])
    )
    architecture: KnowledgeRoleBinding = Field(default_factory=KnowledgeRoleBinding)
    decisions: KnowledgeRoleBinding = Field(default_factory=KnowledgeRoleBinding)


class FeatureFlags(ProjectCtlModel):
    spec_kit: bool = True
    graphify: bool = False


class ModelProfileConfig(ProjectCtlModel):
    provider: str = "codex"
    model: str | None = None
    reasoning: ReasoningLevel
    enabled: bool = True


class QuotaReserve(ProjectCtlModel):
    five_hour: Ratio = 0.10
    weekly: Ratio = 0.10


class QuotaThresholds(ProjectCtlModel):
    conservation_five_hour_below: Ratio = 0.35
    conservation_weekly_below: Ratio = 0.30
    critical_weekly_below: Ratio = 0.12


class ResourceBudgetRequirement(ProjectCtlModel):
    min_five_hour: Ratio
    min_weekly: Ratio


class ResourceBudgetPolicy(ProjectCtlModel):
    trivial: ResourceBudgetRequirement = Field(
        default_factory=lambda: ResourceBudgetRequirement(min_five_hour=0.03, min_weekly=0.01)
    )
    small: ResourceBudgetRequirement = Field(
        default_factory=lambda: ResourceBudgetRequirement(min_five_hour=0.08, min_weekly=0.03)
    )
    medium: ResourceBudgetRequirement = Field(
        default_factory=lambda: ResourceBudgetRequirement(min_five_hour=0.18, min_weekly=0.08)
    )
    large: ResourceBudgetRequirement = Field(
        default_factory=lambda: ResourceBudgetRequirement(min_five_hour=0.30, min_weekly=0.15)
    )
    deep: ResourceBudgetRequirement = Field(
        default_factory=lambda: ResourceBudgetRequirement(min_five_hour=0.45, min_weekly=0.25)
    )


class QuotaPolicy(ProjectCtlModel):
    account: str = "openai-default"
    reserve: QuotaReserve = Field(default_factory=QuotaReserve)
    thresholds: QuotaThresholds = Field(default_factory=QuotaThresholds)
    resource_requirements: ResourceBudgetPolicy = Field(default_factory=ResourceBudgetPolicy)
    unknown_quota_mode: QuotaMode = QuotaMode.CONSERVATION
    max_snapshot_age_seconds: int = Field(default=900, ge=1)
    execution_monitor_interval_seconds: float = Field(default=60.0, gt=0, le=600)


class SchedulerWeights(ProjectCtlModel):
    priority: float = 1.0
    milestone_relevance: float = 1.0
    unblock_value: float = 1.0
    information_gain: float = 1.0
    urgency: float = 1.0
    age_bonus: float = 1.0
    risk_penalty: float = 1.0
    resource_penalty: float = 1.0
    quota_penalty: float = 1.0


class SchedulerConfig(ProjectCtlModel):
    policy: str = "weighted_v1"
    policy_version: int = Field(default=1, ge=1)
    score_precision: int = Field(default=6, ge=0, le=12)
    weights: SchedulerWeights = Field(default_factory=SchedulerWeights)


def default_model_profiles() -> dict[ModelProfile, ModelProfileConfig]:
    return {
        ModelProfile.ECONOMICAL: ModelProfileConfig(reasoning=ReasoningLevel.LOW),
        ModelProfile.BALANCED: ModelProfileConfig(reasoning=ReasoningLevel.MEDIUM),
        ModelProfile.STRONG: ModelProfileConfig(reasoning=ReasoningLevel.MEDIUM),
        ModelProfile.DEEP: ModelProfileConfig(reasoning=ReasoningLevel.HIGH),
    }


class ProjectConfigV1(ProjectCtlModel):
    schema_kind: Literal["projectctl.project_config"] = "projectctl.project_config"
    schema_version: Literal[1] = 1
    project: ProjectIdentity
    task_store: TaskStoreConfigV1 = Field(default_factory=TaskStoreConfigV1)
    paths: ProjectPaths = Field(default_factory=ProjectPaths)
    knowledge: KnowledgeConfig = Field(default_factory=KnowledgeConfig)
    scheduler: SchedulerConfig = Field(default_factory=SchedulerConfig)
    quota: QuotaPolicy = Field(default_factory=QuotaPolicy)
    features: FeatureFlags = Field(default_factory=FeatureFlags)
    model_profiles: dict[ModelProfile, ModelProfileConfig] = Field(default_factory=default_model_profiles)


class ProjectConfig(ProjectCtlModel):
    schema_kind: Literal["projectctl.project_config"] = "projectctl.project_config"
    schema_version: Literal[2] = 2
    project: ProjectIdentity
    task_store: TaskStoreConfig = Field(default_factory=TaskStoreConfig)
    paths: ProjectPaths = Field(default_factory=ProjectPaths)
    knowledge: KnowledgeConfig = Field(default_factory=KnowledgeConfig)
    scheduler: SchedulerConfig = Field(default_factory=SchedulerConfig)
    quota: QuotaPolicy = Field(default_factory=QuotaPolicy)
    features: FeatureFlags = Field(default_factory=FeatureFlags)
    model_profiles: dict[ModelProfile, ModelProfileConfig] = Field(default_factory=default_model_profiles)
