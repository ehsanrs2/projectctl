from typing import Protocol

from projectctl.schemas.importing import ImportPlan, ImportResult


class TaskImporter(Protocol):
    def preview(self, source: str) -> ImportPlan: ...
    def apply(self, plan: ImportPlan) -> ImportResult: ...
