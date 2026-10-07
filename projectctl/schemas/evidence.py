from __future__ import annotations

from typing import Literal

from pydantic import AwareDatetime, Field, model_validator

from projectctl.schemas.base import ProjectCtlModel
from projectctl.schemas.config import RepoRelativePath


class EvidenceManifestV1(ProjectCtlModel):
    schema_kind: Literal["projectctl.evidence_manifest"] = "projectctl.evidence_manifest"
    schema_version: Literal[1] = 1
    run_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    base_commit: str = Field(min_length=7)
    candidate_commit: str = Field(min_length=7)
    diff_digest: str = Field(min_length=1)
    worker_result_digest: str = Field(min_length=1)
    verification_manifest_digest: str = Field(min_length=1)
    changed_paths: list[RepoRelativePath] = Field(default_factory=list)
    overall_pass: bool
    generated_at: AwareDatetime


class EvidenceManifestV2(ProjectCtlModel):
    schema_kind: Literal["projectctl.evidence_manifest"] = "projectctl.evidence_manifest"
    schema_version: Literal[2] = 2
    run_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    base_commit: str = Field(min_length=7)
    candidate_commit: str | None = Field(default=None, min_length=7)
    diff_digest: str = Field(min_length=1)
    workspace_state_digest: str = Field(min_length=1)
    worker_result_digest: str = Field(min_length=1)
    verification_manifest_digest: str = Field(min_length=1)
    verification_profile_digest: str = Field(min_length=1)
    changed_paths: list[RepoRelativePath] = Field(default_factory=list)
    overall_pass: bool
    generated_at: AwareDatetime

    @model_validator(mode="after")
    def passing_evidence_requires_candidate(self):
        if self.overall_pass and self.candidate_commit is None:
            raise ValueError("Passing evidence requires candidate_commit.")
        return self


class EvidenceManifest(ProjectCtlModel):
    schema_kind: Literal["projectctl.evidence_manifest"] = "projectctl.evidence_manifest"
    schema_version: Literal[3] = 3
    run_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    base_commit: str = Field(min_length=7)
    execution_input_digest: str | None = None
    candidate_commit: str | None = Field(default=None, min_length=7)
    diff_digest: str = Field(min_length=1)
    workspace_state_digest: str = Field(min_length=1)
    worker_result_digest: str = Field(min_length=1)
    verification_manifest_digest: str = Field(min_length=1)
    verification_profile_digest: str = Field(min_length=1)
    changed_paths: list[RepoRelativePath] = Field(default_factory=list)
    overall_pass: bool
    generated_at: AwareDatetime

    @model_validator(mode="after")
    def passing_evidence_requires_candidate(self):
        if self.overall_pass and self.candidate_commit is None:
            raise ValueError("Passing evidence requires candidate_commit.")
        return self


def parse_evidence_manifest(
    raw: object,
) -> EvidenceManifest | EvidenceManifestV2 | EvidenceManifestV1:
    if not isinstance(raw, dict):
        raise ValueError("Evidence manifest must be an object.")
    version = raw.get("schema_version", 1)
    if version == 3:
        return EvidenceManifest.model_validate(raw)
    if version == 2:
        return EvidenceManifestV2.model_validate(raw)
    if version == 1:
        return EvidenceManifestV1.model_validate(raw)
    raise ValueError(f"Unsupported evidence manifest schema version: {version}")
