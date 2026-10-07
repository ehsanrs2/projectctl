from __future__ import annotations

from typing import Literal

from pydantic import AwareDatetime, Field, model_validator

from projectctl.schemas.base import ProjectCtlModel
from projectctl.schemas.config import RepoRelativePath


ExecutionPathKind = Literal["exact", "tree"]
ExecutionInputPhase = Literal["preclaim", "admitted"]
ExecutionInputLineageKind = Literal["initial", "reapplication"]


class ExecutionPathScope(ProjectCtlModel):
    path: RepoRelativePath
    kind: ExecutionPathKind = "exact"


class ExecutionInputEvidence(ProjectCtlModel):
    scope: ExecutionPathScope
    digest: str = Field(min_length=1)


class ClaimTransitionEvidence(ProjectCtlModel):
    provider: str = Field(min_length=1)
    claim_digest: str = Field(min_length=1)
    before_selected_task_digest: str = Field(min_length=1)
    after_selected_task_digest: str = Field(min_length=1)
    transition_kind: Literal["unchanged", "provider_native"]
    validated_at: AwareDatetime


class ExecutionInputManifest(ProjectCtlModel):
    schema_kind: Literal["projectctl.execution_input_manifest"] = (
        "projectctl.execution_input_manifest"
    )
    schema_version: Literal[1] = 1

    project_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    task_provider: str = Field(min_length=1)

    scheduler_task_snapshot_digest: str = Field(min_length=1)
    project_state_digest: str = Field(min_length=1)

    preclaim_task_scope_digest: str = Field(min_length=1)
    admitted_task_scope_digest: str = Field(min_length=1)
    scoped_task_ids: list[str] = Field(min_length=1)

    base_commit: str = Field(min_length=7)
    integration_target_ref: str = Field(min_length=1)

    scope_digest: str | None = None
    inputs: list[ExecutionInputEvidence] = Field(default_factory=list)
    writes: list[ExecutionPathScope] = Field(default_factory=list)
    resources: list[str] = Field(default_factory=list)

    phase: ExecutionInputPhase = "preclaim"
    claim_transition: ClaimTransitionEvidence | None = None

    lineage_kind: ExecutionInputLineageKind = "initial"
    parent_execution_input_digest: str | None = None
    created_at: AwareDatetime

    @model_validator(mode="after")
    def validate_contract(self):
        if self.phase == "admitted" and self.claim_transition is None:
            raise ValueError(
                "Admitted execution input requires claim-transition evidence."
            )
        if self.phase == "preclaim" and self.claim_transition is not None:
            raise ValueError(
                "Preclaim execution input cannot contain claim-transition evidence."
            )
        if self.lineage_kind == "initial" and self.parent_execution_input_digest is not None:
            raise ValueError(
                "Initial execution input cannot have a parent execution-input digest."
            )
        if self.lineage_kind == "reapplication" and not self.parent_execution_input_digest:
            raise ValueError(
                "Reapplied execution input requires a parent execution-input digest."
            )
        if len(self.scoped_task_ids) != len(set(self.scoped_task_ids)):
            raise ValueError("Execution input scoped task ids must be unique.")
        if len(self.resources) != len(set(self.resources)):
            raise ValueError("Execution input resource keys must be unique.")
        return self
