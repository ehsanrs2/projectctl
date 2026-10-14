"""B3a3 experimental ProjectCTL project-state v2->v3 migration rehearsal.

ONLY caller-owned SQLite connections/transactions on test or disposable DBs.
NOT registered with initialize_project_state_db, projectctl migrate, RunStore,
verification writers, export or schema-publication APIs. Never call this
against a real ProjectCTL project database.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from projectctl import __version__
from projectctl.storage.sqlite import APPLICATION_ID, PROJECT_STATE_DB_VERSION

SOURCE_VERSION = 2
CANDIDATE_VERSION = 3
MIGRATION_NAME = "m6-verification-as-of-seal-v1"
_REQUIRED_V2_TABLES = frozenset({
    "schema_migrations", "project_metadata", "task_import_bindings",
    "runs", "run_events",
})
_CANDIDATE_STATEMENTS = (
    """CREATE TABLE trace_seals (
        run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE RESTRICT,
        seal_sequence INTEGER NOT NULL CHECK(seal_sequence > 0),
        event_prefix_id INTEGER NOT NULL REFERENCES run_events(id) ON DELETE RESTRICT,
        seal_json TEXT NOT NULL,
        seal_sha256 TEXT NOT NULL CHECK(length(seal_sha256) = 64),
        PRIMARY KEY(run_id, seal_sequence),
        UNIQUE(run_id, event_prefix_id)
    )""",
    """CREATE TRIGGER trace_seals_no_update
       BEFORE UPDATE ON trace_seals BEGIN
           SELECT RAISE(ABORT, 'immutable_seal');
       END""",
    """CREATE TRIGGER trace_seals_no_delete
       BEFORE DELETE ON trace_seals BEGIN
           SELECT RAISE(ABORT, 'immutable_seal');
       END""",
)


class SealMigrationRefused(ValueError):
    """Typed laboratory refusal without leaking database paths or content."""


def _run_statement(conn: sqlite3.Connection, statement: str, params=()):
    """Single statements, never executescript (which can implicitly commit)."""
    return conn.execute(statement, params)


def rehearse_v2_v3_in_open_transaction(
    conn: sqlite3.Connection,
    *,
    applied_at: datetime,
) -> None:
    """Apply candidate DDL *inside* an existing caller-managed transaction.

    Does not BEGIN, COMMIT, ROLLBACK, connect to a file, create a backup,
    or enable any production migration. On any failure caller MUST rollback.
    """
    if not isinstance(conn, sqlite3.Connection) or not conn.in_transaction:
        raise SealMigrationRefused("no_existing_transaction")
    if PROJECT_STATE_DB_VERSION != SOURCE_VERSION:
        raise SealMigrationRefused("unsupported_runtime_version")
    if not isinstance(applied_at, datetime) or (
        applied_at.tzinfo is None or applied_at.utcoffset() is None
    ):
        raise SealMigrationRefused("invalid_migration_timestamp")
    application_id = conn.execute("PRAGMA application_id").fetchone()[0]
    current_version = conn.execute("PRAGMA user_version").fetchone()[0]
    if application_id != APPLICATION_ID or current_version != SOURCE_VERSION:
        raise SealMigrationRefused("invalid_source_database")
    if conn.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
        raise SealMigrationRefused("foreign_keys_disabled")
    present = {
        row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    if not _REQUIRED_V2_TABLES.issubset(present) or "trace_seals" in present:
        raise SealMigrationRefused("unsupported_source_schema")
    recorded = {
        row[0] for row in conn.execute("SELECT version FROM schema_migrations")
    }
    if 1 not in recorded or 2 not in recorded or 3 in recorded:
        raise SealMigrationRefused("migration_history_inconsistent")
    # A pre-existing object under either immutable-trigger name indicates
    # a conflicting or partially precreated schema. Reject before any DDL.
    trigger_names = {
        row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger'"
        )
    }
    if {"trace_seals_no_update", "trace_seals_no_delete"} & trigger_names:
        raise SealMigrationRefused("conflicting_schema_object")

    for statement in _CANDIDATE_STATEMENTS:
        _run_statement(conn, statement)
    applied = applied_at.astimezone(timezone.utc).isoformat()
    _run_statement(
        conn,
        "INSERT INTO schema_migrations("
        "version, name, applied_at, projectctl_version"
        ") VALUES (3, ?, ?, ?)",
        (MIGRATION_NAME, applied, __version__),
    )
    _run_statement(conn, "PRAGMA user_version = 3")
