from __future__ import annotations

from typing import Literal

from pydantic import AwareDatetime, Field

from projectctl.schemas.base import ProjectCtlModel
from projectctl.schemas.config import RepoRelativePath
from projectctl.schemas.execution_input import ExecutionPathScope


DiscoveryProvider = Literal["builtin", "graphify"]
DiscoveryStrength = Literal["explicit", "structural", "inferred", "ambiguous"]
DiscoveryRole = Literal["input", "write_candidate", "test", "reference"]


class ContextDiscoveryEvidence(ProjectCtlModel):
    evidence_id: str = Field(min_length=1)
    provider: DiscoveryProvider
    kind: str = Field(min_length=1)
    strength: DiscoveryStrength
    source_path: RepoRelativePath | None = None
    source_location: str | None = None
    relation: str | None = None
    detail: str = Field(min_length=1)
    confidence_score: float | None = Field(default=None, ge=0.0, le=1.0)


class ContextPathCandidate(ProjectCtlModel):
    path: RepoRelativePath
    roles: list[DiscoveryRole] = Field(default_factory=list)
    score: int = Field(ge=0)
    evidence_ids: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)


class ContextDiscoveryReport(ProjectCtlModel):
    schema_kind: Literal["projectctl.context_discovery_report"] = (
        "projectctl.context_discovery_report"
    )
    schema_version: Literal[1] = 1
    discovery_id: str = Field(min_length=1)
    generated_at: AwareDatetime
    project_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    integration_target_ref: str = Field(min_length=1)
    base_commit: str = Field(min_length=1)
    task_digest: str = Field(min_length=1)
    repository_file_count: int = Field(ge=0)
    indexed_python_files: int = Field(ge=0)
    graphify_enabled: bool = False
    graphify_digest: str | None = None
    authoritative: Literal[False] = False
    candidates: list[ContextPathCandidate] = Field(default_factory=list)
    evidence: list[ContextDiscoveryEvidence] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ScopeCoverage(ProjectCtlModel):
    suggested_inputs_not_declared: list[RepoRelativePath] = Field(default_factory=list)
    suggested_writes_not_declared: list[RepoRelativePath] = Field(default_factory=list)
    declared_inputs_not_suggested: list[RepoRelativePath] = Field(default_factory=list)
    declared_writes_not_suggested: list[RepoRelativePath] = Field(default_factory=list)


class ContextScopeSuggestion(ProjectCtlModel):
    schema_kind: Literal["projectctl.context_scope_suggestion"] = (
        "projectctl.context_scope_suggestion"
    )
    schema_version: Literal[1] = 1
    suggestion_id: str = Field(min_length=1)
    generated_at: AwareDatetime
    project_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    base_commit: str = Field(min_length=1)
    discovery_digest: str = Field(min_length=1)
    authoritative: Literal[False] = False
    requires_human_review: Literal[True] = True
    input_scopes: list[ExecutionPathScope] = Field(default_factory=list)
    write_scopes: list[ExecutionPathScope] = Field(default_factory=list)
    declared_scope_present: bool = False
    declared_scope_digest: str | None = None
    coverage: ScopeCoverage = Field(default_factory=ScopeCoverage)
    warnings: list[str] = Field(default_factory=list)
