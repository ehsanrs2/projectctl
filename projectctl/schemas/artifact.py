from typing import Literal

from pydantic import AwareDatetime, Field

from projectctl.core.enums import Ownership
from projectctl.schemas.base import ProjectCtlModel
from projectctl.schemas.config import RepoRelativePath


class ArtifactSource(ProjectCtlModel):
    path: RepoRelativePath
    digest: str | None = None


class ArtifactMetadata(ProjectCtlModel):
    schema_kind: Literal["projectctl.artifact_metadata"] = "projectctl.artifact_metadata"
    schema_version: Literal[1] = 1
    artifact_id: str
    ownership: Ownership
    generated_at: AwareDatetime | None = None
    generator: str | None = None
    generator_version: str | None = None
    git_commit: str | None = None
    source_digest: str | None = None
    sources: list[ArtifactSource] = Field(default_factory=list)
