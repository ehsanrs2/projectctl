from typing import Annotated, Literal

from pydantic import AfterValidator, Field, model_validator

from projectctl.core.enums import ModelProfile, QuotaMode, ReasoningLevel
from projectctl.core.paths import validate_repo_path
from projectctl.schemas.base import ProjectCtlModel, Ratio

RepoRelativePath = Annotated[str, AfterValidator(validate_repo_path)]


def _validate_remote_identity(value: str) -> str:
    raw = str(value).strip().rstrip("/")
    if "://" in raw or "@" in raw:
        raise ValueError(
            "remote_identity must be credential-free host/path, not a Git URL."
        )
    if "/" not in raw:
        raise ValueError("remote_identity must use host/path.")
    host, path = raw.split("/", 1)
    host = host.strip().casefold()
    path = path.strip().lstrip("/")
    if path.endswith(".git"):
        path = path[:-4]
    path = "/".join(part for part in path.split("/") if part)
    if not host or not path or ".." in path.split("/"):
        raise ValueError("remote_identity is invalid.")
    return f"{host}/{path}"


CodeRemoteIdentity = Annotated[str, AfterValidator(_validate_remote_identity)]


class ProjectIdentity(ProjectCtlModel):
    id: str = Field(min_length=1, pattern=r"^[a-z0-9][a-z0-9._-]*$")
    name: str | None = None
    profile: str = "generic"


class TaskStoreConfigV1(ProjectCtlModel):
    provider: str = "beads"


class TaskStoreConfigV2(ProjectCtlModel):
    provider: str = "beads"
    repository: str | None = None


class TaskStoreConfigV3(ProjectCtlModel):
    provider: str = "beads"
    repository: str | None = None
    cache_max_age_seconds: int = Field(
        default=30,
        ge=0,
        le=3600,
        description=(
            "Maximum age for reusable derived task-provider GET cache entries. "
            "Zero disables local fresh hits and forces remote revalidation."
        ),
    )


class TaskStoreConfigV4(ProjectCtlModel):
    provider: str = "beads"
    repository: str | None = None
    team: str | None = None
    cache_max_age_seconds: int = Field(
        default=30,
        ge=0,
        le=3600,
        description=(
            "Maximum age for reusable derived task-provider GET cache entries. "
            "Zero disables local fresh hits and forces remote revalidation."
        ),
    )



def _validate_jira_site(value: str) -> str:
    raw = str(value).strip().rstrip("/").casefold()
    if "://" in raw or "/" in raw or "@" in raw:
        raise ValueError(
            "Jira site must be a credential-free host such as acme.atlassian.net."
        )
    if not raw.endswith(".atlassian.net"):
        raise ValueError(
            "Built-in Jira task authority supports Jira Cloud *.atlassian.net sites only."
        )
    return raw


JiraSite = Annotated[str, AfterValidator(_validate_jira_site)]


def _validate_jira_project(value: str) -> str:
    raw = str(value).strip().upper()
    if not raw or not raw[0].isalpha() or any(
        not (ch.isalnum() or ch in {"_", "-"}) for ch in raw
    ):
        raise ValueError("Jira project must be a project key such as ENG or PLATFORM.")
    return raw


JiraProjectKey = Annotated[str, AfterValidator(_validate_jira_project)]


class TaskStoreConfigV5(TaskStoreConfigV4):
    site: JiraSite | None = None
    project: JiraProjectKey | None = None


class JiraReadyStatus(ProjectCtlModel):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)


class JiraLinkRule(ProjectCtlModel):
    type_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    inward_label: str = Field(min_length=1)
    outward_label: str = Field(min_length=1)
    inward: Literal["dependency", "blocks", "ignore"]
    outward: Literal["dependency", "blocks", "ignore"]


class JiraWorkflowPolicy(ProjectCtlModel):
    ready_statuses: list[JiraReadyStatus] = Field(default_factory=list)
    link_rules: list[JiraLinkRule] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_unique_ids(self):
        status_ids = [value.id for value in self.ready_statuses]
        if len(status_ids) != len(set(status_ids)):
            raise ValueError("Jira ready status ids must be unique.")
        link_ids = [value.type_id for value in self.link_rules]
        if len(link_ids) != len(set(link_ids)):
            raise ValueError("Jira link rule type_ids must be unique.")
        return self


class TaskStoreConfig(TaskStoreConfigV5):
    jira_policy: JiraWorkflowPolicy = Field(default_factory=JiraWorkflowPolicy)


class CodeTransportConfig(ProjectCtlModel):
    mode: Literal["local", "git_remote"] = "local"
    remote_name: str | None = None
    remote_identity: CodeRemoteIdentity | None = None

    @model_validator(mode="after")
    def validate_transport(self):
        if self.mode == "local":
            if self.remote_name is not None or self.remote_identity is not None:
                raise ValueError(
                    "Local code transport cannot configure a remote name or identity."
                )
            return self

        if not self.remote_name or not self.remote_name.strip():
            raise ValueError("git_remote code transport requires remote_name.")
        if not self.remote_identity or not self.remote_identity.strip():
            raise ValueError("git_remote code transport requires remote_identity.")
        return self


class CodeDeliveryConfig(ProjectCtlModel):
    mode: Literal["local", "direct_git", "review_required"] = "local"


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


class OrchestrationConfig(ProjectCtlModel):
    max_active_runs: int = Field(
        default=1,
        ge=1,
        le=8,
        description=(
            "Maximum automated active runs allowed for this project. "
            "Values above 1 require M4.1/M4.2 parallel proof before admission."
        ),
    )


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


class ProjectConfigV2(ProjectCtlModel):
    schema_kind: Literal["projectctl.project_config"] = "projectctl.project_config"
    schema_version: Literal[2] = 2
    project: ProjectIdentity
    task_store: TaskStoreConfigV2 = Field(default_factory=TaskStoreConfigV2)
    paths: ProjectPaths = Field(default_factory=ProjectPaths)
    knowledge: KnowledgeConfig = Field(default_factory=KnowledgeConfig)
    scheduler: SchedulerConfig = Field(default_factory=SchedulerConfig)
    quota: QuotaPolicy = Field(default_factory=QuotaPolicy)
    features: FeatureFlags = Field(default_factory=FeatureFlags)
    model_profiles: dict[ModelProfile, ModelProfileConfig] = Field(default_factory=default_model_profiles)


class ProjectConfigV3(ProjectCtlModel):
    schema_kind: Literal["projectctl.project_config"] = "projectctl.project_config"
    schema_version: Literal[3] = 3
    project: ProjectIdentity
    task_store: TaskStoreConfigV3 = Field(default_factory=TaskStoreConfigV3)
    paths: ProjectPaths = Field(default_factory=ProjectPaths)
    knowledge: KnowledgeConfig = Field(default_factory=KnowledgeConfig)
    scheduler: SchedulerConfig = Field(default_factory=SchedulerConfig)
    quota: QuotaPolicy = Field(default_factory=QuotaPolicy)
    features: FeatureFlags = Field(default_factory=FeatureFlags)
    model_profiles: dict[ModelProfile, ModelProfileConfig] = Field(default_factory=default_model_profiles)


class ProjectConfigV4(ProjectCtlModel):
    schema_kind: Literal["projectctl.project_config"] = "projectctl.project_config"
    schema_version: Literal[4] = 4
    project: ProjectIdentity
    task_store: TaskStoreConfigV4 = Field(default_factory=TaskStoreConfigV4)
    paths: ProjectPaths = Field(default_factory=ProjectPaths)
    knowledge: KnowledgeConfig = Field(default_factory=KnowledgeConfig)
    scheduler: SchedulerConfig = Field(default_factory=SchedulerConfig)
    quota: QuotaPolicy = Field(default_factory=QuotaPolicy)
    features: FeatureFlags = Field(default_factory=FeatureFlags)
    model_profiles: dict[ModelProfile, ModelProfileConfig] = Field(default_factory=default_model_profiles)


class ProjectConfigV5(ProjectCtlModel):
    schema_kind: Literal["projectctl.project_config"] = "projectctl.project_config"
    schema_version: Literal[5] = 5
    project: ProjectIdentity
    task_store: TaskStoreConfigV4 = Field(default_factory=TaskStoreConfigV4)
    code_transport: CodeTransportConfig = Field(default_factory=CodeTransportConfig)
    paths: ProjectPaths = Field(default_factory=ProjectPaths)
    knowledge: KnowledgeConfig = Field(default_factory=KnowledgeConfig)
    scheduler: SchedulerConfig = Field(default_factory=SchedulerConfig)
    quota: QuotaPolicy = Field(default_factory=QuotaPolicy)
    features: FeatureFlags = Field(default_factory=FeatureFlags)
    model_profiles: dict[ModelProfile, ModelProfileConfig] = Field(default_factory=default_model_profiles)


class ProjectConfigV6(ProjectCtlModel):
    schema_kind: Literal["projectctl.project_config"] = "projectctl.project_config"
    schema_version: Literal[6] = 6
    project: ProjectIdentity
    task_store: TaskStoreConfigV4 = Field(default_factory=TaskStoreConfigV4)
    code_transport: CodeTransportConfig = Field(default_factory=CodeTransportConfig)
    code_delivery: CodeDeliveryConfig = Field(default_factory=CodeDeliveryConfig)
    paths: ProjectPaths = Field(default_factory=ProjectPaths)
    knowledge: KnowledgeConfig = Field(default_factory=KnowledgeConfig)
    scheduler: SchedulerConfig = Field(default_factory=SchedulerConfig)
    quota: QuotaPolicy = Field(default_factory=QuotaPolicy)
    features: FeatureFlags = Field(default_factory=FeatureFlags)
    model_profiles: dict[ModelProfile, ModelProfileConfig] = Field(default_factory=default_model_profiles)

    @model_validator(mode="after")
    def validate_delivery_transport(self):
        if (
            self.code_delivery.mode in {"direct_git", "review_required"}
            and self.code_transport.mode != "git_remote"
        ):
            raise ValueError(
                f"{self.code_delivery.mode} code delivery requires "
                "code_transport.mode='git_remote'."
            )
        return self


class ProjectConfigV7(ProjectCtlModel):
    schema_kind: Literal["projectctl.project_config"] = "projectctl.project_config"
    schema_version: Literal[7] = 7
    project: ProjectIdentity
    task_store: TaskStoreConfigV5 = Field(default_factory=TaskStoreConfigV5)
    code_transport: CodeTransportConfig = Field(default_factory=CodeTransportConfig)
    code_delivery: CodeDeliveryConfig = Field(default_factory=CodeDeliveryConfig)
    paths: ProjectPaths = Field(default_factory=ProjectPaths)
    knowledge: KnowledgeConfig = Field(default_factory=KnowledgeConfig)
    scheduler: SchedulerConfig = Field(default_factory=SchedulerConfig)
    quota: QuotaPolicy = Field(default_factory=QuotaPolicy)
    features: FeatureFlags = Field(default_factory=FeatureFlags)
    model_profiles: dict[ModelProfile, ModelProfileConfig] = Field(default_factory=default_model_profiles)

    @model_validator(mode="after")
    def validate_project_config(self):
        if (
            self.code_delivery.mode in {"direct_git", "review_required"}
            and self.code_transport.mode != "git_remote"
        ):
            raise ValueError(
                f"{self.code_delivery.mode} code delivery requires "
                "code_transport.mode='git_remote'."
            )
        if self.task_store.provider == "jira":
            if not self.task_store.site or not self.task_store.project:
                raise ValueError(
                    "Jira task authority requires task_store.site and task_store.project."
                )
        return self


class ProjectConfigV8(ProjectCtlModel):
    schema_kind: Literal["projectctl.project_config"] = "projectctl.project_config"
    schema_version: Literal[8] = 8
    project: ProjectIdentity
    task_store: TaskStoreConfig = Field(default_factory=TaskStoreConfig)
    code_transport: CodeTransportConfig = Field(default_factory=CodeTransportConfig)
    code_delivery: CodeDeliveryConfig = Field(default_factory=CodeDeliveryConfig)
    paths: ProjectPaths = Field(default_factory=ProjectPaths)
    knowledge: KnowledgeConfig = Field(default_factory=KnowledgeConfig)
    scheduler: SchedulerConfig = Field(default_factory=SchedulerConfig)
    quota: QuotaPolicy = Field(default_factory=QuotaPolicy)
    features: FeatureFlags = Field(default_factory=FeatureFlags)
    model_profiles: dict[ModelProfile, ModelProfileConfig] = Field(default_factory=default_model_profiles)

    @model_validator(mode="after")
    def validate_project_config(self):
        if (
            self.code_delivery.mode in {"direct_git", "review_required"}
            and self.code_transport.mode != "git_remote"
        ):
            raise ValueError(
                f"{self.code_delivery.mode} code delivery requires "
                "code_transport.mode='git_remote'."
            )
        if self.task_store.provider == "jira":
            if not self.task_store.site or not self.task_store.project:
                raise ValueError(
                    "Jira task authority requires task_store.site and task_store.project."
                )
        elif (
            self.task_store.jira_policy.ready_statuses
            or self.task_store.jira_policy.link_rules
        ):
            raise ValueError(
                "task_store.jira_policy is only valid with provider='jira'."
            )
        return self


class ProjectConfigV9(ProjectCtlModel):
    schema_kind: Literal["projectctl.project_config"] = "projectctl.project_config"
    schema_version: Literal[9] = 9
    project: ProjectIdentity
    task_store: TaskStoreConfig = Field(default_factory=TaskStoreConfig)
    code_transport: CodeTransportConfig = Field(default_factory=CodeTransportConfig)
    code_delivery: CodeDeliveryConfig = Field(default_factory=CodeDeliveryConfig)
    paths: ProjectPaths = Field(default_factory=ProjectPaths)
    knowledge: KnowledgeConfig = Field(default_factory=KnowledgeConfig)
    scheduler: SchedulerConfig = Field(default_factory=SchedulerConfig)
    orchestration: OrchestrationConfig = Field(default_factory=OrchestrationConfig)
    quota: QuotaPolicy = Field(default_factory=QuotaPolicy)
    features: FeatureFlags = Field(default_factory=FeatureFlags)
    model_profiles: dict[ModelProfile, ModelProfileConfig] = Field(default_factory=default_model_profiles)

    @model_validator(mode="after")
    def validate_project_config(self):
        if (
            self.code_delivery.mode in {"direct_git", "review_required"}
            and self.code_transport.mode != "git_remote"
        ):
            raise ValueError(
                f"{self.code_delivery.mode} code delivery requires "
                "code_transport.mode='git_remote'."
            )
        if self.task_store.provider == "jira":
            if not self.task_store.site or not self.task_store.project:
                raise ValueError(
                    "Jira task authority requires task_store.site and task_store.project."
                )
        elif (
            self.task_store.jira_policy.ready_statuses
            or self.task_store.jira_policy.link_rules
        ):
            raise ValueError(
                "task_store.jira_policy is only valid with provider='jira'."
            )
        return self


class ScopeGovernanceConfig(ProjectCtlModel):
    """Durable project policy for serial execution scope enforcement."""

    mode: Literal["optional", "required"] = "optional"


class ProjectConfig(ProjectConfigV9):
    """Current configuration; legacy versions remain independently parseable."""

    schema_version: Literal[10] = 10
    scope_governance: ScopeGovernanceConfig = Field(
        default_factory=ScopeGovernanceConfig
    )
