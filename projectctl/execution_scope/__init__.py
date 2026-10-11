"""Human-managed execution scope authority and legacy compatibility."""

from projectctl.execution_scope.catalog import (
    EXECUTION_SCOPE_PATH,
    LEGACY_PARALLEL_SCOPE_PATH,
    ResolvedExecutionScopeCatalog,
    load_execution_scope_catalog,
    parse_execution_scope_catalog_bytes,
    resolve_execution_scope_catalog,
    task_execution_scope,
)

__all__ = [
    "EXECUTION_SCOPE_PATH",
    "LEGACY_PARALLEL_SCOPE_PATH",
    "ResolvedExecutionScopeCatalog",
    "load_execution_scope_catalog",
    "parse_execution_scope_catalog_bytes",
    "resolve_execution_scope_catalog",
    "task_execution_scope",
]
