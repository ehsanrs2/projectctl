from __future__ import annotations

from typing import Literal

from pydantic import AwareDatetime, Field

from projectctl.schemas.base import ProjectCtlModel
from projectctl.schemas.config import RepoRelativePath


class IntegrationManifest(ProjectCtlModel):
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
