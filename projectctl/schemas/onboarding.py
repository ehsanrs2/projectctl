from typing import Literal

from pydantic import AwareDatetime, Field

from projectctl.schemas.base import ProjectCtlModel
from projectctl.schemas.config import RepoRelativePath


class DetectedAsset(ProjectCtlModel):
    path: RepoRelativePath
    kind: str
    role: str | None = None
    scope: RepoRelativePath | None = None


class KnowledgeBinding(ProjectCtlModel):
    role: str
    sources: list[RepoRelativePath] = Field(default_factory=list)


class ProjectInspectionV1(ProjectCtlModel):
    schema_kind: Literal["projectctl.project_inspection"] = "projectctl.project_inspection"
    schema_version: Literal[1] = 1

    project_root: str
    classification: str
    confidence: str
    evidence_score: int = 0
    baseline_commit: str | None = None
    dirty: bool = False
    repository_fingerprint: str

    assets: list[DetectedAsset] = Field(default_factory=list)
    suggested_bindings: list[KnowledgeBinding] = Field(default_factory=list)
    detected_task_systems: list[str] = Field(default_factory=list)
    unresolved_decisions: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class ProjectInspectionV2(ProjectCtlModel):
    schema_kind: Literal["projectctl.project_inspection"] = "projectctl.project_inspection"
    schema_version: Literal[2] = 2

    project_root: str
    classification: str
    confidence: str
    evidence_score: int = 0
    baseline_commit: str | None = None
    dirty: bool = False
    repository_fingerprint: str

    assets: list[DetectedAsset] = Field(default_factory=list)
    suggested_bindings: list[KnowledgeBinding] = Field(default_factory=list)
    detected_task_systems: list[str] = Field(default_factory=list)
    github_repository: str | None = None
    unresolved_decisions: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class ProjectInspection(ProjectCtlModel):
    schema_kind: Literal["projectctl.project_inspection"] = "projectctl.project_inspection"
    schema_version: Literal[3] = 3

    project_root: str
    classification: str
    confidence: str
    evidence_score: int = 0
    baseline_commit: str | None = None
    dirty: bool = False
    repository_fingerprint: str

    assets: list[DetectedAsset] = Field(default_factory=list)
    suggested_bindings: list[KnowledgeBinding] = Field(default_factory=list)
    detected_task_systems: list[str] = Field(default_factory=list)
    github_repository: str | None = None
    git_remote_name: str | None = None
    git_remote_identity: str | None = None
    unresolved_decisions: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class AdoptionPlanV1(ProjectCtlModel):
    schema_kind: Literal["projectctl.adoption_plan"] = "projectctl.adoption_plan"
    schema_version: Literal[1] = 1

    project_root: str
    created_at: AwareDatetime
    baseline_commit: str | None = None
    repository_fingerprint: str
    dirty: bool = False

    preserve: list[RepoRelativePath] = Field(default_factory=list)
    create: list[RepoRelativePath] = Field(default_factory=list)
    knowledge_bindings: list[KnowledgeBinding] = Field(default_factory=list)
    task_store_provider: str | None = None
    unresolved_decisions: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)


class AdoptionPlanV2(ProjectCtlModel):
    schema_kind: Literal["projectctl.adoption_plan"] = "projectctl.adoption_plan"
    schema_version: Literal[2] = 2

    project_root: str
    created_at: AwareDatetime
    baseline_commit: str | None = None
    repository_fingerprint: str
    dirty: bool = False

    preserve: list[RepoRelativePath] = Field(default_factory=list)
    create: list[RepoRelativePath] = Field(default_factory=list)
    knowledge_bindings: list[KnowledgeBinding] = Field(default_factory=list)
    task_store_provider: str | None = None
    task_store_repository: str | None = None
    unresolved_decisions: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)


class AdoptionPlanV3(ProjectCtlModel):
    schema_kind: Literal["projectctl.adoption_plan"] = "projectctl.adoption_plan"
    schema_version: Literal[3] = 3

    project_root: str
    created_at: AwareDatetime
    baseline_commit: str | None = None
    repository_fingerprint: str
    dirty: bool = False

    preserve: list[RepoRelativePath] = Field(default_factory=list)
    create: list[RepoRelativePath] = Field(default_factory=list)
    knowledge_bindings: list[KnowledgeBinding] = Field(default_factory=list)
    task_store_provider: str | None = None
    task_store_repository: str | None = None
    task_store_team: str | None = None
    unresolved_decisions: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)


class AdoptionPlanV4(ProjectCtlModel):
    schema_kind: Literal["projectctl.adoption_plan"] = "projectctl.adoption_plan"
    schema_version: Literal[4] = 4

    project_root: str
    created_at: AwareDatetime
    baseline_commit: str | None = None
    repository_fingerprint: str
    dirty: bool = False

    preserve: list[RepoRelativePath] = Field(default_factory=list)
    create: list[RepoRelativePath] = Field(default_factory=list)
    knowledge_bindings: list[KnowledgeBinding] = Field(default_factory=list)
    task_store_provider: str | None = None
    task_store_repository: str | None = None
    task_store_team: str | None = None
    code_transport_mode: Literal["local", "git_remote"] = "local"
    code_remote_name: str | None = None
    code_remote_identity: str | None = None
    unresolved_decisions: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)


class AdoptionPlan(ProjectCtlModel):
    schema_kind: Literal["projectctl.adoption_plan"] = "projectctl.adoption_plan"
    schema_version: Literal[5] = 5

    project_root: str
    created_at: AwareDatetime
    baseline_commit: str | None = None
    repository_fingerprint: str
    dirty: bool = False

    preserve: list[RepoRelativePath] = Field(default_factory=list)
    create: list[RepoRelativePath] = Field(default_factory=list)
    knowledge_bindings: list[KnowledgeBinding] = Field(default_factory=list)
    task_store_provider: str | None = None
    task_store_repository: str | None = None
    task_store_team: str | None = None
    code_transport_mode: Literal["local", "git_remote"] = "local"
    code_remote_name: str | None = None
    code_remote_identity: str | None = None
    code_delivery_mode: Literal["local", "direct_git", "review_required"] = "local"
    unresolved_decisions: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)


class AdoptionManifestV1(ProjectCtlModel):
    schema_kind: Literal["projectctl.adoption_manifest"] = "projectctl.adoption_manifest"
    schema_version: Literal[1] = 1

    mode: Literal["brownfield"] = "brownfield"
    adopted_at: AwareDatetime
    baseline_commit: str | None = None
    repository_fingerprint: str

    preserved: list[RepoRelativePath] = Field(default_factory=list)
    created: list[RepoRelativePath] = Field(default_factory=list)
    knowledge_bindings: list[KnowledgeBinding] = Field(default_factory=list)
    task_store_provider: str | None = None
    unresolved_decisions: list[str] = Field(default_factory=list)


class AdoptionManifestV2(ProjectCtlModel):
    schema_kind: Literal["projectctl.adoption_manifest"] = "projectctl.adoption_manifest"
    schema_version: Literal[2] = 2

    mode: Literal["brownfield"] = "brownfield"
    adopted_at: AwareDatetime
    baseline_commit: str | None = None
    repository_fingerprint: str

    preserved: list[RepoRelativePath] = Field(default_factory=list)
    created: list[RepoRelativePath] = Field(default_factory=list)
    knowledge_bindings: list[KnowledgeBinding] = Field(default_factory=list)
    task_store_provider: str | None = None
    task_store_repository: str | None = None
    unresolved_decisions: list[str] = Field(default_factory=list)


class AdoptionManifestV3(ProjectCtlModel):
    schema_kind: Literal["projectctl.adoption_manifest"] = "projectctl.adoption_manifest"
    schema_version: Literal[3] = 3

    mode: Literal["brownfield"] = "brownfield"
    adopted_at: AwareDatetime
    baseline_commit: str | None = None
    repository_fingerprint: str

    preserved: list[RepoRelativePath] = Field(default_factory=list)
    created: list[RepoRelativePath] = Field(default_factory=list)
    knowledge_bindings: list[KnowledgeBinding] = Field(default_factory=list)
    task_store_provider: str | None = None
    task_store_repository: str | None = None
    task_store_team: str | None = None
    unresolved_decisions: list[str] = Field(default_factory=list)


class AdoptionManifestV4(ProjectCtlModel):
    schema_kind: Literal["projectctl.adoption_manifest"] = "projectctl.adoption_manifest"
    schema_version: Literal[4] = 4

    mode: Literal["brownfield"] = "brownfield"
    adopted_at: AwareDatetime
    baseline_commit: str | None = None
    repository_fingerprint: str

    preserved: list[RepoRelativePath] = Field(default_factory=list)
    created: list[RepoRelativePath] = Field(default_factory=list)
    knowledge_bindings: list[KnowledgeBinding] = Field(default_factory=list)
    task_store_provider: str | None = None
    task_store_repository: str | None = None
    task_store_team: str | None = None
    code_transport_mode: Literal["local", "git_remote"] = "local"
    code_remote_name: str | None = None
    code_remote_identity: str | None = None
    unresolved_decisions: list[str] = Field(default_factory=list)


class AdoptionManifest(ProjectCtlModel):
    schema_kind: Literal["projectctl.adoption_manifest"] = "projectctl.adoption_manifest"
    schema_version: Literal[5] = 5

    mode: Literal["brownfield"] = "brownfield"
    adopted_at: AwareDatetime
    baseline_commit: str | None = None
    repository_fingerprint: str

    preserved: list[RepoRelativePath] = Field(default_factory=list)
    created: list[RepoRelativePath] = Field(default_factory=list)
    knowledge_bindings: list[KnowledgeBinding] = Field(default_factory=list)
    task_store_provider: str | None = None
    task_store_repository: str | None = None
    task_store_team: str | None = None
    code_transport_mode: Literal["local", "git_remote"] = "local"
    code_remote_name: str | None = None
    code_remote_identity: str | None = None
    code_delivery_mode: Literal["local", "direct_git", "review_required"] = "local"
    unresolved_decisions: list[str] = Field(default_factory=list)

