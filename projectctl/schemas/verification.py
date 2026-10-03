from typing import Literal

from pydantic import AwareDatetime, Field

from projectctl.core.enums import VerificationCheckStatus
from projectctl.schemas.base import ProjectCtlModel
from projectctl.schemas.config import RepoRelativePath


class VerificationCommand(ProjectCtlModel):
    id: str = Field(min_length=1)
    argv: list[str] = Field(min_length=1)
    cwd: RepoRelativePath | None = None
    timeout_seconds: int = Field(default=600, ge=1)
    required: bool = True


class VerificationProfile(ProjectCtlModel):
    id: str = Field(min_length=1)
    commands: list[VerificationCommand] = Field(default_factory=list)


class VerificationCheckResult(ProjectCtlModel):
    id: str = Field(min_length=1)
    argv: list[str] = Field(min_length=1)
    status: VerificationCheckStatus
    exit_code: int | None = None
    duration_ms: int = Field(ge=0)
    stdout_digest: str | None = None
    stderr_digest: str | None = None


class VerificationManifest(ProjectCtlModel):
    schema_kind: Literal["projectctl.verification_manifest"] = "projectctl.verification_manifest"
    schema_version: Literal[1] = 1
    run_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    workspace_state_digest: str = Field(min_length=1)
    profile: str = Field(min_length=1)
    started_at: AwareDatetime
    completed_at: AwareDatetime
    checks: list[VerificationCheckResult] = Field(default_factory=list)
    overall_pass: bool
