"""M6.0 R0b — disposable real ProjectCTL v2 WAL + external JSON epoch counterexample.

Tests deliberately open *only newly-created temporary* SQLite databases.
They do NOT implement a ProjectCTL live-WAL reader, do not certify
source-nonmutation and do not publish Trace or Seal.
"""
from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from urllib.parse import quote

import pytest

from projectctl.storage.sqlite import (
    PROJECT_STATE_DB_VERSION,
    initialize_project_state_db,
)
from projectctl.trace.snapshot import TraceSnapshotError, read_run_db_snapshot


_DECISION = (
    Path(__file__).resolve().parents[1]
    / "docs/architecture/r0b/r0b-current-feasibility-decision.json"
)


def _source(tmp_path: Path):
    """Disposable ProjectCTL v2 DB, separate fixed-size JSON, open WAL writer."""
    project = tmp_path / "disposable-project"
    storage = project / ".projectctl"
    storage.mkdir(parents=True)
    db = storage / "state.sqlite"
    initialize_project_state_db(db)
    writer = sqlite3.connect(db, isolation_level=None)
    writer.execute("PRAGMA wal_autocheckpoint=0")
    assert writer.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    writer.execute("BEGIN IMMEDIATE")
    writer.execute("CREATE TABLE r0b_epoch_lab(epoch INTEGER NOT NULL)")
    writer.execute("INSERT INTO r0b_epoch_lab VALUES (1)")
    writer.execute("COMMIT")
    assert Path(str(db) + "-wal").exists()
    manifest = storage / "r0b-test-only-manifest.json"
    manifest.write_text('{"epoch":1}\n', encoding="utf-8")
    return project, db, manifest, writer


def test_actual_sqlite_snapshot_does_not_freeze_independent_file(tmp_path):
    """Both individually valid reads form an epoch combination never written."""
    if os.name != "posix":
        pytest.skip("POSIX disposable WAL observation")
    project, db, manifest, writer = _source(tmp_path)
    uri = "file:" + quote(str(db.absolute()), safe="/") + "?mode=ro"
    try:
        reader = sqlite3.connect(uri, uri=True, isolation_level=None)
        try:
            reader.execute("PRAGMA query_only=ON")
            reader.execute("BEGIN")
            # A read, not BEGIN by itself, pins the SQLite WAL snapshot.
            first_db = reader.execute(
                "SELECT max(epoch) FROM r0b_epoch_lab"
            ).fetchone()[0]
            assert first_db == 1

            # DB epoch advances, and an external JSON file is separately
            # atomically published *after* it; no common SQLite transaction.
            writer.execute("BEGIN IMMEDIATE")
            writer.execute("INSERT INTO r0b_epoch_lab VALUES (2)")
            writer.execute("COMMIT")
            staged = manifest.with_suffix(".next")
            staged.write_text('{"epoch":2}\n', encoding="utf-8")
            os.replace(staged, manifest)

            pinned_db = reader.execute(
                "SELECT max(epoch) FROM r0b_epoch_lab"
            ).fetchone()[0]
            external_now = json.loads(manifest.read_bytes())["epoch"]
            assert pinned_db == 1
            assert external_now == 2
            assert (pinned_db, external_now) == (1, 2)
            # A later read can observe the newer SQLite epoch, but cannot
            # retroactively bind the earlier read to the external JSON.
            reader.execute("ROLLBACK")
            assert reader.execute(
                "SELECT max(epoch) FROM r0b_epoch_lab"
            ).fetchone()[0] == 2
        finally:
            reader.close()
    finally:
        writer.close()


def test_projectctl_reader_rejects_disposable_active_wal_before_sqlite_open(
    tmp_path,
    monkeypatch,
):
    """Guard public-read-path refusal; never silently wire R0's test VFS."""
    if os.name != "posix" or not hasattr(os, "O_NOFOLLOW"):
        pytest.skip("requires POSIX no-follow")
    project, db, _manifest, writer = _source(tmp_path)
    try:
        # Ensure R0b's current production-facing snapshot guard refuses WAL.
        with pytest.raises(TraceSnapshotError, match="source_unreadable"):
            read_run_db_snapshot(project, "r0b_disposable")
    finally:
        writer.close()


def test_r0b_current_decision_is_explicitly_fail_closed():
    report = json.loads(_DECISION.read_text(encoding="utf-8"))
    assert report == {
        "stage": "M6.0-R0b",
        "baseline_main_sha": "f9b1c7ae31cfc1223586ca1001747dc36c67f0f7",
        "decision_scope": "CURRENT_PROJECTCTL_v2_ACTIVE_WAL_EXPORT_FEASIBILITY_ONLY",
        "selected": "C_FAIL_CLOSED_NOT_CURRENTLY_SUPPORTED",
        "route_A_native_source_read_nonmutation_proven": False,
        "route_A_cross_store_same_epoch_proven": False,
        "route_B_snapshot_atomicity_proven": False,
        "route_B_source_nonmutation_proven": False,
        "route_B_cross_store_same_epoch_proven": False,
        "route_C_live_WAL_export_must_refuse": True,
        "reopen_requires": "SEPARATELY_REVIEWED_INDEPENDENT_PLATFORM_AND_EPOCH_EVIDENCE",
        "authorizes_source_WAL_reader": False,
        "authorizes_trace_collector_or_CLI": False,
        "authorizes_writer_Seal": False,
        "authorizes_migration": False,
        "authorizes_root_trial": False,
        "state": "PROPOSED_FAIL_CLOSED_DECISION_NOT_ADR_CHANGE",
    }


def test_project_still_v2_and_no_public_trace_cli_registration():
    assert PROJECT_STATE_DB_VERSION == 2
    source = (Path(__file__).resolve().parents[1]
              / "projectctl/cli/entry.py").read_text(encoding="utf-8")
    assert "register_trace" not in source
    assert "trace export" not in source
