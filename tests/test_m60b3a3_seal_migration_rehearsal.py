"""B3a3: migration rehearsal against disposable real ProjectCTL v2 DBs only."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from projectctl.core.errors import RunStoreError
from projectctl.storage.runs import RunStore
from projectctl.storage.sqlite import (
    APPLICATION_ID, GLOBAL_STATE_DB_VERSION, PROJECT_STATE_DB_VERSION,
    initialize_project_state_db, inspect_db,
)
from projectctl.trace import seal_migration_lab as lab
from projectctl.trace.seal_migration_lab import (
    SealMigrationRefused, rehearse_v2_v3_in_open_transaction,
)

STAMP = datetime(2026, 10, 14, 8, tzinfo=timezone.utc)


def _existing_v2_db(root: Path) -> Path:
    db = root / ".projectctl" / "state.sqlite"
    initialize_project_state_db(db)
    assert inspect_db(db) == (APPLICATION_ID, 2)
    return db


def _conn(db: Path, *, foreign_keys: bool = True) -> sqlite3.Connection:
    conn = sqlite3.connect(db, isolation_level=None)
    conn.execute(f"PRAGMA foreign_keys={'ON' if foreign_keys else 'OFF'}")
    conn.execute("PRAGMA busy_timeout=1000")
    return conn


def _schema(conn: sqlite3.Connection):
    return conn.execute(
        "SELECT type,name,sql FROM sqlite_master "
        "WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name"
    ).fetchall()


def _versions(conn: sqlite3.Connection):
    return tuple(
        row[0] for row in conn.execute(
            "SELECT version FROM schema_migrations ORDER BY version"
        )
    )


def _state(conn: sqlite3.Connection):
    return conn.execute("PRAGMA user_version").fetchone()[0], _versions(conn), _schema(conn)


def _insert_legacy_run(conn: sqlite3.Connection):
    conn.execute(
        "INSERT INTO runs(run_id,task_id,status,execution_plan_digest,"
        "base_commit,branch_name,worktree_id,worktree_path,worker_provider,"
        "created_at,manifest_json) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        ("run-1", "task-1", "verifying", "e" * 64, "deadbeef",
         "test-branch", "worktree-1", "/tmp/test-fixture",
         "mock-worker", STAMP.isoformat(), '{"fixture":"v2"}'),
    )
    conn.execute(
        "INSERT INTO run_events(run_id,created_at,event_type,payload_json)"
        " VALUES(?,?,?,?)",
        ("run-1", STAMP.isoformat(), "run.created", "{}"),
    )


def test_disposable_real_project_v2_schema_can_be_upgraded_in_one_transaction(tmp_path):
    db = _existing_v2_db(tmp_path)
    conn = _conn(db)
    try:
        _insert_legacy_run(conn)
        before_count = conn.execute("SELECT count(*) FROM runs").fetchone()[0]
        conn.execute("BEGIN IMMEDIATE")
        rehearse_v2_v3_in_open_transaction(conn, applied_at=STAMP)
        assert conn.in_transaction
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 3
        assert _versions(conn) == (1, 2, 3)
        conn.commit()
        assert inspect_db(db) == (APPLICATION_ID, 3)
        assert conn.execute("SELECT count(*) FROM runs").fetchone()[0] == before_count
        assert conn.execute("SELECT count(*) FROM run_events").fetchone()[0] == 1
        assert conn.execute(
            "SELECT name FROM schema_migrations WHERE version=3"
        ).fetchone()[0] == lab.MIGRATION_NAME
        assert conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name='trace_seals'"
        ).fetchone()[0] == "trace_seals"
        # The deployed v2 runtime intentionally cannot treat this candidate
        # as an accepted production v3 project-state database.
        with pytest.raises(RunStoreError):
            RunStore(tmp_path)
    finally:
        conn.close()


def test_caller_rollback_restores_schema_version_and_every_ddl_object(tmp_path):
    db = _existing_v2_db(tmp_path)
    conn = _conn(db)
    try:
        baseline = _state(conn)
        conn.execute("BEGIN IMMEDIATE")
        rehearse_v2_v3_in_open_transaction(conn, applied_at=STAMP)
        assert _state(conn) != baseline
        conn.rollback()
        assert _state(conn) == baseline
        assert inspect_db(db) == (APPLICATION_ID, 2)
    finally:
        conn.close()


@pytest.mark.parametrize("failure_number", [1, 2, 3, 4, 5])
def test_fault_at_each_migration_statement_is_caller_rollback_safe(
    tmp_path, monkeypatch, failure_number
):
    db = _existing_v2_db(tmp_path)
    conn = _conn(db)
    baseline = _state(conn)
    real_execute = lab._run_statement
    count = 0

    def fault_once(connection, statement, params=()):
        nonlocal count
        count += 1
        if count == failure_number:
            raise sqlite3.OperationalError("simulated-fs-or-db-failure")
        return real_execute(connection, statement, params)

    monkeypatch.setattr(lab, "_run_statement", fault_once)
    try:
        conn.execute("BEGIN IMMEDIATE")
        with pytest.raises(sqlite3.OperationalError):
            rehearse_v2_v3_in_open_transaction(conn, applied_at=STAMP)
        conn.rollback()
        assert _state(conn) == baseline
        assert inspect_db(db) == (APPLICATION_ID, 2)
    finally:
        conn.close()


def test_no_implicit_transaction_and_no_schema_changes_on_refusal(tmp_path):
    db = _existing_v2_db(tmp_path)
    conn = _conn(db)
    try:
        baseline = _state(conn)
        with pytest.raises(SealMigrationRefused, match="no_existing_transaction"):
            rehearse_v2_v3_in_open_transaction(conn, applied_at=STAMP)
        assert _state(conn) == baseline
        assert not conn.in_transaction
    finally:
        conn.close()


def test_disabled_foreign_keys_is_rejected_before_creating_tables(tmp_path):
    db = _existing_v2_db(tmp_path)
    conn = _conn(db, foreign_keys=False)
    try:
        baseline = _state(conn)
        conn.execute("BEGIN IMMEDIATE")
        with pytest.raises(SealMigrationRefused, match="foreign_keys_disabled"):
            rehearse_v2_v3_in_open_transaction(conn, applied_at=STAMP)
        conn.rollback()
        assert _state(conn) == baseline
    finally:
        conn.close()


@pytest.mark.parametrize("bad_stamp", [
    None, "2026-10-14", datetime(2026, 10, 14, 8),
])
def test_migration_timestamp_must_be_aware_datetime(tmp_path, bad_stamp):
    db = _existing_v2_db(tmp_path)
    conn = _conn(db)
    try:
        baseline = _state(conn)
        conn.execute("BEGIN IMMEDIATE")
        with pytest.raises(SealMigrationRefused, match="invalid_migration_timestamp"):
            rehearse_v2_v3_in_open_transaction(conn, applied_at=bad_stamp)
        conn.rollback()
        assert _state(conn) == baseline
    finally:
        conn.close()


def test_wrong_application_id_refused_without_creating_seal_objects(tmp_path):
    db = _existing_v2_db(tmp_path)
    conn = _conn(db)
    try:
        conn.execute("PRAGMA application_id = 1234")
        baseline = _state(conn)
        conn.execute("BEGIN IMMEDIATE")
        with pytest.raises(SealMigrationRefused, match="invalid_source_database"):
            rehearse_v2_v3_in_open_transaction(conn, applied_at=STAMP)
        conn.rollback()
        assert _state(conn) == baseline
    finally:
        conn.close()


def test_missing_migration_history_refused_before_ddl(tmp_path):
    db = _existing_v2_db(tmp_path)
    conn = _conn(db)
    try:
        conn.execute("DELETE FROM schema_migrations WHERE version=2")
        baseline = _state(conn)
        conn.execute("BEGIN IMMEDIATE")
        with pytest.raises(SealMigrationRefused, match="migration_history_inconsistent"):
            rehearse_v2_v3_in_open_transaction(conn, applied_at=STAMP)
        conn.rollback()
        assert _state(conn) == baseline
    finally:
        conn.close()


def test_replaying_candidate_upgrade_is_refused(tmp_path):
    db = _existing_v2_db(tmp_path)
    conn = _conn(db)
    try:
        conn.execute("BEGIN IMMEDIATE")
        rehearse_v2_v3_in_open_transaction(conn, applied_at=STAMP)
        conn.commit()
        before = _state(conn)
        conn.execute("BEGIN IMMEDIATE")
        with pytest.raises(SealMigrationRefused, match="invalid_source_database"):
            rehearse_v2_v3_in_open_transaction(conn, applied_at=STAMP)
        conn.rollback()
        assert _state(conn) == before
    finally:
        conn.close()


def test_candidate_seal_table_is_insert_only_for_rehearsal(tmp_path):
    db = _existing_v2_db(tmp_path)
    conn = _conn(db)
    try:
        _insert_legacy_run(conn)
        conn.execute("BEGIN IMMEDIATE")
        rehearse_v2_v3_in_open_transaction(conn, applied_at=STAMP)
        event_id = conn.execute(
            "SELECT id FROM run_events WHERE run_id='run-1'"
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO trace_seals(run_id,seal_sequence,event_prefix_id,"
            "seal_json,seal_sha256) VALUES(?,?,?,?,?)",
            ("run-1", 1, event_id, '{"schema_version":1}', "a" * 64),
        )
        conn.commit()
        with pytest.raises(sqlite3.IntegrityError, match="immutable_seal"):
            conn.execute("UPDATE trace_seals SET seal_sha256=?", ("b" * 64,))
        with pytest.raises(sqlite3.IntegrityError, match="immutable_seal"):
            conn.execute("DELETE FROM trace_seals")
        assert conn.execute("SELECT count(*) FROM trace_seals").fetchone()[0] == 1
    finally:
        conn.close()


def test_rehearsal_is_separate_from_projectctl_runtime_and_global_version(tmp_path):
    db = _existing_v2_db(tmp_path)
    assert PROJECT_STATE_DB_VERSION == 2
    assert GLOBAL_STATE_DB_VERSION == 2
    conn = _conn(db)
    try:
        assert _versions(conn) == (1, 2)
        assert "trace_seals" not in {
            row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        # Merely importing the lab must never mutate the source project.
        assert inspect_db(db) == (APPLICATION_ID, 2)
    finally:
        conn.close()
