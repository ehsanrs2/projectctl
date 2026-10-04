from typing import Literal

from pydantic import Field

from projectctl.core.enums import CapabilityState
from projectctl.schemas.base import ProjectCtlModel


class TaskAuthorityCapabilities(ProjectCtlModel):
    schema_kind: Literal["projectctl.task_authority_capabilities"] = (
        "projectctl.task_authority_capabilities"
    )
    schema_version: Literal[1] = 1

    provider: str
    read: CapabilityState
    claim: CapabilityState
    release: CapabilityState
    block_for_decision: CapabilityState
    complete: CapabilityState
    notes: list[str] = Field(default_factory=list)
