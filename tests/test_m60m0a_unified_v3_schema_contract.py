"""M6.0 M0a: a candidate v2->v3 schema contract, TEST-ONLY.

All DDL is in this test file and executes ONLY on new tmp_path ProjectCTL v2
fixtures. No production migration, initialization, writer or reader is wired.
"""
from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

import pytest

from projectctl import __version__
from projectctl.core.errors import RunStoreError
from projectctl.storage.runs import RunStore
from projectctl.storage.sqlite import (
    APPLICATION_ID,
    GLOBAL_STATE_DB_VERSION,
    PROJECT_STATE_DB_VERSION,
    initialize_project_state_db,
    inspect_db,
)

STAMP = datetime(2026, 10, 14, 12, tzinfo=timezone.utc).isoformat()
MIGRATION_NAME = "candidate-m6-fenced-seal-v3"
# All 12 statements execute separately; never executescript.
# SQLite executescript may commit an already-open transaction.
_V3_SQL = (
    """ALTER TABLE runs ADD COLUMN lease_generation INTEGER NOT NULL DEFAULT 0
       CHECK(typeof(lease_generation)='integer' AND lease_generation >= 0)""",
    """ALTER TABLE runs ADD COLUMN lease_token TEXT
       CHECK(lease_token IS NULL OR
       (typeof(lease_token)='text' AND length(lease_token)=32
        AND lease_token NOT GLOB '*[^0-9a-f]*'))""",
    """CREATE UNIQUE INDEX idx_run_events_run_id_id ON run_events(run_id, id)""",
    """CREATE TABLE trace_seals (
       run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE RESTRICT,
       seal_sequence INTEGER NOT NULL CHECK(seal_sequence = 1),
       event_prefix_id INTEGER NOT NULL,
       seal_protocol_version INTEGER NOT NULL CHECK(seal_protocol_version = 1),
       seal_json TEXT NOT NULL
           CHECK(typeof(seal_json)='text'
                 AND length(CAST(seal_json AS BLOB)) BETWEEN 1 AND 4096),
       seal_sha256 TEXT NOT NULL CHECK(
           typeof(seal_sha256)='text'
           AND length(seal_sha256)=64
           AND seal_sha256 NOT GLOB '*[^0-9a-f]*'
       ),
       PRIMARY KEY (run_id, seal_sequence),
       UNIQUE (run_id, event_prefix_id),
       FOREIGN KEY (run_id, event_prefix_id)
           REFERENCES run_events(run_id, id) ON DELETE RESTRICT
       )""",
    """CREATE TRIGGER trace_seals_valid_anchor BEFORE INSERT ON trace_seals
       BEGIN
           SELECT CASE WHEN NOT EXISTS (
               SELECT 1 FROM run_events
               WHERE run_id=NEW.run_id AND id=NEW.event_prefix_id
                 AND event_type='run.transition'
           ) OR NOT EXISTS (
               SELECT 1 FROM runs
               WHERE run_id=NEW.run_id AND status='ready_to_integrate'
           ) THEN RAISE(ABORT, 'invalid_transition_anchor') END;
       END""",
    """CREATE TRIGGER trace_seals_no_update BEFORE UPDATE ON trace_seals
       BEGIN SELECT RAISE(ABORT, 'immutable_seal'); END""",
    """CREATE TRIGGER trace_seals_no_delete BEFORE DELETE ON trace_seals
       BEGIN SELECT RAISE(ABORT, 'immutable_seal'); END""",
    """CREATE TRIGGER trace_seals_prefix_no_update BEFORE UPDATE ON run_events
       WHEN EXISTS (
           SELECT 1 FROM trace_seals
           WHERE (run_id=OLD.run_id AND OLD.id<=event_prefix_id)
              OR (run_id=NEW.run_id AND NEW.id<=event_prefix_id)
       )
       BEGIN SELECT RAISE(ABORT, 'sealed_event_prefix_immutable'); END""",
    """CREATE TRIGGER trace_seals_prefix_no_delete BEFORE DELETE ON run_events
       WHEN EXISTS (
           SELECT 1 FROM trace_seals
           WHERE run_id=OLD.run_id AND OLD.id<=event_prefix_id
       )
       BEGIN SELECT RAISE(ABORT, 'sealed_event_prefix_immutable'); END""",
    """CREATE TRIGGER trace_seals_prefix_no_backfill BEFORE INSERT ON run_events
       WHEN NEW.id IS NOT NULL AND NEW.id>0 AND EXISTS (
           SELECT 1 FROM trace_seals
           WHERE run_id=NEW.run_id AND NEW.id<=event_prefix_id
       )
       BEGIN SELECT RAISE(ABORT, 'sealed_event_prefix_immutable'); END""",
    """INSERT INTO schema_migrations(version,name,applied_at,projectctl_version)
       VALUES (3, ?, ?, ?)""",
    "PRAGMA user_version = 3",
)


class ContractRefused(ValueError):
    pass


def _db(tmp_path: Path) -> Path:
    path = tmp_path / ".projectctl" / "state.sqlite"
    initialize_project_state_db(path)
    assert inspect_db(path) == (APPLICATION_ID, 2)
    return path


def _conn(path: Path, *, fk: bool = True) -> sqlite3.Connection:
    conn = sqlite3.connect(path, isolation_level=None)
    conn.execute("PRAGMA foreign_keys = " + ("ON" if fk else "OFF"))
    return conn


def _objects(conn: sqlite3.Connection):
    return tuple(conn.execute(
        "SELECT type,name,sql FROM sqlite_master "
        "WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name"
    ).fetchall())


def _state(conn: sqlite3.Connection):
    return (
        conn.execute("PRAGMA user_version").fetchone()[0],
        tuple(conn.execute(
            "SELECT version,name FROM schema_migrations ORDER BY version"
        ).fetchall()),
        _objects(conn),
    )


def _apply_disposable_candidate(
    conn: sqlite3.Connection, *, fault_at: int | None = None
):
    if not conn.in_transaction:
        raise ContractRefused("transaction_required")
    if (conn.execute("PRAGMA application_id").fetchone()[0] != APPLICATION_ID
            or conn.execute("PRAGMA user_version").fetchone()[0] != 2
            or PROJECT_STATE_DB_VERSION != 2):
        raise ContractRefused("invalid_v2_source")
    if conn.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
        raise ContractRefused("foreign_keys_required")
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    )}
    required = {
        "schema_migrations", "project_metadata", "task_import_bindings",
        "runs", "run_events",
    }
    if not required.issubset(tables):
        raise ContractRefused("missing_v2_tables")
    if any(r[1] in ("lease_generation", "lease_token") for r in conn.execute(
        "PRAGMA table_info(runs)"
    )):
        raise ContractRefused("already_fenced")
    if conn.execute(
        "SELECT 1 FROM runs WHERE lease_owner IS NOT NULL LIMIT 1"
    ).fetchone():
        # A DB query alone cannot prove no live process exists. The actual
        # production migration additionally requires a maintenance gate.
        raise ContractRefused("legacy_lease_present")
    versions = [r[0] for r in conn.execute(
        "SELECT version FROM schema_migrations ORDER BY version"
    )]
    if versions != [1, 2]:
        raise ContractRefused("migration_history_mismatch")
    names = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master"
    )}
    if {
        "trace_seals", "idx_run_events_run_id_id",
        "trace_seals_valid_anchor", "trace_seals_no_update",
        "trace_seals_no_delete", "trace_seals_prefix_no_update",
        "trace_seals_prefix_no_delete", "trace_seals_prefix_no_backfill",
    } & names:
        raise ContractRefused("conflicting_schema_object")
    for number, sql in enumerate(_V3_SQL, start=1):
        if number == fault_at:
            raise sqlite3.OperationalError("injected_statement_failure")
        params = (
            (MIGRATION_NAME, STAMP, __version__)
            if sql.lstrip().startswith("INSERT INTO schema_migrations") else ()
        )
        conn.execute(sql, params)


def _run(conn: sqlite3.Connection, run_id: str, status="ready_to_integrate"):
    conn.execute(
        "INSERT INTO runs(run_id,task_id,status,execution_plan_digest,"
        "base_commit,branch_name,worktree_id,worktree_path,worker_provider,"
        "created_at,manifest_json) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        (
            run_id, "task-" + run_id, status, "e" * 64, "abcdef123",
            "branch-" + run_id, "wt-" + run_id, "/tmp/fixture-" + run_id,
            "fixture", STAMP, '{"schema_version":2}',
        ),
    )


def _event(conn, run_id, event_type="run.transition"):
    return conn.execute(
        "INSERT INTO run_events(run_id,created_at,event_type,payload_json)"
        " VALUES(?,?,?,?)", (run_id, STAMP, event_type, "{}"),
    ).lastrowid


def _seal(conn, run_id, event_id, **kwargs):
    data = dict(
        run_id=run_id, seal_sequence=1, event_prefix_id=event_id,
        seal_protocol_version=1, seal_json="{}", seal_sha256="a" * 64,
    )
    data.update(kwargs)
    return conn.execute(
        "INSERT INTO trace_seals"
        "(run_id,seal_sequence,event_prefix_id,seal_protocol_version,"
        "seal_json,seal_sha256) VALUES (?,?,?,?,?,?)",
        tuple(data[k] for k in (
            "run_id", "seal_sequence", "event_prefix_id",
            "seal_protocol_version", "seal_json", "seal_sha256"
        )),
    )


def test_v2_to_v3_candidate_preserves_rows_and_refuses_old_runtime(tmp_path):
    db = _db(tmp_path)
    with closing(_conn(db)) as conn:
        _run(conn, "run-a")
        event_id = _event(conn, "run-a")
        conn.execute("BEGIN IMMEDIATE")
        _apply_disposable_candidate(conn)
        assert conn.in_transaction
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 3
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        conn.commit()
        assert inspect_db(db) == (APPLICATION_ID, 3)
        row = conn.execute(
            "SELECT status, lease_generation, lease_token "
            "FROM runs WHERE run_id='run-a'"
        ).fetchone()
        assert row == ("ready_to_integrate", 0, None)
        assert conn.execute(
            "SELECT id FROM run_events WHERE run_id='run-a'"
        ).fetchone()[0] == event_id
        assert PROJECT_STATE_DB_VERSION == GLOBAL_STATE_DB_VERSION == 2
        with pytest.raises(RunStoreError):
            RunStore(tmp_path)


@pytest.mark.parametrize("fault_at", range(1, len(_V3_SQL) + 1))
def test_each_migration_statement_rolls_back_schema_and_version(tmp_path, fault_at):
    db = _db(tmp_path)
    with closing(_conn(db)) as conn:
        _run(conn, "run-a")
        before = _state(conn)
        conn.execute("BEGIN IMMEDIATE")
        with pytest.raises(sqlite3.OperationalError, match="injected_statement"):
            _apply_disposable_candidate(conn, fault_at=fault_at)
        conn.rollback()
        assert _state(conn) == before
        assert inspect_db(db) == (APPLICATION_ID, 2)


def test_explicit_rollback_undoes_all_candidate_ddl(tmp_path):
    db = _db(tmp_path)
    with closing(_conn(db)) as conn:
        before = _state(conn)
        conn.execute("BEGIN IMMEDIATE")
        _apply_disposable_candidate(conn)
        assert _state(conn) != before
        conn.rollback()
        assert _state(conn) == before


def test_legacy_lease_blocks_schema_upgrade_before_ddl(tmp_path):
    db = _db(tmp_path)
    with closing(_conn(db)) as conn:
        _run(conn, "run-a")
        conn.execute(
            "UPDATE runs SET lease_owner='old-owner', "
            "lease_expires_at=? WHERE run_id='run-a'", (STAMP,)
        )
        before = _state(conn)
        conn.execute("BEGIN IMMEDIATE")
        with pytest.raises(ContractRefused, match="legacy_lease_present"):
            _apply_disposable_candidate(conn)
        conn.rollback()
        assert _state(conn) == before


@pytest.mark.parametrize("reason", ["no_transaction", "wrong_app", "bad_fk"])
def test_invalid_source_preflight_refuses_without_ddl(tmp_path, reason):
    db = _db(tmp_path)
    with closing(_conn(db, fk=reason != "bad_fk")) as conn:
        if reason == "wrong_app":
            conn.execute("PRAGMA application_id=12345")
        before = _state(conn)
        if reason != "no_transaction":
            conn.execute("BEGIN IMMEDIATE")
        with pytest.raises(ContractRefused):
            _apply_disposable_candidate(conn)
        if conn.in_transaction:
            conn.rollback()
        assert _state(conn) == before


def test_composite_fk_rejects_cross_run_event_and_refuses_bad_event_type(tmp_path):
    db = _db(tmp_path)
    with closing(_conn(db)) as conn:
        _run(conn, "run-a")
        _run(conn, "run-b")
        a_event = _event(conn, "run-a")
        b_event = _event(conn, "run-b")
        wrong_type = _event(conn, "run-a", "verification.passed")
        conn.execute("BEGIN IMMEDIATE")
        _apply_disposable_candidate(conn)
        conn.commit()
        with pytest.raises(sqlite3.IntegrityError):
            _seal(conn, "run-a", b_event)
        with pytest.raises(sqlite3.IntegrityError, match="invalid_transition_anchor"):
            _seal(conn, "run-a", wrong_type)
        _seal(conn, "run-a", a_event)
        assert conn.execute("SELECT count(*) FROM trace_seals").fetchone()[0] == 1


def test_seal_single_epoch_immutable_and_parent_deletion_restricted(tmp_path):
    db = _db(tmp_path)
    with closing(_conn(db)) as conn:
        _run(conn, "run-a")
        ev = _event(conn, "run-a")
        conn.execute("BEGIN IMMEDIATE")
        _apply_disposable_candidate(conn)
        conn.commit()
        _seal(conn, "run-a", ev)
        with pytest.raises(sqlite3.IntegrityError):
            _seal(conn, "run-a", ev)
        with pytest.raises(sqlite3.IntegrityError):
            _seal(conn, "run-a", ev, seal_sequence=2)
        with pytest.raises(sqlite3.IntegrityError, match="immutable_seal"):
            conn.execute("UPDATE trace_seals SET seal_sha256=?", ("b"*64,))
        with pytest.raises(sqlite3.IntegrityError, match="immutable_seal"):
            conn.execute("DELETE FROM trace_seals")
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("DELETE FROM run_events WHERE id=?", (ev,))
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("DELETE FROM runs WHERE run_id='run-a'")


@pytest.mark.parametrize("kwargs", [
    {"seal_sha256": "A" * 64},
    {"seal_sha256": "g" * 64},
    {"seal_sha256": "a" * 63},
    {"seal_protocol_version": 2},
    {"seal_json": "x" * 4097},
    {"seal_json": b"\x00"},
    {"seal_sha256": b"a" * 64},
])
def test_seal_shape_constraints_reject_invalid_private_rows(tmp_path, kwargs):
    db = _db(tmp_path)
    with closing(_conn(db)) as conn:
        _run(conn, "run-a")
        ev = _event(conn, "run-a")
        conn.execute("BEGIN IMMEDIATE")
        _apply_disposable_candidate(conn)
        conn.commit()
        with pytest.raises(sqlite3.IntegrityError):
            _seal(conn, "run-a", ev, **kwargs)


def test_schema_does_not_cryptographically_authenticate_seal_json(tmp_path):
    # Candidate SQL provides relational/shape constraints only. Even
    # syntactically plausible 64-hex is not proof of a trusted writer.
    db = _db(tmp_path)
    with closing(_conn(db)) as conn:
        _run(conn, "run-a")
        ev = _event(conn, "run-a")
        conn.execute("BEGIN IMMEDIATE")
        _apply_disposable_candidate(conn)
        conn.commit()
        _seal(conn, "run-a", ev, seal_json="{}")
        assert conn.execute(
            "SELECT seal_sha256 FROM trace_seals"
        ).fetchone()[0] == "a" * 64


def test_fenced_generation_and_token_shape_are_schema_only(tmp_path):
    db = _db(tmp_path)
    with closing(_conn(db)) as conn:
        conn.execute("BEGIN IMMEDIATE")
        _apply_disposable_candidate(conn)
        conn.commit()
        _run(conn, "run-a")
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "UPDATE runs SET lease_generation=-1 WHERE run_id='run-a'"
            )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "UPDATE runs SET lease_token=? WHERE run_id='run-a'",
                ("not-hex",),
            )
        # SQL cannot establish lease authorization, freshness or epoch
        # monotonicity by itself. Those are trusted writer API obligations.
        conn.execute(
            "UPDATE runs SET lease_generation=1,lease_token=? "
            "WHERE run_id='run-a'", ("a"*32,),
        )
        assert conn.execute(
            "SELECT lease_generation FROM runs WHERE run_id='run-a'"
        ).fetchone()[0] == 1
@pytest.mark.parametrize("value", ["garbage", 1.5, -1, b"\x01"])
def test_generation_rejects_noninteger_negative_and_blob_values(tmp_path, value):
    db = _db(tmp_path)
    with closing(_conn(db)) as conn:
        conn.execute("BEGIN IMMEDIATE")
        _apply_disposable_candidate(conn)
        conn.commit()
        _run(conn, "run-a")
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "UPDATE runs SET lease_generation=? WHERE run_id='run-a'",
                (value,),
            )
        assert conn.execute(
            "SELECT lease_generation, typeof(lease_generation) FROM runs "
            "WHERE run_id='run-a'"
        ).fetchone() == (0, "integer")


def test_generation_int64_overflow_is_refused_without_real_fallback(tmp_path):
    db = _db(tmp_path)
    with closing(_conn(db)) as conn:
        conn.execute("BEGIN IMMEDIATE")
        _apply_disposable_candidate(conn)
        conn.commit()
        _run(conn, "run-a")
        upper = (1 << 63) - 1
        conn.execute(
            "UPDATE runs SET lease_generation=? WHERE run_id='run-a'",
            (upper,),
        )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "UPDATE runs SET lease_generation=lease_generation+1 "
                "WHERE run_id='run-a'"
            )
        assert conn.execute(
            "SELECT lease_generation,typeof(lease_generation) FROM runs "
            "WHERE run_id='run-a'"
        ).fetchone() == (upper, "integer")


def test_lease_token_rejects_blob_hex_bytes(tmp_path):
    db = _db(tmp_path)
    with closing(_conn(db)) as conn:
        conn.execute("BEGIN IMMEDIATE")
        _apply_disposable_candidate(conn)
        conn.commit()
        _run(conn, "run-a")
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "UPDATE runs SET lease_token=? WHERE run_id='run-a'",
                (b"a" * 32,),
            )
        assert conn.execute(
            "SELECT lease_token FROM runs WHERE run_id='run-a'"
        ).fetchone()[0] is None


@pytest.mark.parametrize(
    ("column", "replacement"),
    [
        ("event_type", "verification.failed"),
        ("payload_json", '{"forged":true}'),
        ("created_at", "2000-01-01T00:00:00+00:00"),
        ("run_id", "run-b"),
    ],
)
def test_sealed_anchor_is_immutable_after_insert(tmp_path, column, replacement):
    db = _db(tmp_path)
    with closing(_conn(db)) as conn:
        _run(conn, "run-a")
        _run(conn, "run-b")
        anchor = _event(conn, "run-a")
        conn.execute("BEGIN IMMEDIATE")
        _apply_disposable_candidate(conn)
        conn.commit()
        _seal(conn, "run-a", anchor)
        with pytest.raises(
            sqlite3.IntegrityError, match="sealed_event_prefix_immutable"
        ):
            # Only test-controlled fixed column names are interpolated.
            conn.execute(
                f"UPDATE run_events SET {column}=? WHERE id=?",
                (replacement, anchor),
            )
        assert conn.execute(
            "SELECT event_type,run_id FROM run_events WHERE id=?", (anchor,)
        ).fetchone() == ("run.transition", "run-a")


def test_sealed_earlier_prefix_events_are_frozen_but_later_events_are_not(
    tmp_path,
):
    db = _db(tmp_path)
    with closing(_conn(db)) as conn:
        _run(conn, "run-a")
        _run(conn, "run-b")
        earlier = _event(conn, "run-a", "run.created")
        anchor = _event(conn, "run-a")
        other = _event(conn, "run-b")
        conn.execute("BEGIN IMMEDIATE")
        _apply_disposable_candidate(conn)
        conn.commit()
        _seal(conn, "run-a", anchor)
        for statement in (
            "UPDATE run_events SET payload_json='{}' WHERE id=?",
            "DELETE FROM run_events WHERE id=?",
        ):
            with pytest.raises(
                sqlite3.IntegrityError, match="sealed_event_prefix_immutable"
            ):
                conn.execute(statement, (earlier,))
        later = _event(conn, "run-a", "integration.started")
        conn.execute(
            "UPDATE run_events SET payload_json=? WHERE id=?",
            ('{"later":true}', later),
        )
        conn.execute(
            "UPDATE run_events SET payload_json=? WHERE id=?",
            ('{"other":true}', other),
        )
        assert conn.execute(
            "SELECT count(*) FROM run_events WHERE run_id='run-a'"
        ).fetchone()[0] == 3


def test_sealed_prefix_blocks_id_backfill_and_cross_run_event_relocation(
    tmp_path,
):
    db = _db(tmp_path)
    with closing(_conn(db)) as conn:
        _run(conn, "run-a")
        _run(conn, "run-b")
        hole = _event(conn, "run-a", "run.created")
        anchor = _event(conn, "run-a")
        moving = _event(conn, "run-b")
        conn.execute("DELETE FROM run_events WHERE id=?", (hole,))
        conn.execute("BEGIN IMMEDIATE")
        _apply_disposable_candidate(conn)
        conn.commit()
        _seal(conn, "run-a", anchor)
        with pytest.raises(
            sqlite3.IntegrityError, match="sealed_event_prefix_immutable"
        ):
            conn.execute(
                "INSERT INTO run_events(id,run_id,created_at,event_type,payload_json)"
                " VALUES(?,?,?,?,?)",
                (hole, "run-a", STAMP, "run.created", "{}"),
            )
        with pytest.raises(
            sqlite3.IntegrityError, match="sealed_event_prefix_immutable"
        ):
            conn.execute(
                "UPDATE run_events SET run_id='run-a',id=? WHERE id=?",
                (hole, moving),
            )
        assert conn.execute(
            "SELECT run_id FROM run_events WHERE id=?", (moving,)
        ).fetchone()[0] == "run-b"

