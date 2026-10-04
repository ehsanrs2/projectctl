from typing import Literal

from pydantic import AwareDatetime, Field

from projectctl.schemas.base import ProjectCtlModel


class TaskClaimRequest(ProjectCtlModel):
    schema_kind: Literal["projectctl.task_claim_request"] = "projectctl.task_claim_request"
    schema_version: Literal[1] = 1

    task_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    actor: str = Field(min_length=1)
    base_commit: str = Field(min_length=7)
    integration_target_ref: str = Field(min_length=1)
    claim_token: str = Field(min_length=16)
    requested_at: AwareDatetime


class TaskClaim(ProjectCtlModel):
    schema_kind: Literal["projectctl.task_claim"] = "projectctl.task_claim"
    schema_version: Literal[1] = 1

    provider: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    actor: str = Field(min_length=1)
    base_commit: str = Field(min_length=7)
    integration_target_ref: str = Field(min_length=1)
    claim_token: str = Field(min_length=16)
    request_digest: str = Field(min_length=1)

    acquired: bool
    observed_at: AwareDatetime
    reason: str | None = None

    repository: str | None = None
    ownership_ref: str | None = None
    ownership_sha: str | None = None
