from __future__ import annotations

from typing import Literal

from pydantic import AwareDatetime, Field

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


class ExecutionInputManifest(ProjectCtlModel):
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
