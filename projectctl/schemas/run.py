from typing import Literal

from pydantic import AwareDatetime, Field

from projectctl.core.enums import ModelProfile, ReasoningLevel, RunStatus
from projectctl.schemas.base import ProjectCtlModel
from projectctl.schemas.config import RepoRelativePath


class WorkerDescriptor(ProjectCtlModel):
    provider: str
    model_profile: ModelProfile
    reasoning: ReasoningLevel
    actual_model: str | None = None


class ContextArtifact(ProjectCtlModel):
    path: RepoRelativePath
    digest: str


class ContextManifest(ProjectCtlModel):
    schema_kind: Literal["projectctl.context_manifest"] = "projectctl.context_manifest"
    schema_version: Literal[1] = 1
    task_id: str
    git_commit: str
    artifacts: list[ContextArtifact] = Field(default_factory=list)
    code_paths: list[RepoRelativePath] = Field(default_factory=list)
    graph_revision: str | None = None


class RunManifest(ProjectCtlModel):
    schema_kind: Literal["projectctl.run_manifest"] = "projectctl.run_manifest"
    schema_version: Literal[1] = 1
    run_id: str
    task_id: str
    status: RunStatus = RunStatus.PLANNED
    base_commit: str | None = None
    worker: WorkerDescriptor
    context_manifest: RepoRelativePath | None = None
    started_at: AwareDatetime | None = None
    completed_at: AwareDatetime | None = None
    checkpoint_at: AwareDatetime | None = None
