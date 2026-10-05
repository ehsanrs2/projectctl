from typing import Literal

from pydantic import AwareDatetime, Field

from projectctl.schemas.base import ProjectCtlModel
from projectctl.schemas.config import RepoRelativePath


class TaskDeliveryPolicy(ProjectCtlModel):
    schema_kind: Literal["projectctl.task_delivery_policy"] = "projectctl.task_delivery_policy"
    schema_version: Literal[1] = 1

    provider: str = Field(min_length=1)
    publication_required: bool = False
    remote_name: str | None = None
    release_claim_after_completion: bool = False
    release_claim_after_decision_block: bool = False


class PublicationRequest(ProjectCtlModel):
    schema_kind: Literal["projectctl.publication_request"] = "projectctl.publication_request"
    schema_version: Literal[1] = 1

    run_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    provider: str = Field(min_length=1)
    repository: str | None = None
    remote_name: str = Field(min_length=1)
    target_ref: str = Field(min_length=1)
    base_commit: str = Field(min_length=7)
    candidate_commit: str = Field(min_length=7)
    evidence_manifest: RepoRelativePath
    evidence_digest: str = Field(min_length=1)
    requested_at: AwareDatetime


class PublicationManifest(ProjectCtlModel):
    schema_kind: Literal["projectctl.publication_manifest"] = "projectctl.publication_manifest"
    schema_version: Literal[1] = 1

    run_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    provider: str = Field(min_length=1)
    repository: str | None = None
    remote_name: str = Field(min_length=1)
    target_ref: str = Field(min_length=1)
    base_commit: str = Field(min_length=7)
    candidate_commit: str = Field(min_length=7)
    evidence_manifest: RepoRelativePath
    evidence_digest: str = Field(min_length=1)
    request_digest: str = Field(min_length=1)
    remote_before: str | None = None
    remote_after: str | None = None
    published: bool
    observed_at: AwareDatetime
    reason: str | None = None


class CodeDeliveryPolicy(ProjectCtlModel):
    schema_kind: Literal["projectctl.code_delivery_policy"] = "projectctl.code_delivery_policy"
    schema_version: Literal[1] = 1

    mode: Literal["local", "direct_git", "review_required"]
    supported: bool
    publication_required: bool
    completion_evidence: Literal[
        "evidence_manifest",
        "publication_manifest",
        "review_receipt",
    ]
    transport_mode: Literal["local", "git_remote"]
    remote_name: str | None = None
    remote_identity: str | None = None
    notes: list[str] = Field(default_factory=list)
