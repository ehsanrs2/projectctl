from typing import Literal

from pydantic import Field

from projectctl.schemas.base import ProjectCtlModel


class ExecutionOwnershipPolicy(ProjectCtlModel):
    schema_kind: Literal["projectctl.execution_ownership_policy"] = (
        "projectctl.execution_ownership_policy"
    )
    schema_version: Literal[1] = 1

    task_provider: str = Field(min_length=1)
    strategy: Literal["task_native", "local_lock", "git_ref_lease"]
    scope: Literal["local", "distributed"]
    transport_mode: Literal["local", "git_remote"]
    remote_name: str | None = None
    remote_identity: str | None = None
    notes: list[str] = Field(default_factory=list)
