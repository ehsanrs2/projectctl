from typing import Protocol


class SchemaMigrator(Protocol):
    def can_migrate(self, schema_kind: str, source_version: int, target_version: int) -> bool: ...
