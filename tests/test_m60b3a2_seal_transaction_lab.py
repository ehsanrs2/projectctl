"""M6.0 B3a2 isolated SQLite transaction *lab*, not ProjectCTL migration tests."""
from __future__ import annotations

import hashlib
import json
import sqlite3

import pytest

from projectctl.storage.sqlite import PROJECT_STATE_DB_VERSION
from projectctl.trace.seal_contract import (
    VerificationAsOfSealV1,
    parse_private_seal_json_bytes,
    private_seal_sha256,
)
from projectctl.trace.seal_transaction_lab import (
    EXPERIMENTAL_TRACE_SEALS_DDL,
    SealTransactionRefused,
    insert_verification_seal_in_open_transaction,
    selected_run_projection_sha256,
)


def _manifest(status: str) -> str:
    # Deliberately only a test double for persisted manifest JSON; full
    # RunManifest model + semantic digest proof are outside this SQL lab.
    return json.dumps(
        {"schema_version": 2, "run_id": "run-1", "task_id": "task-1",
         "status": status},
        sort_keys=True, separators=(",", ":"),
    )


def _db():
    connection = sqlite3.connect(":memory:", isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.executescript("""
        PRAGMA foreign_keys=ON;
        CREATE TABLE runs(
            run_id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL,
            status TEXT NOT NULL,
            terminal_reason TEXT,
            execution_plan_digest TEXT,
            base_commit TEXT,
            candidate_commit TEXT,
            created_at TEXT,
            completed_at TEXT,
            manifest_json TEXT NOT NULL
        );
        CREATE TABLE run_events(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL REFERENCES runs(run_id),
            created_at TEXT NOT NULL,
            event_type TEXT NOT NULL,
            payload_json TEXT NOT NULL
        );
    """ + EXPERIMENTAL_TRACE_SEALS_DDL)
    connection.execute(
        "INSERT INTO runs("
        "run_id,task_id,status,terminal_reason,execution_plan_digest,"
        "base_commit,candidate_commit,created_at,completed_at,manifest_json"
        ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("run-1", "task-1", "verifying", None, "e" * 64,
         "deadbeef", None, "2026-10-14T06:00:00+00:00", None,
         _manifest("verifying")),
    )
    connection.execute(
        "INSERT INTO run_events(run_id,created_at,event_type,payload_json)"
        " VALUES(?,?,?,?)",
        ("run-1", "2026-10-14T06:00:00+00:00", "run.created", "{}"),
    )
    assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert connection.execute("PRAGMA user_version").fetchone()[0] == 0
    return connection


def _begin_transition(connection: sqlite3.Connection):
    connection.execute("BEGIN IMMEDIATE")
    connection.execute(
        "UPDATE runs SET status=?, candidate_commit=?, completed_at=?,"
        " manifest_json=? WHERE run_id=?",
        ("ready_to_integrate", "abc123",
         "2026-10-14T06:01:00+00:00", _manifest("ready_to_integrate"),
         "run-1"),
    )
    cursor = connection.execute(
        "INSERT INTO run_events(run_id,created_at,event_type,payload_json)"
        " VALUES (?,?,?,?)",
        ("run-1", "2026-10-14T06:01:00+00:00",
         "run.transition", '{"from":"verifying","to":"ready_to_integrate"}'),
    )
    return cursor.lastrowid


def _seal(connection, event_id: int, **overrides):
    row = connection.execute(
        "SELECT run_id,task_id,status,terminal_reason,execution_plan_digest,"
        "base_commit,candidate_commit,created_at,completed_at,manifest_json"
        " FROM runs WHERE run_id='run-1'"
    ).fetchone()
    payload = {
        "schema_kind": "projectctl.verification_as_of_seal",
        "schema_version": 1,
        "seal_protocol_version": 1,
        "artifact_digest_algorithm": "sha256",
        "project_id": "projectctl",
        "run_id": "run-1",
        "task_id": "task-1",
        "seal_sequence": 1,
        "observed_status": "ready_to_integrate",
        "event_prefix_id": event_id,
        "run_manifest_schema_version": 2,
        "run_manifest_raw_sha256": hashlib.sha256(
            row["manifest_json"].encode()
        ).hexdigest(),
        "run_record_projection_sha256": selected_run_projection_sha256(row),
        "verification_manifest_raw_sha256": "a" * 64,
        "evidence_manifest_raw_sha256": "b" * 64,
    }
    return VerificationAsOfSealV1.model_validate({**payload, **overrides})


def _state(connection):
    return (
        connection.execute(
            "SELECT status FROM runs WHERE run_id='run-1'"
        ).fetchone()[0],
        connection.execute("SELECT count(*) FROM run_events").fetchone()[0],
        connection.execute("SELECT count(*) FROM trace_seals").fetchone()[0],
    )


def test_one_sqlite_commit_contains_status_transition_event_and_seal():
    conn = _db()
    try:
        event = _begin_transition(conn)
        seal = _seal(conn, event)
        insert_verification_seal_in_open_transaction(
            conn, seal, expected_project_id="projectctl"
        )
        assert conn.in_transaction
        assert _state(conn) == ("ready_to_integrate", 2, 1)
        conn.commit()
        assert not conn.in_transaction
        assert _state(conn) == ("ready_to_integrate", 2, 1)
        record = conn.execute(
            "SELECT seal_json,seal_sha256,event_prefix_id FROM trace_seals"
        ).fetchone()
        assert parse_private_seal_json_bytes(record["seal_json"].encode()) == seal
        assert record["seal_sha256"] == private_seal_sha256(seal)
        assert record["event_prefix_id"] == event
    finally:
        conn.close()


def test_caller_rollback_reverses_all_three_operations():
    conn = _db()
    try:
        event = _begin_transition(conn)
        insert_verification_seal_in_open_transaction(
            conn, _seal(conn, event), expected_project_id="projectctl"
        )
        conn.rollback()
        assert _state(conn) == ("verifying", 1, 0)
    finally:
        conn.close()


def test_seal_insert_trigger_failure_allows_atomic_caller_rollback():
    conn = _db()
    try:
        conn.execute(
            "CREATE TRIGGER test_seal_insert_fail BEFORE INSERT ON trace_seals "
            "BEGIN SELECT RAISE(ABORT, 'simulated_failure'); END"
        )
        event = _begin_transition(conn)
        with pytest.raises(sqlite3.IntegrityError):
            insert_verification_seal_in_open_transaction(
                conn, _seal(conn, event), expected_project_id="projectctl"
            )
        conn.rollback()
        assert _state(conn) == ("verifying", 1, 0)
    finally:
        conn.close()


@pytest.mark.parametrize(("field", "bad"), [
    ("task_id", "task-other"),
    ("run_id", "run-other"),
    ("run_manifest_raw_sha256", "f" * 64),
    ("run_record_projection_sha256", "f" * 64),
    ("event_prefix_id", 999),
    ("seal_sequence", 2),
    ("event_prefix_id", 1),
])
def test_incorrect_row_event_identity_digests_or_epoch_fail_closed(field, bad):
    conn = _db()
    try:
        event = _begin_transition(conn)
        with pytest.raises(SealTransactionRefused):
            insert_verification_seal_in_open_transaction(
                conn, _seal(conn, event, **{field: bad}),
                expected_project_id="projectctl",
            )
        conn.rollback()
        assert _state(conn) == ("verifying", 1, 0)
    finally:
        conn.close()


def test_project_identity_requires_explicit_trusted_caller_match():
    conn = _db()
    try:
        event = _begin_transition(conn)
        with pytest.raises(SealTransactionRefused, match="identity_mismatch"):
            insert_verification_seal_in_open_transaction(
                conn, _seal(conn, event), expected_project_id="other-project"
            )
        conn.rollback()
        assert _state(conn) == ("verifying", 1, 0)
    finally:
        conn.close()


def test_stale_event_boundary_with_later_same_run_event_is_rejected():
    conn = _db()
    try:
        event = _begin_transition(conn)
        conn.execute(
            "INSERT INTO run_events(run_id,created_at,event_type,payload_json)"
            " VALUES (?,?,?,?)",
            ("run-1", "2026-10-14T06:01:00+00:00",
             "verification.passed", "{}"),
        )
        with pytest.raises(SealTransactionRefused, match="stale_event_boundary"):
            insert_verification_seal_in_open_transaction(
                conn, _seal(conn, event), expected_project_id="projectctl"
            )
        conn.rollback()
        assert _state(conn) == ("verifying", 1, 0)
    finally:
        conn.close()


def test_no_implicit_transaction_schema_creation_or_commit():
    conn = _db()
    try:
        assert PROJECT_STATE_DB_VERSION == 2
        # A structurally valid seal alone is never permitted to open
        # its own transaction. The helper is a no-op on the DB.
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "UPDATE runs SET status=?,manifest_json=? WHERE run_id='run-1'",
            ("ready_to_integrate", _manifest("ready_to_integrate")),
        )
        sample = _seal(conn, 1)
        conn.rollback()
        with pytest.raises(SealTransactionRefused, match="no_active_writer_transaction"):
            insert_verification_seal_in_open_transaction(
                conn, sample, expected_project_id="projectctl"
            )
        assert _state(conn) == ("verifying", 1, 0)
    finally:
        conn.close()


def test_immutable_rows_reject_update_delete_and_cannot_be_replayed():
    conn = _db()
    try:
        event = _begin_transition(conn)
        seal = _seal(conn, event)
        insert_verification_seal_in_open_transaction(
            conn, seal, expected_project_id="projectctl"
        )
        conn.commit()
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "UPDATE trace_seals SET seal_sha256=?",
                ("f" * 64,),
            )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("DELETE FROM trace_seals")
        conn.execute("BEGIN IMMEDIATE")
        with pytest.raises(SealTransactionRefused, match="duplicate_pilot_seal"):
            insert_verification_seal_in_open_transaction(
                conn, seal, expected_project_id="projectctl"
            )
        conn.rollback()
        assert _state(conn) == ("ready_to_integrate", 2, 1)
    finally:
        conn.close()


def test_no_seal_can_be_inserted_from_verifying_run_status():
    conn = _db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        event = conn.execute(
            "INSERT INTO run_events(run_id,created_at,event_type,payload_json)"
            " VALUES (?,?,?,?)",
            ("run-1", "2026-10-14T06:01:00+00:00",
             "run.transition", '{"to":"ready_to_integrate"}'),
        ).lastrowid
        with pytest.raises(SealTransactionRefused, match="identity_or_status_mismatch"):
            insert_verification_seal_in_open_transaction(
                conn, _seal(conn, event), expected_project_id="projectctl"
            )
        conn.rollback()
        assert _state(conn) == ("verifying", 1, 0)
    finally:
        conn.close()


def test_no_writes_on_any_authoritative_project_db(tmp_path):
    # Regression boundary: all actual transaction mutations in this
    # module's tests are limited to sqlite3.connect(':memory:').
    assert not (tmp_path / ".projectctl").exists()
    conn = _db()
    try:
        assert conn.execute("PRAGMA database_list").fetchone()["file"] == ""
        assert not (tmp_path / ".projectctl").exists()
    finally:
        conn.close()
