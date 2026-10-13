"""B2a feasibility only: inspect a detached SQLite WAL copy without connecting to run authority.

This is deliberately NOT an operational run reader, Collector, SQLite
transaction snapshot guarantee, artifact-link proof, or public CLI API.
Even two identical raw reads cannot prove that a concurrently checkpointing
multi-file SQLite source was a single atomic instant.
"""
from __future__ import annotations

import hashlib
import os
import sqlite3
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

from projectctl.trace.snapshot import (
    TraceSnapshotError,
    _DIRECTORY_FLAGS,
    _FILE_FLAGS,
    _assert_supported_platform,
    _directory_chain,
    _read_fd,
)

MAX_PROBE_DB_BYTES = 32 * 1024 * 1024
MAX_PROBE_WAL_BYTES = 16 * 1024 * 1024
_SQLITE_HEADER = b"SQLite format 3\x00"
_SQLITE_WAL_MAGICS = {b"7\x7f\x06\x82", b"7\x7f\x06\x83"}


@dataclass(frozen=True)
class DetachedWalProbe:
    """Candidate readability only; *not* proof of an authoritative snapshot."""

    candidate_db_sha256: str
    candidate_wal_sha256: str
    detached_integrity: str = "ok"
    snapshot_proven: bool = False


def _pinned_bytes(parent_fd: int, name: str, maximum: int) -> bytes:
    """Bounded same-descriptor bytes with no-follow and post-read leaf identity."""
    try:
        fd = os.open(name, _FILE_FLAGS, dir_fd=parent_fd)
        try:
            raw = _read_fd(fd, limit=maximum)
            original = os.fstat(fd)
            current = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
            if not stat.S_ISREG(current.st_mode) or (
                original.st_dev, original.st_ino, original.st_size,
                original.st_mtime_ns, original.st_ctime_ns
            ) != (
                current.st_dev, current.st_ino, current.st_size,
                current.st_mtime_ns, current.st_ctime_ns
            ):
                raise TraceSnapshotError("source_changed")
            return raw
        finally:
            os.close(fd)
    except TraceSnapshotError:
        raise
    except (OSError, ValueError):
        raise TraceSnapshotError("source_unreadable") from None


def _sample_pair(parent_fd: int) -> tuple[bytes, bytes]:
    db = _pinned_bytes(parent_fd, "state.sqlite", MAX_PROBE_DB_BYTES)
    wal = _pinned_bytes(parent_fd, "state.sqlite-wal", MAX_PROBE_WAL_BYTES)
    if len(db) < 100 or not db.startswith(_SQLITE_HEADER):
        raise TraceSnapshotError("invalid_content")
    if db[18] != 2 or db[19] != 2:
        raise TraceSnapshotError("source_unreadable")
    if len(wal) < 32 or wal[:4] not in _SQLITE_WAL_MAGICS:
        raise TraceSnapshotError("invalid_content")
    return db, wal


def _write_private_copy(path: Path, data: bytes) -> None:
    # TemporaryDirectory is created with owner-only permissions. The file
    # is exclusively created with 0600; neither path comes from the source.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        pos = 0
        while pos < len(data):
            written = os.write(fd, data[pos:])
            if written <= 0:
                raise TraceSnapshotError("source_unreadable")
            pos += written
    finally:
        os.close(fd)


def _inspect_detached_copy(db: bytes, wal: bytes) -> None:
    """Only SQLite detached staging can create/edit its WAL/SHM sidecars."""
    try:
        with tempfile.TemporaryDirectory(prefix="projectctl-m6-wal-probe-") as temp:
            staging_db = Path(temp) / "state.sqlite"
            _write_private_copy(staging_db, db)
            _write_private_copy(Path(temp) / "state.sqlite-wal", wal)
            uri = "file:" + quote(str(staging_db), safe="/") + "?mode=ro"
            connection = sqlite3.connect(
                uri, uri=True, isolation_level=None, timeout=0.2
            )
            try:
                connection.execute("PRAGMA query_only=ON")
                connection.execute("BEGIN")
                result = connection.execute("PRAGMA integrity_check").fetchone()
                if not result or result[0] != "ok":
                    raise TraceSnapshotError("invalid_content")
                connection.execute("ROLLBACK")
            finally:
                connection.close()
    except TraceSnapshotError:
        raise
    except (sqlite3.Error, OSError, ValueError):
        raise TraceSnapshotError("source_unreadable") from None


def probe_detached_live_wal(project_root: Path) -> DetachedWalProbe:
    """Explore a bounded detached raw copy, NEVER connect SQLite to source.

    Independent samples and post-staging repeat are a race detector only,
    NOT an atomic transaction, and success must never authorize a trace
    source as 'present', 'complete' or 'supported'.
    """
    _assert_supported_platform()
    try:
        with _directory_chain(Path(project_root), ".projectctl") as parent_fd:
            db, wal = _sample_pair(parent_fd)
            if (db, wal) != _sample_pair(parent_fd):
                raise TraceSnapshotError("inconsistent_snapshot")
            _inspect_detached_copy(db, wal)
            if (db, wal) != _sample_pair(parent_fd):
                raise TraceSnapshotError("inconsistent_snapshot")
    except TraceSnapshotError:
        raise
    except (OSError, ValueError):
        raise TraceSnapshotError("source_unreadable") from None

    return DetachedWalProbe(
        candidate_db_sha256=hashlib.sha256(db).hexdigest(),
        candidate_wal_sha256=hashlib.sha256(wal).hexdigest(),
    )
