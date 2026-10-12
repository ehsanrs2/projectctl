from __future__ import annotations

from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, StringConstraints

from projectctl.schemas.base import ProjectCtlModel
from projectctl.schemas.config import RepoRelativePath
from projectctl.schemas.parallel import ParallelTaskScope
from projectctl.schemas.execution_scope import ExecutionTaskScope


class ContextScopeReviewV1(ProjectCtlModel):
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
    warnings: list[str] = Field(default_factory=list)


class ContextScopeAdoptionRequestV1(ProjectCtlModel):
    schema_kind: Literal["projectctl.context_scope_adoption_request"] = (
        "projectctl.context_scope_adoption_request"
    )
    schema_version: Literal[1] = 1
    adoption_id: str = Field(min_length=1)
    requested_at: AwareDatetime
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
    proposed_catalog_digest: str = Field(min_length=1)
    proposed_scope_digest: str = Field(min_length=1)


class ContextScopeAdoptionReceiptV1(ProjectCtlModel):
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
    request_digest: str = Field(min_length=1)
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



class ContextScopeReview(ContextScopeReviewV1):
    """New canonical scope review; v1 review identity remains audit-only."""

    schema_version: Literal[2] = 2
    catalog_path: Literal["projectctl.scope.yaml"] = "projectctl.scope.yaml"
    proposed_scope: ExecutionTaskScope
    # Scope review is byte-bound authority: global ProjectCtlModel's
    # str_strip_whitespace=True would silently remove the final YAML newline,
    # breaking exact proposed-catalog validation and the approval digest.
    proposed_catalog_yaml: Annotated[
        str, StringConstraints(strip_whitespace=False)
    ] = Field(min_length=1)
    catalog_before_yaml: Annotated[
        str, StringConstraints(strip_whitespace=False)
    ] | None = None


class ContextScopeAdoptionRequest(ContextScopeAdoptionRequestV1):
    """New canonical approval request; no v1 approval can change this policy."""

    schema_version: Literal[2] = 2
    catalog_path: Literal["projectctl.scope.yaml"] = "projectctl.scope.yaml"


class ContextScopeAdoptionReceipt(ContextScopeAdoptionReceiptV1):
    """Durable applied receipt for canonical scope authority."""

    schema_version: Literal[2] = 2
    catalog_path: Literal["projectctl.scope.yaml"] = "projectctl.scope.yaml"
    adopted_scope: ExecutionTaskScope


def _parse_versioned(raw: object, v1, v2, label: str):
    if not isinstance(raw, dict):
        raise ValueError(f"{label} must be an object.")
    version = raw.get("schema_version", 1)
    if version == 1:
        return v1.model_validate(raw)
    if version == 2:
        return v2.model_validate(raw)
    raise ValueError(f"Unsupported {label} version: {version!r}")


def parse_context_scope_review(raw: object) -> ContextScopeReview | ContextScopeReviewV1:
    return _parse_versioned(raw, ContextScopeReviewV1, ContextScopeReview, "scope review")


def parse_context_scope_adoption_request(
    raw: object,
) -> ContextScopeAdoptionRequest | ContextScopeAdoptionRequestV1:
    return _parse_versioned(
        raw, ContextScopeAdoptionRequestV1, ContextScopeAdoptionRequest,
        "scope adoption request",
    )


def parse_context_scope_adoption_receipt(
    raw: object,
) -> ContextScopeAdoptionReceipt | ContextScopeAdoptionReceiptV1:
    return _parse_versioned(
        raw, ContextScopeAdoptionReceiptV1, ContextScopeAdoptionReceipt,
        "scope adoption receipt",
    )
