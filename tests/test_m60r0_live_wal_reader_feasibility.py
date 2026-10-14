"""M6.0 R0: disposable-only SQLite WAL source-reader feasibility matrix.

CAUTION: SQLite is connected to *test-owned* WAL fixtures in this module.
Do not transplant this reader into ProjectCTL production or its exporter.
A successful SELECT (or unchanged pre/post byte sample) proves neither
no source-side effects nor a DB/filesystem as-of epoch.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import sqlite3
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from urllib.parse import quote

import pytest


pytestmark = pytest.mark.skipif(
    os.name != "posix" or not hasattr(os, "O_NOFOLLOW"),
    reason="R0 source-file observation requires POSIX O_NOFOLLOW",
)

_MAX_FIXTURE_BYTES = 8 * 1024 * 1024
_SUFFIXES = ("", "-wal", "-shm")


@dataclass(frozen=True)
class R0Candidate:
    """Diagnostic only; safe/atomic source observations are NOT certified."""

    sqlite_read: str
    rows: tuple[int, ...]
    source_changed: tuple[str, ...]
    atime_changed: tuple[str, ...]
    created_sidecars: tuple[str, ...]
    snapshot_proven: Literal[False] = False
    source_nonmutation_proven: Literal[False] = False
    cross_store_epoch_proven: Literal[False] = False

    def __post_init__(self):
        if not (
            self.snapshot_proven is False
            and self.source_nonmutation_proven is False
            and self.cross_store_epoch_proven is False
        ):
            raise ValueError("r0_never_proves_authority")


class R0FixtureRefused(ValueError):
    """No paths, SQL errors, or fixture contents in public error messages."""


def _read_fingerprint(leaf: Path):
    try:
        fd = os.open(
            leaf,
            os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_NONBLOCK", 0),
        )
    except FileNotFoundError:
        return None
    except OSError:
        raise R0FixtureRefused("unsafe_fixture_source") from None
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_size > _MAX_FIXTURE_BYTES:
            raise R0FixtureRefused("unsafe_fixture_source")
        raw = bytearray()
        while len(raw) <= _MAX_FIXTURE_BYTES:
            part = os.read(fd, min(65536, _MAX_FIXTURE_BYTES + 1 - len(raw)))
            if not part:
                break
            raw.extend(part)
        after = os.fstat(fd)
        if len(raw) != before.st_size or len(raw) > _MAX_FIXTURE_BYTES or (
            before.st_dev, before.st_ino, before.st_size,
            before.st_mtime_ns, before.st_ctime_ns,
        ) != (
            after.st_dev, after.st_ino, after.st_size,
            after.st_mtime_ns, after.st_ctime_ns,
        ):
            raise R0FixtureRefused("fixture_changed_during_read")
        current = leaf.lstat()
        if (current.st_dev, current.st_ino) != (after.st_dev, after.st_ino):
            raise R0FixtureRefused("fixture_changed_during_read")
        # Sampling bytes may itself update atime on some filesystems.
        # This is an observable diagnostic, not a non-mutation proof.
        return (
            hashlib.sha256(raw).hexdigest(),
            after.st_dev, after.st_ino, after.st_size,
            after.st_mtime_ns, after.st_ctime_ns, after.st_atime_ns,
        )
    except OSError:
        raise R0FixtureRefused("unsafe_fixture_source") from None
    finally:
        os.close(fd)


def _sample(db: Path):
    return {
        suffix: _read_fingerprint(Path(str(db) + suffix))
        for suffix in _SUFFIXES
    }


def _fixture(root: Path):
    root.mkdir(parents=True, exist_ok=True)
    db = root / "state.sqlite"
    writer = sqlite3.connect(db)
    assert writer.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"
    writer.execute("PRAGMA wal_autocheckpoint=0")
    writer.execute("CREATE TABLE r0_samples (n INTEGER NOT NULL)")
    writer.execute("INSERT INTO r0_samples VALUES (1)")
    writer.commit()
    assert Path(str(db) + "-wal").exists()
    assert Path(str(db) + "-shm").exists()
    return db, writer


def _r0_disposable_native_ro_observation(db: Path) -> R0Candidate:
    """Observe native mode=ro VFS effects for test fixtures ONLY.

    This routine does not establish a safe authority read, even on success.
    In particular SQLite may interact with -shm and/or create sidecars.
    """
    if db.name != "state.sqlite":
        raise R0FixtureRefused("invalid_fixture_name")
    before = _sample(db)
    original = Path(str(db))
    # A missing/invalid WAL is outside this narrow live-WAL experiment.
    if before[""] is None or before["-wal"] is None:
        raise R0FixtureRefused("missing_live_wal")
    header_fd = os.open(original, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        header = os.pread(header_fd, 100, 0)
    finally:
        os.close(header_fd)
    if len(header) != 100 or not header.startswith(b"SQLite format 3\x00"):
        raise R0FixtureRefused("invalid_fixture_header")
    if header[18:20] != b"\x02\x02":
        raise R0FixtureRefused("not_wal_mode")

    rows: tuple[int, ...] = ()
    outcome = "source_unreadable"
    # Unlike the real exporter, an R0 *disposable* probe intentionally
    # exercises the SQLite VFS on the original temporary fixture.
    uri = "file:" + quote(str(db.absolute()), safe="/") + "?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True, isolation_level=None, timeout=0.2)
        try:
            conn.execute("PRAGMA query_only=ON")
            conn.execute("BEGIN")
            rows = tuple(
                int(row[0]) for row in conn.execute(
                    "SELECT n FROM r0_samples ORDER BY n LIMIT 32"
                ).fetchall()
            )
            conn.execute("ROLLBACK")
            outcome = "candidate_readable"
        finally:
            conn.close()
    except sqlite3.Error:
        outcome = "source_unreadable"

    after = _sample(db)
    changed = tuple(
        suffix for suffix in _SUFFIXES
        if (before[suffix] is None) != (after[suffix] is None)
        or (
            before[suffix] is not None
            and after[suffix] is not None
            and before[suffix][:-1] != after[suffix][:-1]
        )
    )
    atime = tuple(
        suffix for suffix in _SUFFIXES
        if before[suffix] is not None and after[suffix] is not None
        and before[suffix][-1] != after[suffix][-1]
    )
    created = tuple(
        suffix for suffix in ("-wal", "-shm")
        if before[suffix] is None and after[suffix] is not None
    )
    return R0Candidate(outcome, rows, changed, atime, created)


def test_live_wal_native_mode_ro_reads_committed_rows_only_as_candidate(tmp_path):
    db, writer = _fixture(tmp_path / "live")
    try:
        result = _r0_disposable_native_ro_observation(db)
        assert result.sqlite_read == "candidate_readable"
        assert result.rows == (1,)
        assert result.snapshot_proven is False
        assert result.source_nonmutation_proven is False
        assert result.cross_store_epoch_proven is False
        assert all(s in _SUFFIXES for s in result.source_changed)
        assert "state.sqlite" not in repr(result)
    finally:
        writer.close()


def test_read_transaction_sees_one_sqlite_epoch_while_writer_commits(tmp_path):
    db, writer = _fixture(tmp_path / "writer")
    uri = "file:" + quote(str(db.absolute()), safe="/") + "?mode=ro"
    try:
        reader = sqlite3.connect(uri, uri=True, isolation_level=None)
        try:
            reader.execute("PRAGMA query_only=ON")
            reader.execute("BEGIN")
            first = reader.execute("SELECT count(*) FROM r0_samples").fetchone()[0]
            writer.execute("INSERT INTO r0_samples VALUES (2)")
            writer.commit()
            second = reader.execute("SELECT count(*) FROM r0_samples").fetchone()[0]
            assert first == second == 1
            reader.execute("ROLLBACK")
            fresh = reader.execute("SELECT count(*) FROM r0_samples").fetchone()[0]
            assert fresh == 2
        finally:
            reader.close()
    finally:
        writer.close()


def test_missing_shm_on_detached_disposable_copy_is_not_certified(tmp_path):
    db, writer = _fixture(tmp_path / "original")
    dest_root = tmp_path / "clone"
    dest_root.mkdir()
    clone = dest_root / "state.sqlite"
    try:
        shutil.copyfile(db, clone)
        shutil.copyfile(Path(str(db) + "-wal"), Path(str(clone) + "-wal"))
        assert not Path(str(clone) + "-shm").exists()
        result = _r0_disposable_native_ro_observation(clone)
        assert result.sqlite_read in ("candidate_readable", "source_unreadable")
        assert result.snapshot_proven is False
        assert result.source_nonmutation_proven is False
        assert result.cross_store_epoch_proven is False
        assert all(s in ("-wal", "-shm") for s in result.created_sidecars)
        # An entirely separate raw-copy clone does not prove one original instant.
    finally:
        writer.close()


def test_sqlite_epoch_never_binds_a_separately_replaced_json_file(tmp_path):
    db, writer = _fixture(tmp_path / "independent_files")
    artifact = db.parent / "evidence-manifest.json"
    artifact.write_text('{"epoch":1}', encoding="utf-8")
    uri = "file:" + quote(str(db.absolute()), safe="/") + "?mode=ro"
    try:
        reader = sqlite3.connect(uri, uri=True, isolation_level=None)
        try:
            reader.execute("PRAGMA query_only=ON")
            reader.execute("BEGIN")
            assert reader.execute("SELECT count(*) FROM r0_samples").fetchone()[0] == 1
            replacement = db.parent / "replacement.json"
            replacement.write_text('{"epoch":2}', encoding="utf-8")
            os.replace(replacement, artifact)
            assert reader.execute("SELECT count(*) FROM r0_samples").fetchone()[0] == 1
            assert artifact.read_text(encoding="utf-8") == '{"epoch":2}'
            reader.execute("ROLLBACK")
        finally:
            reader.close()
    finally:
        writer.close()


def test_missing_database_does_not_create_authority_files(tmp_path):
    db = tmp_path / "missing" / "state.sqlite"
    with pytest.raises(R0FixtureRefused, match="missing_live_wal"):
        _r0_disposable_native_ro_observation(db)
    assert not db.parent.exists()


def test_rollback_journal_header_never_opened_as_wal(tmp_path):
    root = tmp_path / "rollback"
    root.mkdir()
    db = root / "state.sqlite"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE t(x)")
    conn.commit()
    conn.close()
    # Synthesizing the sidecar does not change the rollback header.
    Path(str(db) + "-wal").write_bytes(b"not-a-real-wal")
    with pytest.raises(R0FixtureRefused, match="not_wal_mode"):
        _r0_disposable_native_ro_observation(db)


def test_symlinked_disposable_wal_is_refused_before_sqlite_connect(tmp_path):
    db, writer = _fixture(tmp_path / "original")
    root = tmp_path / "linked_fixture"
    root.mkdir()
    clone = root / "state.sqlite"
    try:
        shutil.copyfile(db, clone)
        wal = Path(str(db) + "-wal")
        external_before = wal.read_bytes()
        Path(str(clone) + "-wal").symlink_to(wal)
        with pytest.raises(R0FixtureRefused, match="unsafe_fixture_source"):
            _r0_disposable_native_ro_observation(clone)
        assert wal.read_bytes() == external_before
    finally:
        writer.close()


def test_result_cannot_claim_safe_snapshot_even_if_samples_match():
    # Types and a successful read are deliberately not an authority API.
    recorded = R0Candidate("candidate_readable", (1,), (), (), ())
    assert not recorded.snapshot_proven
    assert not recorded.source_nonmutation_proven
    assert not recorded.cross_store_epoch_proven

def test_negative_proof_flags_are_not_overridable():
    with pytest.raises(ValueError, match="r0_never_proves_authority"):
        R0Candidate(
            "candidate_readable", (1,), (), (), (), snapshot_proven=True
        )


def test_checkpoint_during_native_observation_cannot_upgrade_proof(
    tmp_path, monkeypatch
):
    db, writer = _fixture(tmp_path / "checkpoint")
    real_connect = sqlite3.connect
    saw_checkpoint = []

    def checkpoint_then_open(value, *args, **kwargs):
        if str(value).startswith("file:"):
            result = writer.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
            saw_checkpoint.append(result)
        return real_connect(value, *args, **kwargs)

    try:
        monkeypatch.setattr(sqlite3, "connect", checkpoint_then_open)
        observation = _r0_disposable_native_ro_observation(db)
        assert saw_checkpoint
        assert observation.snapshot_proven is False
        assert observation.source_nonmutation_proven is False
        assert observation.cross_store_epoch_proven is False
        # A completed checkpoint may change source WAL bytes/size; whether
        # a native readonly connection also touched sidecars is not proven.
    finally:
        writer.close()


def test_no_sqlite_vfs_connection_after_rejecting_missing_or_unsafe_wal(
    tmp_path, monkeypatch
):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("unsafe fixture must be rejected before VFS open")

    missing = tmp_path / "missing" / "state.sqlite"
    monkeypatch.setattr(sqlite3, "connect", forbidden)
    with pytest.raises(R0FixtureRefused):
        _r0_disposable_native_ro_observation(missing)
    assert not missing.parent.exists()
