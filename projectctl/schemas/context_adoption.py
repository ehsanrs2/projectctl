from __future__ import annotations

from typing import Literal

from pydantic import AwareDatetime, Field

from projectctl.schemas.base import ProjectCtlModel
from projectctl.schemas.config import RepoRelativePath
from projectctl.schemas.parallel import ParallelTaskScope


class ContextScopeReview(ProjectCtlModel):
    schema_kind: Literal["projectctl.context_scope_review"] = (
        "projectctl.context_scope_review"
    )
    schema_version: Literal[1] = 1
    review_id: str = Field(min_length=1)
    created_at: AwareDatetime
    project_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    integration_target_ref: str = Field(min_length=1)
    base_commit: str = Field(min_length=7)
    task_digest: str = Field(min_length=1)
    discovery_digest: str = Field(min_length=1)
    suggestion_id: str = Field(min_length=1)
    suggestion_digest: str = Field(min_length=1)
    suggestion_artifact: RepoRelativePath
    catalog_path: RepoRelativePath = "projectctl.parallel.yaml"
    catalog_before_present: bool
    catalog_before_digest: str = Field(min_length=1)
    catalog_before_yaml: str | None = None
    scope_before_digest: str | None = None
    proposed_scope: ParallelTaskScope
    proposed_catalog_digest: str = Field(min_length=1)
    proposed_catalog_yaml: str = Field(min_length=1)
    selected_suggestion_inputs: list[RepoRelativePath] = Field(default_factory=list)
    selected_suggestion_writes: list[RepoRelativePath] = Field(default_factory=list)
    added_inputs: list[RepoRelativePath] = Field(default_factory=list)
    added_writes: list[RepoRelativePath] = Field(default_factory=list)
    added_resources: list[str] = Field(default_factory=list)
    mutation_mode: Literal["additive"] = "additive"
    requires_digest_approval: Literal[True] = True


class ContextScopeAdoptionReceipt(ProjectCtlModel):
    schema_kind: Literal["projectctl.context_scope_adoption_receipt"] = (
        "projectctl.context_scope_adoption_receipt"
    )
    schema_version: Literal[1] = 1
    adoption_id: str = Field(min_length=1)
    adopted_at: AwareDatetime
    actor: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    review_id: str = Field(min_length=1)
    review_digest: str = Field(min_length=1)
    approval_digest: str = Field(min_length=1)
    approval_method: Literal["cli_review_digest"] = "cli_review_digest"
    base_commit: str = Field(min_length=7)
    task_digest: str = Field(min_length=1)
    catalog_path: RepoRelativePath
    catalog_before_digest: str = Field(min_length=1)
    catalog_after_digest: str = Field(min_length=1)
    scope_before_digest: str | None = None
    scope_after_digest: str = Field(min_length=1)
    adopted_scope: ParallelTaskScope
    applied: Literal[True] = True
