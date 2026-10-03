from typing import Literal

from pydantic import AwareDatetime, Field

from projectctl.core.enums import (
    ApprovalPolicy,
    ExecutionSandboxMode,
    NetworkPolicy,
    WorkerResultStatus,
)
from projectctl.schemas.base import ProjectCtlModel
from projectctl.schemas.config import RepoRelativePath
from projectctl.schemas.run import WorkerDescriptor


class GitExecutionPolicy(ProjectCtlModel):
    allow_commit: bool = False
    allow_merge: bool = False
    allow_rebase: bool = False
    allow_push: bool = False


class ExecutionPolicy(ProjectCtlModel):
    sandbox: ExecutionSandboxMode = ExecutionSandboxMode.WORKSPACE_WRITE
    network: NetworkPolicy = NetworkPolicy.DISABLED
    approval: ApprovalPolicy = ApprovalPolicy.DENY_ALL
    git: GitExecutionPolicy = Field(default_factory=GitExecutionPolicy)


class ExecutionPlan(ProjectCtlModel):
    schema_kind: Literal["projectctl.execution_plan"] = "projectctl.execution_plan"
    schema_version: Literal[1] = 1
    plan_id: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    task_source_revision: str | None = None
    scheduler_decision_digest: str = Field(min_length=1)
    task_snapshot_digest: str = Field(min_length=1)
    project_state_digest: str = Field(min_length=1)
    quota_snapshot_digest: str = Field(min_length=1)
    base_commit: str = Field(min_length=7)
    integration_target_ref: str = Field(min_length=1)
    worker: WorkerDescriptor
    execution_policy: ExecutionPolicy = Field(default_factory=ExecutionPolicy)
    verification_profile: str = Field(default="default", min_length=1)
    created_at: AwareDatetime


class PermissionRequest(ProjectCtlModel):
    capability: str = Field(min_length=1)
    reason: str = Field(min_length=1)


class WorkerRequest(ProjectCtlModel):
    schema_kind: Literal["projectctl.worker_request"] = "projectctl.worker_request"
    schema_version: Literal[1] = 1
    run_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    base_commit: str = Field(min_length=7)
    branch_name: str = Field(min_length=1)
    worktree_id: str = Field(min_length=1)
    execution_plan_digest: str = Field(min_length=1)
    context_manifest_digest: str = Field(min_length=1)
    worker: WorkerDescriptor
    execution_policy: ExecutionPolicy
    objective: str = Field(min_length=1)
    acceptance_criteria: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    stop_conditions: list[str] = Field(default_factory=list)
    output_schema_kind: Literal["projectctl.worker_result"] = "projectctl.worker_result"


class WorkerResult(ProjectCtlModel):
    schema_kind: Literal["projectctl.worker_result"] = "projectctl.worker_result"
    schema_version: Literal[1] = 1
    run_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    status: WorkerResultStatus
    summary: str = Field(min_length=1)
    blockers: list[str] = Field(default_factory=list)
    requested_permissions: list[PermissionRequest] = Field(default_factory=list)
    suggested_verification: list[str] = Field(default_factory=list)
    worker_thread_id: str | None = None
    completed_at: AwareDatetime


class WorkerCheckpoint(ProjectCtlModel):
    schema_kind: Literal["projectctl.worker_checkpoint"] = "projectctl.worker_checkpoint"
    schema_version: Literal[1] = 1
    run_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    worker_thread_id: str | None = None
    worktree_id: str = Field(min_length=1)
    base_commit: str = Field(min_length=7)
    branch_name: str = Field(min_length=1)
    context_manifest_digest: str = Field(min_length=1)
    checkpoint_at: AwareDatetime


class ClaimResult(ProjectCtlModel):
    task_id: str = Field(min_length=1)
    actor: str = Field(min_length=1)
    claimed: bool
    observed_at: AwareDatetime
    reason: str | None = None


class EvidenceReference(ProjectCtlModel):
    path: RepoRelativePath
    digest: str = Field(min_length=1)
