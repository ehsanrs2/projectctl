"""M6.0 B3a2: experimental in-transaction Seal insertion boundary.

No schema creation, commit, open, migration, file read or production writer
registration occurs here. Future integration requires separate acceptance of
the SQLite migration, durable file publication and concurrency protocol.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3

from projectctl.trace.seal_contract import (
    VerificationAsOfSealV1,
    canonical_private_seal_json_bytes,
    private_seal_sha256,
)

# This is a *design candidate* for an explicit future v2 -> v3 migration.
# It is NEVER executed by ProjectCTL initialization or this module.
EXPERIMENTAL_TRACE_SEALS_DDL = """
CREATE TABLE trace_seals (
    run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE RESTRICT,
    seal_sequence INTEGER NOT NULL CHECK(seal_sequence > 0),
    event_prefix_id INTEGER NOT NULL REFERENCES run_events(id) ON DELETE RESTRICT,
    seal_json TEXT NOT NULL,
    seal_sha256 TEXT NOT NULL CHECK(length(seal_sha256) = 64),
    PRIMARY KEY(run_id, seal_sequence),
    UNIQUE(run_id, event_prefix_id)
);
CREATE TRIGGER trace_seals_no_update
BEFORE UPDATE ON trace_seals BEGIN
    SELECT RAISE(ABORT, 'immutable_seal');
END;
CREATE TRIGGER trace_seals_no_delete
BEFORE DELETE ON trace_seals BEGIN
    SELECT RAISE(ABORT, 'immutable_seal');
END;
"""

# Explicit selected columns only: mirrors B1a snapshot's non-payload run
# row projection. Do not include private lease/worker/provider columns.
RUN_RECORD_PROJECTION_COLUMNS = (
    "run_id", "task_id", "status", "terminal_reason",
    "execution_plan_digest", "base_commit", "candidate_commit",
    "created_at", "completed_at",
)


class SealTransactionRefused(ValueError):
    """Safe internal refusal; no source data is included in the message."""


def selected_run_projection_sha256(row: sqlite3.Row) -> str:
    """Stable private digest of fixed, explicitly selected run columns."""
    if not isinstance(row, sqlite3.Row):
        raise SealTransactionRefused("invalid_run_row")
    try:
        payload = {name: row[name] for name in RUN_RECORD_PROJECTION_COLUMNS}
        encoded = json.dumps(
            payload, sort_keys=True, ensure_ascii=False,
            separators=(",", ":"), allow_nan=False,
        ).encode("utf-8")
    except (KeyError, IndexError, TypeError, ValueError, UnicodeError):
        raise SealTransactionRefused("invalid_run_projection") from None
    return hashlib.sha256(encoded).hexdigest()


def insert_verification_seal_in_open_transaction(
    conn: sqlite3.Connection,
    seal: VerificationAsOfSealV1,
    *,
    expected_project_id: str,
) -> None:
    """Insert pilot Seal only, in caller-owned existing writer transaction.

    **Does NOT COMMIT**. The caller must have already updated the Run row
    and inserted its transition event in the SAME transaction. File byte
    digests and project_id trust remain external prerequisites. Do not call
    against a production ProjectCTL DB (no approved schema migration).
    """
    if not conn.in_transaction:
        raise SealTransactionRefused("no_active_writer_transaction")
    if not isinstance(seal, VerificationAsOfSealV1):
        raise SealTransactionRefused("invalid_seal_model")
    if type(expected_project_id) is not str or seal.project_id != expected_project_id:
        raise SealTransactionRefused("identity_mismatch")
    if seal.seal_sequence != 1:
        # B3a2 explicitly excludes later epochs and re-verification.
        raise SealTransactionRefused("unsupported_epoch")
    row = conn.execute(
        "SELECT run_id, task_id, status, terminal_reason, "
        "execution_plan_digest, base_commit, candidate_commit, "
        "created_at, completed_at, manifest_json FROM runs WHERE run_id=?",
        (seal.run_id,),
    ).fetchone()
    if row is None:
        raise SealTransactionRefused("missing_run")
    if not isinstance(row, sqlite3.Row):
        raise SealTransactionRefused("invalid_run_row")
    if (row["task_id"] != seal.task_id
            or row["status"] != "ready_to_integrate"
            or row["run_id"] != seal.run_id):
        raise SealTransactionRefused("identity_or_status_mismatch")
    manifest = row["manifest_json"]
    if not isinstance(manifest, str):
        raise SealTransactionRefused("invalid_manifest")
    manifest_hash = hashlib.sha256(manifest.encode("utf-8")).hexdigest()
    if manifest_hash != seal.run_manifest_raw_sha256:
        raise SealTransactionRefused("run_manifest_digest_mismatch")
    if selected_run_projection_sha256(row) != seal.run_record_projection_sha256:
        raise SealTransactionRefused("run_projection_digest_mismatch")
    # Structural only: a full versioned RunManifest/phase-specific semantic
    # validation is a separate trusted writer acceptance gate.
    event = conn.execute(
        "SELECT run_id, event_type FROM run_events WHERE id=?",
        (seal.event_prefix_id,),
    ).fetchone()
    if event is None or event["run_id"] != seal.run_id or event["event_type"] != "run.transition":
        raise SealTransactionRefused("invalid_event_boundary")
    latest = conn.execute(
        "SELECT MAX(id) FROM run_events WHERE run_id=?",
        (seal.run_id,),
    ).fetchone()[0]
    if latest != seal.event_prefix_id:
        raise SealTransactionRefused("stale_event_boundary")
    if conn.execute(
        "SELECT 1 FROM trace_seals WHERE run_id=? LIMIT 1",
        (seal.run_id,),
    ).fetchone() is not None:
        raise SealTransactionRefused("duplicate_pilot_seal")
    conn.execute(
        "INSERT INTO trace_seals("
        "run_id, seal_sequence, event_prefix_id, seal_json, seal_sha256"
        ") VALUES (?, ?, ?, ?, ?)",
        (
            seal.run_id, seal.seal_sequence, seal.event_prefix_id,
            canonical_private_seal_json_bytes(seal).decode("utf-8"),
            private_seal_sha256(seal),
        ),
    )
