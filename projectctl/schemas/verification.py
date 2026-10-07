from __future__ import annotations

from typing import Literal

from pydantic import AwareDatetime, Field, model_validator

from projectctl.core.enums import VerificationCheckStatus
from projectctl.schemas.base import ProjectCtlModel
from projectctl.schemas.config import RepoRelativePath


DEFAULT_PROTECTED_PATHS = [
    ".projectctl/**",
    "evidence/**",
    "docs/generated/**",
    "AGENTS.md",
    "**/AGENTS.md",
    "AGENTS.override.md",
    "**/AGENTS.override.md",
    "docs/PROJECT_STATE.yaml",
    "specs/**",
    "docs/decisions/**",
    "projectctl.verification.yaml",
    "projectctl.parallel.yaml",
]
RESERVED_CHECK_IDS = {"diff-policy", "execution-write-scope", "workspace-stability"}


class VerificationCommand(ProjectCtlModel):
    id: str = Field(min_length=1, pattern=r"^[A-Za-z0-9._-]+$")
    argv: list[str] = Field(min_length=1)
    cwd: RepoRelativePath | None = None
    timeout_seconds: int = Field(default=600, ge=1, le=86400)
    required: bool = True


class DiffPolicy(ProjectCtlModel):
    require_changes: bool = True
    protected_paths: list[str] = Field(
        default_factory=lambda: list(DEFAULT_PROTECTED_PATHS)
    )
    allow_symlink_changes: bool = False
    max_changed_paths: int = Field(default=1000, ge=1)


class VerificationProfile(ProjectCtlModel):
    id: str = Field(min_length=1, pattern=r"^[A-Za-z0-9._-]+$")
    commands: list[VerificationCommand] = Field(min_length=1)
    diff_policy: DiffPolicy = Field(default_factory=DiffPolicy)

    @model_validator(mode="after")
    def validate_command_ids(self):
        ids = [command.id for command in self.commands]
        if len(ids) != len(set(ids)):
            raise ValueError("Verification command ids must be unique within a profile.")
        reserved = sorted(set(ids) & RESERVED_CHECK_IDS)
        if reserved:
            raise ValueError(
                "Verification command ids are reserved by ProjectCTL: "
                + ", ".join(reserved)
            )
        return self


class VerificationCatalog(ProjectCtlModel):
    schema_kind: Literal["projectctl.verification_catalog"] = "projectctl.verification_catalog"
    schema_version: Literal[1] = 1
    default_profile: str = Field(default="default", min_length=1)
    profiles: dict[str, VerificationProfile] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_profiles(self):
        if self.default_profile not in self.profiles:
            raise ValueError(
                f"Default verification profile {self.default_profile!r} is not defined."
            )
        for key, profile in self.profiles.items():
            if key != profile.id:
                raise ValueError(
                    f"Verification profile key {key!r} does not match id {profile.id!r}."
                )
        return self


class VerificationCheckResult(ProjectCtlModel):
    id: str = Field(min_length=1)
    argv: list[str] = Field(min_length=1)
    status: VerificationCheckStatus
    exit_code: int | None = None
    duration_ms: int = Field(ge=0)
    stdout_digest: str | None = None
    stderr_digest: str | None = None


class VerificationManifestV1(ProjectCtlModel):
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


class VerificationManifestV2(ProjectCtlModel):
    schema_kind: Literal["projectctl.verification_manifest"] = "projectctl.verification_manifest"
    schema_version: Literal[2] = 2
    run_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    base_commit: str = Field(min_length=7)
    workspace_state_digest: str = Field(min_length=1)
    profile: str = Field(min_length=1)
    profile_digest: str = Field(min_length=1)
    changed_paths: list[RepoRelativePath] = Field(default_factory=list)
    policy_violations: list[str] = Field(default_factory=list)
    started_at: AwareDatetime
    completed_at: AwareDatetime
    checks: list[VerificationCheckResult] = Field(default_factory=list)
    overall_pass: bool


class VerificationManifest(ProjectCtlModel):
    schema_kind: Literal["projectctl.verification_manifest"] = "projectctl.verification_manifest"
    schema_version: Literal[3] = 3
    run_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    base_commit: str = Field(min_length=7)
    execution_input_digest: str | None = None
    workspace_state_digest: str = Field(min_length=1)
    profile: str = Field(min_length=1)
    profile_digest: str = Field(min_length=1)
    changed_paths: list[RepoRelativePath] = Field(default_factory=list)
    policy_violations: list[str] = Field(default_factory=list)
    started_at: AwareDatetime
    completed_at: AwareDatetime
    checks: list[VerificationCheckResult] = Field(default_factory=list)
    overall_pass: bool


def parse_verification_manifest(
    raw: object,
) -> VerificationManifest | VerificationManifestV2 | VerificationManifestV1:
    if not isinstance(raw, dict):
        raise ValueError("Verification manifest must be an object.")
    version = raw.get("schema_version", 1)
    if version == 3:
        return VerificationManifest.model_validate(raw)
    if version == 2:
        return VerificationManifestV2.model_validate(raw)
    if version == 1:
        return VerificationManifestV1.model_validate(raw)
    raise ValueError(f"Unsupported verification manifest schema version: {version}")
