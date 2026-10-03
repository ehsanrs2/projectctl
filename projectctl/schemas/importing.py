from pydantic import AwareDatetime, Field

from projectctl.core.enums import ImportAction
from projectctl.schemas.base import ProjectCtlModel


class ImportItem(ProjectCtlModel):
    source_id: str
    target_id: str | None = None
    action: ImportAction
    reason: str | None = None


class ImportPlan(ProjectCtlModel):
    source_type: str
    source_path: str
    source_digest: str
    context_digest: str | None = None
    milestone: str | None = None
    items: list[ImportItem] = Field(default_factory=list)


class ImportResult(ProjectCtlModel):
    source_type: str
    source_path: str
    source_digest: str
    context_digest: str | None = None
    milestone: str | None = None
    applied_at: AwareDatetime
    items: list[ImportItem] = Field(default_factory=list)
