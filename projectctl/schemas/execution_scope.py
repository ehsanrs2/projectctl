from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from projectctl.schemas.base import ProjectCtlModel
from projectctl.schemas.execution_input import ExecutionPathScope


class ExecutionTaskScope(ProjectCtlModel):
    """Human-managed task input, write, and resource authority."""

    task_id: str = Field(min_length=1)
    inputs: list[ExecutionPathScope] = Field(min_length=1)
    writes: list[ExecutionPathScope] = Field(min_length=1)
    resources: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_scope(self):
        for label, scopes in (("input", self.inputs), ("write", self.writes)):
            keys = [(item.path, item.kind) for item in scopes]
            if len(keys) != len(set(keys)):
                raise ValueError(f"Execution {label} scopes must be unique.")
        if any(not resource for resource in self.resources):
            raise ValueError("Execution resource keys must be non-empty.")
        if len(self.resources) != len(set(self.resources)):
            raise ValueError("Execution resource keys must be unique.")
        return self


class ExecutionScopeCatalog(ProjectCtlModel):
    """Sole canonical human-managed execution scope catalog."""

    schema_kind: Literal["projectctl.execution_scope_catalog"] = (
        "projectctl.execution_scope_catalog"
    )
    schema_version: Literal[1] = 1
    tasks: dict[str, ExecutionTaskScope] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_task_keys(self):
        for key, scope in self.tasks.items():
            if key != scope.task_id:
                raise ValueError(
                    f"Execution scope key {key!r} does not match task_id "
                    f"{scope.task_id!r}."
                )
        return self
