"""M6.0 M0c: disposable offline admission/recovery decision model, NOT a migrator.

All database files are under pytest tmp_path. This never runs v3 DDL on
source authority or registers a migration command. A v2 process can ignore
new locks: external writer exclusion is a prerequisite, NOT something this
model can establish or authenticate.
"""
from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import dataclass, replace
from pathlib import Path

import pytest

from projectctl.storage.sqlite import (
    APPLICATION_ID,
    PROJECT_STATE_DB_VERSION,
    initialize_project_state_db,
    inspect_db,
)
from projectctl.trace.seal_backup_lab import rehearse_disposable_v2_backup


@dataclass(frozen=True)
class ExternalExclusion:
    """Operator-supplied CLAIM only: not independently authenticated by Python."""

    operator_approved: bool = False
    all_processes_stopped: bool = False
    background_writers_drained: bool = False
    new_starts_prevented: bool = False
    nonlocal_writers_excluded: bool = False
    exclusion_held_through_reconciliation: bool = False
    old_client_restart_blocked: bool = False


@dataclass(frozen=True)
class SourceObservation:
    app_id: int
    version: int
    history: tuple[int, ...]
    integrity: str
    legacy_owners: int
    event_count: int


def _observe(path: Path) -> SourceObservation:
    # TEST-OWNED paths only. Opening a live WAL source here would not be
    # acceptable in the future read-only R1 Trace collector.
    with closing(sqlite3.connect(path)) as conn:
        return SourceObservation(
            app_id=conn.execute("PRAGMA application_id").fetchone()[0],
            version=conn.execute("PRAGMA user_version").fetchone()[0],
            history=tuple(row[0] for row in conn.execute(
                "SELECT version FROM schema_migrations ORDER BY version"
            )),
            integrity=conn.execute("PRAGMA integrity_check").fetchone()[0],
            legacy_owners=conn.execute(
                "SELECT count(*) FROM runs WHERE lease_owner IS NOT NULL"
            ).fetchone()[0],
            event_count=conn.execute(
                "SELECT count(*) FROM run_events"
            ).fetchone()[0],
        )


def _admission_review(
    exclusion: ExternalExclusion,
    before: SourceObservation,
    after: SourceObservation,
    backup: SourceObservation | None,
    *,
    backup_durable_and_retained: bool,
    paths_anchored: bool,
) -> str:
    """A test-only checklist. The best result is REVIEW, never GO."""
    if not all(vars(exclusion).values()):
        return "BLOCK_MISSING_EXTERNAL_EXCLUSION"
    if not paths_anchored or not backup_durable_and_retained or backup is None:
        return "BLOCK_MISSING_TRUSTED_BACKUP"
    if any(x != APPLICATION_ID for x in (before.app_id, after.app_id, backup.app_id)):
        return "QUARANTINE_SOURCE_IDENTITY"
    for state in (before, after, backup):
        if state.version != 2 or state.history != (1, 2) or state.integrity != "ok":
            return "QUARANTINE_SOURCE_VERSION_OR_INTEGRITY"
        if state.legacy_owners:
            return "BLOCK_LEGACY_LEASE"
    if before != after or before != backup:
        # Mismatch proves one problem; matching samples cannot prove
        # absence of a hidden legacy writer or JSON artifact mutations.
        return "BLOCK_OBSERVED_EPOCH_DRIFT"
    return "OPERATOR_REVIEW_ONLY"


def _recovery_review(
    *,
    backup: SourceObservation | None,
    source: SourceObservation | None,
    outcome_known: bool,
    exclusion_continuous: bool,
) -> str:
    """No automatic restore, retry, v3 acceptance or restart."""
    if not exclusion_continuous or backup is None or source is None:
        return "QUARANTINE_MISSING_EVIDENCE"
    if (backup.app_id != APPLICATION_ID or backup.version != 2
            or backup.history != (1, 2) or backup.integrity != "ok"):
        return "QUARANTINE_UNTRUSTED_BACKUP"
    if not outcome_known:
        return "QUARANTINE_AMBIGUOUS_COMMIT"
    if source.app_id != APPLICATION_ID or source.integrity != "ok":
        return "QUARANTINE_UNTRUSTED_SOURCE"
    if source.version == 2 and source.history == (1, 2):
        return "OPERATOR_REVIEW_V2_RETAIN_BACKUP"
    if source.version == 3 and source.history == (1, 2, 3):
        # Complete unified v3 schema, trusted writer/Seal and compatibility
        # are NOT proved by these three integers.
        return "OPERATOR_REVIEW_V3_NOT_VALIDATED"
    return "QUARANTINE_MIXED_VERSION_HISTORY"


def _fixture(tmp_path: Path) -> tuple[Path, sqlite3.Connection]:
    db = tmp_path / "disposable" / ".projectctl" / "state.sqlite"
    initialize_project_state_db(db)
    conn = sqlite3.connect(db)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute(
        "INSERT INTO runs(run_id,task_id,status,execution_plan_digest,"
        "base_commit,branch_name,worktree_id,worktree_path,worker_provider,"
        "created_at,manifest_json) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        ("run-m0c", "task-m0c", "planned", "f"*64, "abcdef123",
         "branch-m0c", "wt-m0c", str(db.parent / "nonexistent-worktree"),
         "fixture", "2026-10-17T00:00:00+00:00", "{}"),
    )
    conn.execute(
        "INSERT INTO project_metadata(key,value) VALUES('m0c','wal-committed')"
    )
    conn.commit()
    assert inspect_db(db) == (APPLICATION_ID, 2)
    return db, conn


def _claim() -> ExternalExclusion:
    return ExternalExclusion(True, True, True, True, True, True, True)


def _published_backup(conn: sqlite3.Connection, db: Path) -> Path:
    dest = db.parent / "m0c-backup.sqlite"
    rehearse_disposable_v2_backup(conn, dest)
    return dest


def test_all_external_exclusion_assertions_required_even_with_backup(tmp_path):
    db, conn = _fixture(tmp_path)
    try:
        backup = _published_backup(conn, db)
        obs = _observe(db)
        assert obs == _observe(backup)
        for field in vars(_claim()):
            incomplete = replace(_claim(), **{field: False})
            assert _admission_review(
                incomplete, obs, obs, obs,
                backup_durable_and_retained=True, paths_anchored=True,
            ) == "BLOCK_MISSING_EXTERNAL_EXCLUSION"
        # Even an operator-supplied perfect-looking claim is not
        # trustworthy enough to authorize an automatic migration.
        assert _admission_review(
            _claim(), obs, obs, obs,
            backup_durable_and_retained=True, paths_anchored=True,
        ) == "OPERATOR_REVIEW_ONLY"
    finally:
        conn.close()


@pytest.mark.parametrize("missing", ["backup", "durability", "paths"])
def test_missing_backup_or_path_evidence_blocks(tmp_path, missing):
    db, conn = _fixture(tmp_path)
    try:
        obs = _observe(db)
        assert _admission_review(
            _claim(), obs, obs, None if missing == "backup" else obs,
            backup_durable_and_retained=missing != "durability",
            paths_anchored=missing != "paths",
        ) == "BLOCK_MISSING_TRUSTED_BACKUP"
        assert PROJECT_STATE_DB_VERSION == 2
    finally:
        conn.close()


def test_post_backup_writer_invalidates_preflight_observation(tmp_path):
    db, conn = _fixture(tmp_path)
    try:
        backup = _published_backup(conn, db)
        before = _observe(db)
        # Simulate a writer running after backup despite claimed exclusion.
        conn.execute(
            "INSERT INTO run_events(run_id,created_at,event_type,payload_json)"
            " VALUES(?,?,?,?)",
            ("run-m0c", "2026-10-17T00:00:01+00:00", "m0c.fixture", "{}"),
        )
        conn.commit()
        after = _observe(db)
        assert before != after
        assert _admission_review(
            _claim(), before, after, _observe(backup),
            backup_durable_and_retained=True, paths_anchored=True,
        ) == "BLOCK_OBSERVED_EPOCH_DRIFT"
    finally:
        conn.close()


def test_wrong_identity_version_history_integrity_or_owner_refused(tmp_path):
    db, conn = _fixture(tmp_path)
    try:
        backup = _published_backup(conn, db)
        original = _observe(db)
        cases = [
            (replace(original, app_id=123), "QUARANTINE_SOURCE_IDENTITY"),
            (replace(original, version=3), "QUARANTINE_SOURCE_VERSION_OR_INTEGRITY"),
            (replace(original, history=(1,)), "QUARANTINE_SOURCE_VERSION_OR_INTEGRITY"),
            (replace(original, integrity="bad"), "QUARANTINE_SOURCE_VERSION_OR_INTEGRITY"),
            (replace(original, legacy_owners=1), "BLOCK_LEGACY_LEASE"),
        ]
        for observed, expected in cases:
            assert _admission_review(
                _claim(), original, observed, _observe(backup),
                backup_durable_and_retained=True, paths_anchored=True,
            ) == expected
        assert _observe(db) == original
    finally:
        conn.close()


@pytest.mark.parametrize("fault", ["staged", "copied", "validated", "file_fsynced"])
def test_backup_prepublication_fault_blocks_admission(tmp_path, fault):
    db, conn = _fixture(tmp_path)
    try:
        destination = db.parent / "m0c-backup.sqlite"

        def abort(phase: str, _stage: Path) -> None:
            if phase == fault:
                raise RuntimeError("m0c_injected_failure")

        with pytest.raises(RuntimeError, match="m0c_injected_failure"):
            rehearse_disposable_v2_backup(conn, destination, fault_hook=abort)
        assert not destination.exists()
        obs = _observe(db)
        assert _admission_review(
            _claim(), obs, obs, None,
            backup_durable_and_retained=False, paths_anchored=True,
        ) == "BLOCK_MISSING_TRUSTED_BACKUP"
    finally:
        conn.close()


def test_recovery_keeps_original_and_requires_operator_decision(tmp_path):
    db, conn = _fixture(tmp_path)
    try:
        backup = _published_backup(conn, db)
        original = _observe(backup)
        current = _observe(db)
        assert _recovery_review(
            backup=original, source=current, outcome_known=True,
            exclusion_continuous=True,
        ) == "OPERATOR_REVIEW_V2_RETAIN_BACKUP"
        assert _recovery_review(
            backup=original, source=current, outcome_known=False,
            exclusion_continuous=True,
        ) == "QUARANTINE_AMBIGUOUS_COMMIT"
        assert _recovery_review(
            backup=original, source=current, outcome_known=True,
            exclusion_continuous=False,
        ) == "QUARANTINE_MISSING_EVIDENCE"
        assert _recovery_review(
            backup=replace(original, integrity="corrupt"), source=current,
            outcome_known=True, exclusion_continuous=True,
        ) == "QUARANTINE_UNTRUSTED_BACKUP"
        assert _recovery_review(
            backup=original, source=replace(current, version=3),
            outcome_known=True, exclusion_continuous=True,
        ) == "QUARANTINE_MIXED_VERSION_HISTORY"
        assert _recovery_review(
            backup=original,
            source=replace(current, version=3, history=(1, 2, 3)),
            outcome_known=True, exclusion_continuous=True,
        ) == "OPERATOR_REVIEW_V3_NOT_VALIDATED"
        assert inspect_db(db) == (APPLICATION_ID, 2)
    finally:
        conn.close()
