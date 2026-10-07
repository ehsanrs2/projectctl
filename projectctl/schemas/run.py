from typing import Literal

from pydantic import AwareDatetime, Field, model_validator

from projectctl.core.enums import ModelProfile, ReasoningLevel, RunStatus, RunStatusV1, RunTerminalReason
from projectctl.schemas.base import ProjectCtlModel
from projectctl.schemas.config import RepoRelativePath
from projectctl.schemas.execution_input import ExecutionPathScope


class WorkerDescriptor(ProjectCtlModel):
    provider: str
    model_profile: ModelProfile
    reasoning: ReasoningLevel
    actual_model: str | None = None


class ContextArtifact(ProjectCtlModel):
    path: RepoRelativePath
    digest: str


class InstructionSource(ProjectCtlModel):
    path: RepoRelativePath
    digest: str
    scope: str = Field(min_length=1)


class KnowledgeSource(ProjectCtlModel):
    role: str = Field(min_length=1)
    path: RepoRelativePath
    digest: str


class ContextManifestV1(ProjectCtlModel):
    schema_kind: Literal["projectctl.context_manifest"] = "projectctl.context_manifest"
    schema_version: Literal[1] = 1
    task_id: str
    git_commit: str
    artifacts: list[ContextArtifact] = Field(default_factory=list)
    code_paths: list[RepoRelativePath] = Field(default_factory=list)
    graph_revision: str | None = None


class ContextManifestV2(ProjectCtlModel):
    schema_kind: Literal["projectctl.context_manifest"] = "projectctl.context_manifest"
    schema_version: Literal[2] = 2
    task_id: str = Field(min_length=1)
    git_commit: str = Field(min_length=7)
    task_snapshot_digest: str = Field(min_length=1)
    project_state_digest: str = Field(min_length=1)
    spec_digest: str | None = None
    artifacts: list[ContextArtifact] = Field(default_factory=list)
    code_paths: list[RepoRelativePath] = Field(default_factory=list)
    instruction_sources: list[InstructionSource] = Field(default_factory=list)
    knowledge_sources: list[KnowledgeSource] = Field(default_factory=list)
    graph_revision: str | None = None


class ContextManifest(ProjectCtlModel):
    schema_kind: Literal["projectctl.context_manifest"] = "projectctl.context_manifest"
    schema_version: Literal[3] = 3
    task_id: str = Field(min_length=1)
    git_commit: str = Field(min_length=7)
    task_snapshot_digest: str = Field(min_length=1)
    execution_input_digest: str | None = None
    claim_transition_digest: str | None = None
    project_state_digest: str = Field(min_length=1)
    spec_digest: str | None = None
    artifacts: list[ContextArtifact] = Field(default_factory=list)
    code_paths: list[RepoRelativePath] = Field(default_factory=list)
    input_scopes: list[ExecutionPathScope] = Field(default_factory=list)
    write_scopes: list[ExecutionPathScope] = Field(default_factory=list)
    instruction_sources: list[InstructionSource] = Field(default_factory=list)
    knowledge_sources: list[KnowledgeSource] = Field(default_factory=list)
    graph_revision: str | None = None


def parse_context_manifest(raw: object) -> ContextManifest | ContextManifestV2 | ContextManifestV1:
    if not isinstance(raw, dict):
        raise ValueError("Context manifest must be an object.")
    version = raw.get("schema_version", 1)
    if version == 3:
        return ContextManifest.model_validate(raw)
    if version == 2:
        return ContextManifestV2.model_validate(raw)
    if version == 1:
        return ContextManifestV1.model_validate(raw)
    raise ValueError(f"Unsupported context manifest schema version: {version}")


class RunManifestV1(ProjectCtlModel):
    schema_kind: Literal["projectctl.run_manifest"] = "projectctl.run_manifest"
    schema_version: Literal[1] = 1
    run_id: str
    task_id: str
    status: RunStatusV1 = RunStatusV1.PLANNED
    base_commit: str | None = None
    worker: WorkerDescriptor
    context_manifest: RepoRelativePath | None = None
    started_at: AwareDatetime | None = None
    completed_at: AwareDatetime | None = None
    checkpoint_at: AwareDatetime | None = None


class RunManifest(ProjectCtlModel):
    schema_kind: Literal["projectctl.run_manifest"] = "projectctl.run_manifest"
    schema_version: Literal[2] = 2
    run_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    execution_plan_digest: str = Field(min_length=1)
    status: RunStatus = RunStatus.PLANNED
    terminal_reason: RunTerminalReason | None = None
    base_commit: str = Field(min_length=7)
    candidate_commit: str | None = None
    branch_name: str = Field(min_length=1)
    worktree_id: str = Field(min_length=1)
    worker: WorkerDescriptor
    worker_thread_id: str | None = None
    context_manifest: RepoRelativePath | None = None
    evidence_manifest: RepoRelativePath | None = None
    started_at: AwareDatetime | None = None
    completed_at: AwareDatetime | None = None
    checkpoint_at: AwareDatetime | None = None
    checkpoint_ref: str | None = None

    @model_validator(mode="after")
    def validate_terminal_reason(self):
        terminal_with_reason = {
            RunStatus.BLOCKED_POLICY,
            RunStatus.NEEDS_DECISION,
            RunStatus.FAILED,
            RunStatus.CANCELLED,
            RunStatus.ABANDONED,
        }
        if self.status in terminal_with_reason and self.terminal_reason is None:
            raise ValueError("Terminal/blocked run status requires terminal_reason.")
        if self.status == RunStatus.PASSED and self.terminal_reason is not None:
            raise ValueError("A passed run cannot have terminal_reason.")
        return self
