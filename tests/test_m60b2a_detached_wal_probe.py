"""Feasibility-only tests: detached WAL probe does NOT authorize live Trace reads."""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest

from projectctl.trace.snapshot import TraceSnapshotError
from projectctl.trace.wal_probe import (
    MAX_PROBE_DB_BYTES,
    probe_detached_live_wal,
)

pytestmark = pytest.mark.skipif(
    os.name != "posix" or not hasattr(os, "O_NOFOLLOW"),
    reason="B2a prototype requires POSIX no-follow descriptors",
)


def _wal_fixture(tmp_path: Path):
    state = tmp_path / ".projectctl"
    state.mkdir()
    db = state / "state.sqlite"
    connection = sqlite3.connect(db)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA wal_autocheckpoint=0")
    connection.execute("CREATE TABLE proof (value TEXT NOT NULL)")
    connection.execute("INSERT INTO proof VALUES ('secret-live-WAL-payload')")
    connection.commit()
    assert Path(str(db) + "-wal").exists()
    assert Path(str(db) + "-shm").exists()
    return db, connection


def _bytes_and_metadata(db: Path):
    values = {}
    for suffix in ("", "-wal", "-shm"):
        file = Path(str(db) + suffix)
        if file.exists():
            info = file.stat()
            values[suffix] = (
                file.read_bytes(), info.st_size, info.st_mtime_ns,
                info.st_ctime_ns, info.st_ino,
            )
    return values


def test_detached_wal_probe_reads_candidate_without_authority_mutation(tmp_path):
    db, connection = _wal_fixture(tmp_path)
    try:
        before = _bytes_and_metadata(db)
        first = probe_detached_live_wal(tmp_path)
        second = probe_detached_live_wal(tmp_path)
        assert first == second
        assert len(first.candidate_db_sha256) == 64
        assert len(first.candidate_wal_sha256) == 64
        assert first.detached_integrity == "ok"
        assert first.snapshot_proven is False
        assert _bytes_and_metadata(db) == before
        assert "secret-live-WAL-payload" not in repr(first)
    finally:
        connection.close()


def test_probe_never_calls_sqlite_on_original_authority(tmp_path, monkeypatch):
    db, writer = _wal_fixture(tmp_path)
    import projectctl.trace.wal_probe as probe
    actual_connect = sqlite3.connect
    observed = []

    def guarded_connect(value, *args, **kwargs):
        observed.append(str(value))
        assert "/.projectctl/" not in str(value), (
            "Original authority must not be passed to SQLite VFS"
        )
        return actual_connect(value, *args, **kwargs)

    monkeypatch.setattr(probe.sqlite3, "connect", guarded_connect)
    try:
        before = _bytes_and_metadata(db)
        assert probe_detached_live_wal(tmp_path).detached_integrity == "ok"
        assert observed
        assert _bytes_and_metadata(db) == before
    finally:
        writer.close()


def test_concurrent_wal_writer_rejected_before_candidate_return(tmp_path, monkeypatch):
    db, writer = _wal_fixture(tmp_path)
    import projectctl.trace.wal_probe as probe
    original = probe._inspect_detached_copy

    def writer_during_staged_inspection(database, wal):
        result = original(database, wal)
        writer.execute("INSERT INTO proof VALUES ('concurrent-new-commit')")
        writer.commit()
        return result

    monkeypatch.setattr(probe, "_inspect_detached_copy", writer_during_staged_inspection)
    try:
        with pytest.raises(TraceSnapshotError) as exc:
            probe_detached_live_wal(tmp_path)
        assert exc.value.reason_code == "inconsistent_snapshot"
    finally:
        writer.close()


def test_missing_authority_is_not_created(tmp_path):
    with pytest.raises(TraceSnapshotError):
        probe_detached_live_wal(tmp_path)
    assert not (tmp_path / ".projectctl").exists()


def test_symlinked_wal_refuses_to_read_external_file(tmp_path):
    db, writer = _wal_fixture(tmp_path)
    try:
        wal = Path(str(db) + "-wal")
        external = tmp_path / "outside-secret"
        external.write_bytes(wal.read_bytes())
        wal.unlink()
        wal.symlink_to(external)
        before = external.read_bytes()
        with pytest.raises(TraceSnapshotError):
            probe_detached_live_wal(tmp_path)
        assert external.read_bytes() == before
    finally:
        writer.close()


def test_oversized_database_refused_before_staging(tmp_path):
    state = tmp_path / ".projectctl"
    state.mkdir()
    with (state / "state.sqlite").open("wb") as stream:
        stream.write(b"SQLite format 3\\x00")
        stream.truncate(MAX_PROBE_DB_BYTES + 1)
    (state / "state.sqlite-wal").write_bytes(b"7\\x7f\\x06\\x82" + b"x" * 40)
    with pytest.raises(TraceSnapshotError) as exc:
        probe_detached_live_wal(tmp_path)
    assert exc.value.reason_code == "source_unreadable"


def test_rollback_journal_source_refused_as_outside_b2a_scope(tmp_path):
    state = tmp_path / ".projectctl"
    state.mkdir()
    db = state / "state.sqlite"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE sample (id INTEGER)")
    conn.commit()
    conn.close()
    (state / "state.sqlite-wal").write_bytes(b"7\\x7f\\x06\\x82" + b"x" * 40)
    with pytest.raises(TraceSnapshotError) as exc:
        probe_detached_live_wal(tmp_path)
    assert exc.value.reason_code == "source_unreadable"


def test_probe_does_not_leave_staging_directory(tmp_path, monkeypatch):
    db, writer = _wal_fixture(tmp_path)
    import projectctl.trace.wal_probe as probe
    original_temp = probe.tempfile.TemporaryDirectory
    created = []

    class CapturedTemp:
        def __init__(self, **kwargs):
            self.delegate = original_temp(**kwargs)

        def __enter__(self):
            value = self.delegate.__enter__()
            created.append(Path(value))
            return value

        def __exit__(self, *args):
            return self.delegate.__exit__(*args)

    monkeypatch.setattr(probe.tempfile, "TemporaryDirectory", CapturedTemp)
    try:
        probe_detached_live_wal(tmp_path)
        assert created and all(not x.exists() for x in created)
    finally:
        writer.close()
