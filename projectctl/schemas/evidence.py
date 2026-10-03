from typing import Literal

from pydantic import AwareDatetime, Field

from projectctl.schemas.base import ProjectCtlModel
from projectctl.schemas.config import RepoRelativePath


class EvidenceManifest(ProjectCtlModel):
    schema_kind: Literal["projectctl.evidence_manifest"] = "projectctl.evidence_manifest"
    schema_version: Literal[1] = 1
    run_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    base_commit: str = Field(min_length=7)
    candidate_commit: str = Field(min_length=7)
    diff_digest: str = Field(min_length=1)
    worker_result_digest: str = Field(min_length=1)
    verification_manifest_digest: str = Field(min_length=1)
    changed_paths: list[RepoRelativePath] = Field(default_factory=list)
    overall_pass: bool
    generated_at: AwareDatetime
