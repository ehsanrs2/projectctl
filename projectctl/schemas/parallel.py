from __future__ import annotations

from typing import Literal

from pydantic import AwareDatetime, Field, model_validator

from projectctl.schemas.base import ProjectCtlModel
from projectctl.schemas.config import RepoRelativePath


ParallelPathKind = Literal["exact", "tree"]


class ParallelPathScope(ProjectCtlModel):
    path: RepoRelativePath
    kind: ParallelPathKind = "exact"


class ParallelTaskScope(ProjectCtlModel):
    task_id: str = Field(min_length=1)
    inputs: list[ParallelPathScope] = Field(min_length=1)
    writes: list[ParallelPathScope] = Field(min_length=1)
    resources: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_scope(self):
        input_keys = [(item.path, item.kind) for item in self.inputs]
        write_keys = [(item.path, item.kind) for item in self.writes]
        if len(input_keys) != len(set(input_keys)):
            raise ValueError("Parallel input scopes must be unique.")
        if len(write_keys) != len(set(write_keys)):
            raise ValueError("Parallel write scopes must be unique.")
        resources = list(self.resources)
        if any(not item for item in resources):
            raise ValueError("Parallel resource keys must be non-empty.")
        if len(resources) != len(set(resources)):
            raise ValueError("Parallel resource keys must be unique.")
        return self


class ParallelScopeCatalog(ProjectCtlModel):
    schema_kind: Literal["projectctl.parallel_scope_catalog"] = (
        "projectctl.parallel_scope_catalog"
    )
    schema_version: Literal[1] = 1
    tasks: dict[str, ParallelTaskScope] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_task_keys(self):
        for task_id, scope in self.tasks.items():
            if task_id != scope.task_id:
                raise ValueError(
                    f"Parallel scope key {task_id!r} does not match task_id "
                    f"{scope.task_id!r}."
                )
        return self


class ParallelInputEvidence(ProjectCtlModel):
    scope: ParallelPathScope
    digest: str = Field(min_length=1)


class ParallelPlan(ProjectCtlModel):
    schema_kind: Literal["projectctl.parallel_plan"] = "projectctl.parallel_plan"
    schema_version: Literal[1] = 1
    plan_id: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    integration_target_ref: str = Field(min_length=1)
    base_commit: str = Field(min_length=7)
    project_state_digest: str = Field(min_length=1)
    scoped_task_digest: str = Field(min_length=1)
    scoped_task_ids: list[str] = Field(min_length=1)
    scope_digest: str = Field(min_length=1)
    inputs: list[ParallelInputEvidence] = Field(min_length=1)
    writes: list[ParallelPathScope] = Field(min_length=1)
    resources: list[str] = Field(default_factory=list)
    created_at: AwareDatetime


class ParallelConflict(ProjectCtlModel):
    reason: Literal[
        "same_task",
        "project_mismatch",
        "project_state_mismatch",
        "task_dependency",
        "write_write_overlap",
        "write_input_overlap",
        "resource_overlap",
        "target_base_mismatch",
    ]
    detail: str = Field(min_length=1)


class ParallelSafetyDecision(ProjectCtlModel):
    schema_kind: Literal["projectctl.parallel_safety_decision"] = (
        "projectctl.parallel_safety_decision"
    )
    schema_version: Literal[1] = 1
    decision_id: str = Field(min_length=1)
    evaluated_at: AwareDatetime
    left_plan_digest: str = Field(min_length=1)
    right_plan_digest: str = Field(min_length=1)
    independent: bool
    shared_target: bool
    shared_base: bool
    integration_requires_reverification: bool
    conflicts: list[ParallelConflict] = Field(default_factory=list)
