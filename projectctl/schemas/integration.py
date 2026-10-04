from __future__ import annotations

from typing import Literal

from pydantic import AwareDatetime, Field, model_validator

from projectctl.schemas.base import ProjectCtlModel
from projectctl.schemas.config import RepoRelativePath


class IntegrationManifestV1(ProjectCtlModel):
    schema_kind: Literal["projectctl.integration_manifest"] = "projectctl.integration_manifest"
    schema_version: Literal[1] = 1
    run_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    target_ref: str = Field(min_length=1)
    base_commit: str = Field(min_length=7)
    candidate_commit: str = Field(min_length=7)
    target_before: str = Field(min_length=7)
    target_after: str = Field(min_length=7)
    evidence_manifest: RepoRelativePath
    evidence_digest: str = Field(min_length=1)
    task_completed: bool
    worktree_cleaned: bool
    integrated_at: AwareDatetime


class IntegrationManifest(ProjectCtlModel):
    schema_kind: Literal["projectctl.integration_manifest"] = "projectctl.integration_manifest"
    schema_version: Literal[2] = 2
    run_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    target_ref: str = Field(min_length=1)
    base_commit: str = Field(min_length=7)
    candidate_commit: str = Field(min_length=7)
    target_before: str = Field(min_length=7)
    target_after: str = Field(min_length=7)
    evidence_manifest: RepoRelativePath
    evidence_digest: str = Field(min_length=1)
    publication_required: bool = False
    publication_manifest: RepoRelativePath | None = None
    publication_digest: str | None = None
    task_completed: bool
    claim_released: bool = False
    worktree_cleaned: bool
    integrated_at: AwareDatetime
    completed_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def validate_publication_chain(self):
        if self.publication_required:
            if self.task_completed and (
                not self.publication_manifest or not self.publication_digest
            ):
                raise ValueError(
                    "Published task completion requires publication manifest and digest."
                )
        elif self.publication_manifest is not None or self.publication_digest is not None:
            raise ValueError(
                "Local-only integration cannot reference a publication manifest."
            )
        if self.task_completed and self.completed_at is None:
            raise ValueError("Completed integration requires completed_at.")
        return self


def parse_integration_manifest(
    raw: object,
) -> IntegrationManifest | IntegrationManifestV1:
    if not isinstance(raw, dict):
        raise ValueError("Integration manifest must be an object.")
    version = raw.get("schema_version", 1)
    if version == 2:
        return IntegrationManifest.model_validate(raw)
    if version == 1:
        return IntegrationManifestV1.model_validate(raw)
    raise ValueError(f"Unsupported integration manifest schema version: {version}")


class RecoveryAction(ProjectCtlModel):
    run_id: str = Field(min_length=1)
    previous_status: str = Field(min_length=1)
    resolved_status: str = Field(min_length=1)
    action: str = Field(min_length=1)
    details: list[str] = Field(default_factory=list)


class RecoveryReport(ProjectCtlModel):
    schema_kind: Literal["projectctl.recovery_report"] = "projectctl.recovery_report"
    schema_version: Literal[1] = 1
    project_root: str = Field(min_length=1)
    actions: list[RecoveryAction] = Field(default_factory=list)
    observed_at: AwareDatetime
