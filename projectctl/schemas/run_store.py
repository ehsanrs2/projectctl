from pydantic import AwareDatetime, Field

from projectctl.core.enums import RunStatus, RunTerminalReason
from projectctl.schemas.base import ProjectCtlModel


class RunRecord(ProjectCtlModel):
    run_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    status: RunStatus
    terminal_reason: RunTerminalReason | None = None
    execution_plan_digest: str = Field(min_length=1)
    base_commit: str = Field(min_length=7)
    candidate_commit: str | None = None
    branch_name: str = Field(min_length=1)
    worktree_id: str = Field(min_length=1)
    worktree_path: str = Field(min_length=1)
    worker_provider: str = Field(min_length=1)
    worker_thread_id: str | None = None
    lease_owner: str | None = None
    lease_expires_at: AwareDatetime | None = None
    heartbeat_at: AwareDatetime | None = None
    created_at: AwareDatetime
    started_at: AwareDatetime | None = None
    completed_at: AwareDatetime | None = None
    checkpoint_at: AwareDatetime | None = None
    checkpoint_ref: str | None = None


class RunEventRecord(ProjectCtlModel):
    id: int
    run_id: str
    created_at: AwareDatetime
    event_type: str
    payload: dict = Field(default_factory=dict)
