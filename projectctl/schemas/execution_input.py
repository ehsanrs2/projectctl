from __future__ import annotations

from typing import Literal

from pydantic import AwareDatetime, Field, model_validator

from projectctl.schemas.base import ProjectCtlModel
from projectctl.schemas.config import RepoRelativePath
from projectctl.schemas.task import NormalizedTask


ExecutionPathKind = Literal["exact", "tree"]


class ExecutionPathScope(ProjectCtlModel):
    path: RepoRelativePath
    kind: ExecutionPathKind = "exact"


class ExecutionCodeInput(ProjectCtlModel):
    scope: ExecutionPathScope
    digest: str = Field(min_length=1)


class ExecutionTaskInput(ProjectCtlModel):
    task_id: str = Field(min_length=1)
    digest: str = Field(min_length=1)
    task: NormalizedTask


class ExecutionInputLineage(ProjectCtlModel):
    source_execution_input_digest: str = Field(min_length=1)
    transformation: Literal["parallel_reapplication"]
    reapplication_id: str = Field(min_length=1)


class ExecutionInputManifestV1(ProjectCtlModel):
    schema_kind: Literal["projectctl.execution_input_manifest"] = (
        "projectctl.execution_input_manifest"
    )
    schema_version: Literal[1] = 1
    input_id: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    integration_target_ref: str = Field(min_length=1)
    base_commit: str = Field(min_length=7)
    project_state_digest: str = Field(min_length=1)
    scheduler_task_snapshot_digest: str = Field(min_length=1)
    task_scope_digest: str = Field(min_length=1)
    task_scope_ids: list[str] = Field(min_length=1)
    task_inputs: list[ExecutionTaskInput] = Field(min_length=1)
    references_digest: str = Field(min_length=1)
    code_inputs: list[ExecutionCodeInput] = Field(default_factory=list)
    write_scopes: list[ExecutionPathScope] = Field(default_factory=list)
    resources: list[str] = Field(default_factory=list)
    scope_policy_digest: str | None = None
    lineage: ExecutionInputLineage | None = None
    created_at: AwareDatetime


class ExecutionInputManifest(ExecutionInputManifestV1):
    """Runtime authority for new runs; legacy v1 stays audit-readable."""

    schema_version: Literal[2] = 2
    scope_governance_mode: Literal["optional", "required"]
    scope_catalog_source: Literal["canonical", "legacy", "absent"]

    @model_validator(mode="after")
    def validate_governed_scope(self):
        if self.scope_governance_mode == "required":
            if self.scope_catalog_source == "absent":
                raise ValueError("Required execution scope cannot have an absent catalog.")
            if (
                self.scope_policy_digest is None
                or not self.code_inputs
                or not self.write_scopes
            ):
                raise ValueError(
                    "Required execution scope must bind declared inputs and writes."
                )
        return self


def parse_execution_input_manifest(
    raw: object,
) -> ExecutionInputManifest | ExecutionInputManifestV1:
    if not isinstance(raw, dict):
        raise ValueError("Execution input manifest must be an object.")
    version = raw.get("schema_version", 1)
    if version == 2:
        return ExecutionInputManifest.model_validate(raw)
    if version == 1:
        return ExecutionInputManifestV1.model_validate(raw)
    raise ValueError(f"Unsupported execution input manifest version: {version!r}")


class ClaimTransitionEvidence(ProjectCtlModel):
    schema_kind: Literal["projectctl.claim_transition_evidence"] = (
        "projectctl.claim_transition_evidence"
    )
    schema_version: Literal[1] = 1
    run_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    provider: str = Field(min_length=1)
    execution_input_digest: str = Field(min_length=1)
    claim_request_digest: str = Field(min_length=1)
    claim_digest: str = Field(min_length=1)
    preclaim_task_digest: str = Field(min_length=1)
    postclaim_task_digest: str = Field(min_length=1)
    postclaim_task_scope_digest: str = Field(min_length=1)
    postclaim_task_scope_ids: list[str] = Field(min_length=1)
    postclaim_task_inputs: list[ExecutionTaskInput] = Field(min_length=1)
    observed_at: AwareDatetime
