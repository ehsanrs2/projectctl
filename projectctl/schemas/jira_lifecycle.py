from __future__ import annotations

from typing import Literal

from pydantic import AwareDatetime, Field, model_validator

from projectctl.schemas.base import ProjectCtlModel
from projectctl.schemas.config import RepoRelativePath


class JiraLifecycleMarker(ProjectCtlModel):
    schema_kind: Literal["projectctl.jira_lifecycle_marker"] = (
        "projectctl.jira_lifecycle_marker"
    )
    schema_version: Literal[1] = 1

    task_id: str = Field(min_length=1)
    issue_id: str = Field(min_length=1)
    state: Literal["completion_pending", "completed", "needs_decision"]
    generation: int = Field(ge=1)
    run_id: str | None = Field(default=None, min_length=1)
    evidence_path: RepoRelativePath | None = None
    evidence_digest: str | None = Field(default=None, min_length=1)
    updated_at: AwareDatetime

    @model_validator(mode="after")
    def validate_completion_binding(self):
        if self.state in {"completion_pending", "completed"}:
            if not self.run_id or not self.evidence_path or not self.evidence_digest:
                raise ValueError(
                    "Jira completion markers require run_id and durable evidence binding."
                )
        return self
