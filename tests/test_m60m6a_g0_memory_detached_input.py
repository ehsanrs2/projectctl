"""M6a-G0: prove an *in-memory* consumer boundary for detached DB bytes.

Only tests, all disk fixtures under pytest tmp_path. This is NOT a safe
producer/capture method, attested source, cross-store epoch, current Run,
authenticated receipt, runtime Reader, Collector, CLI or deployment.
Existing B1/B2/R0b and bdiag tests remain the authority for their scopes.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from contextlib import closing

import pytest

from projectctl.storage.sqlite import (
    APPLICATION_ID,
    PROJECT_STATE_DB_VERSION,
    initialize_project_state_db,
)

_HEADER = b"SQLite format 3\x00"
_MAX_IMAGE_BYTES = 16 * 1024 * 1024
_DECISION = "M6A_MEMORY_SQLITE_INPUT_LAB_ONLY"


class InputRefused(ValueError):
    """Fixed, sanitized refusal; no input file path is accepted."""


@dataclass(frozen=True)
class MemoryOnlyObservation:
    decision: str
    db_schema_version: int
    runs_count: int
    source_origin_proven: bool = False
    cross_store_epoch_proven: bool = False
    source_capture_nonmutation_proven: bool = False
    authenticated_custody_proven: bool = False
    current_state_proven: bool = False
    authorizes_collector_or_cli: bool = False


def _inspect_memory_image(raw: bytes) -> MemoryOnlyObservation:
    """Consume supplied bytes only; SQLite sees ':memory:', never a path.

    The caller's byte acquisition and external JSON epoch are OUT OF SCOPE.
    In particular, this does not establish source atime/nonmutation during
    acquisition. Refuse WAL data rather than recovering or converting it.
    """
    if (type(raw) is not bytes or len(raw) < 512 or
            len(raw) > _MAX_IMAGE_BYTES or
            raw[:len(_HEADER)] != _HEADER):
        raise InputRefused("INVALID_OR_UNBOUNDED_INPUT_IMAGE")
    if raw[18:20] != b"\x01\x01":
        raise InputRefused("WAL_OR_UNSUPPORTED_JOURNAL_IMAGE")
    try:
        conn = sqlite3.connect(":memory:", isolation_level=None)
    except (sqlite3.Error, OSError):
        raise InputRefused("MEMORY_SQLITE_UNAVAILABLE") from None
    try:
        if not hasattr(conn, "deserialize"):
            raise InputRefused("MEMORY_DESERIALIZE_UNAVAILABLE")
        conn.deserialize(raw)
        conn.execute("PRAGMA trusted_schema=OFF")
        conn.execute("PRAGMA query_only=ON")
        conn.execute("BEGIN")
        app_id = conn.execute("PRAGMA application_id").fetchone()[0]
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        if app_id != APPLICATION_ID or version != PROJECT_STATE_DB_VERSION:
            raise InputRefused("UNSUPPORTED_SOURCE_SCHEMA")
        # A deliberately *non-authoritative* count. A syntactically valid
        # database does not prove where/when its bytes originated.
        count = conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
        if type(count) is not int or count < 0:
            raise InputRefused("INVALID_SOURCE_CONTENT")
        return MemoryOnlyObservation(
            decision=_DECISION,
            db_schema_version=version,
            runs_count=count,
        )
    except InputRefused:
        raise
    except (sqlite3.Error, ValueError, TypeError):
        raise InputRefused("INVALID_SOURCE_CONTENT") from None
    finally:
        conn.close()


def _synthetic_v2_rollback_image(tmp_path: Path) -> tuple[Path, bytes]:
    """Only manufacture a disposable v2 ProjectCTL schema in a temp dir."""
    db = tmp_path / "synthetic-projectctl-state.sqlite"
    initialize_project_state_db(db)
    with closing(sqlite3.connect(db)) as conn:
        mode = conn.execute("PRAGMA journal_mode=DELETE").fetchone()[0]
        assert mode == "delete"
        conn.commit()
    raw = db.read_bytes()  # acquisition belongs to the test, not the probe
    assert raw[:len(_HEADER)] == _HEADER
    assert raw[18:20] == b"\x01\x01"
    return db, raw


def test_real_v2_rollback_image_is_consumed_without_sqlite_file_vfs(
    tmp_path, monkeypatch
):
    db, raw = _synthetic_v2_rollback_image(tmp_path)
    calls = []
    sqlite_connect = sqlite3.connect

    def connect_guard(database, *args, **kwargs):
        calls.append(database)
        assert database == ":memory:", "never open the fixture DB in the probe"
        return sqlite_connect(database, *args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", connect_guard)
    try:
        result = _inspect_memory_image(raw)
    finally:
        monkeypatch.setattr(sqlite3, "connect", sqlite_connect)
    assert calls == [":memory:"]
    assert db.exists()
    assert result.decision == _DECISION
    assert result.db_schema_version == PROJECT_STATE_DB_VERSION
    assert result.runs_count == 0
    assert not any((
        result.source_origin_proven, result.cross_store_epoch_proven,
        result.source_capture_nonmutation_proven,
        result.authenticated_custody_proven, result.current_state_proven,
        result.authorizes_collector_or_cli,
    ))


def test_file_can_be_removed_after_explicit_byte_acquisition(tmp_path):
    db, raw = _synthetic_v2_rollback_image(tmp_path)
    db.unlink()
    assert not db.exists()
    assert _inspect_memory_image(raw).decision == _DECISION
    assert not list(tmp_path.glob("*.sqlite-*"))


def test_memory_only_consumer_does_not_touch_source_metadata_after_acquisition(
    tmp_path,
):
    db, raw = _synthetic_v2_rollback_image(tmp_path)
    before = db.stat()
    assert _inspect_memory_image(raw).runs_count == 0
    after = db.stat()
    # Includes atime. This says NOTHING about the prior acquisition read.
    assert (before.st_dev, before.st_ino, before.st_size,
            before.st_atime_ns, before.st_mtime_ns, before.st_ctime_ns) == (
            after.st_dev, after.st_ino, after.st_size,
            after.st_atime_ns, after.st_mtime_ns, after.st_ctime_ns)


def test_real_active_wal_header_is_refused_before_deserialize(tmp_path, monkeypatch):
    db = tmp_path / "synthetic-active-wal.sqlite"
    writer = sqlite3.connect(db)
    try:
        assert writer.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"
        writer.execute("CREATE TABLE marker (value INTEGER)")
        writer.execute("INSERT INTO marker VALUES (1)")
        writer.commit()
        raw = db.read_bytes()  # test-owned fixture only, NOT a snapshot proof
        assert raw[18:20] == b"\x02\x02"
        calls = []
        original = sqlite3.connect

        def guarded_connect(*args, **kwargs):
            calls.append(args)
            return original(*args, **kwargs)

        monkeypatch.setattr(sqlite3, "connect", guarded_connect)
        with pytest.raises(InputRefused, match="WAL_OR_UNSUPPORTED_JOURNAL_IMAGE"):
            _inspect_memory_image(raw)
        assert calls == []
    finally:
        writer.close()


@pytest.mark.parametrize("corruption", [
    b"",
    b"not sqlite",
    b"SQLite format 3\x00",
])
def test_invalid_image_rejected_without_file_access(corruption, monkeypatch):
    def should_not_connect(*args, **kwargs):
        raise AssertionError("must reject before any SQLite VFS access")

    monkeypatch.setattr(sqlite3, "connect", should_not_connect)
    with pytest.raises(InputRefused, match="INVALID_OR_UNBOUNDED_INPUT_IMAGE"):
        _inspect_memory_image(corruption)


def test_bounded_image_refuses_before_sqlite_connection(monkeypatch):
    def should_not_connect(*args, **kwargs):
        raise AssertionError("unbounded input must not open SQLite")

    monkeypatch.setattr(sqlite3, "connect", should_not_connect)
    raw = _HEADER + b"\x00" * _MAX_IMAGE_BYTES
    with pytest.raises(InputRefused, match="INVALID_OR_UNBOUNDED_INPUT_IMAGE"):
        _inspect_memory_image(raw)


@pytest.mark.parametrize(("pragma", "value"), [
    ("user_version", "99"),
    ("application_id", "0"),
])
def test_unrecognized_source_identity_refused(tmp_path, pragma, value):
    db, _ = _synthetic_v2_rollback_image(tmp_path)
    with closing(sqlite3.connect(db)) as conn:
        conn.execute(f"PRAGMA {pragma} = {value}")
        conn.commit()
    with pytest.raises(InputRefused, match="UNSUPPORTED_SOURCE_SCHEMA"):
        _inspect_memory_image(db.read_bytes())


def test_malformed_header_valid_shape_fails_closed(tmp_path):
    _, raw = _synthetic_v2_rollback_image(tmp_path)
    # Still has the SQLite magic and rollback markers, but not enough
    # valid database pages to contain the expected schema.
    with pytest.raises(InputRefused, match="INVALID_SOURCE_CONTENT"):
        _inspect_memory_image(raw[:512])


def test_deserialize_unavailable_is_explicit_refusal(tmp_path, monkeypatch):
    _, raw = _synthetic_v2_rollback_image(tmp_path)

    class MissingDeserialize:
        def close(self):
            pass

    monkeypatch.setattr(sqlite3, "connect",
                        lambda *args, **kwargs: MissingDeserialize())
    with pytest.raises(InputRefused, match="MEMORY_DESERIALIZE_UNAVAILABLE"):
        _inspect_memory_image(raw)


def test_same_bytes_deterministic_but_no_attestation_or_cli(tmp_path):
    _, raw = _synthetic_v2_rollback_image(tmp_path)
    a = _inspect_memory_image(raw)
    b = _inspect_memory_image(raw)
    assert a == b
    assert a.decision.endswith("LAB_ONLY")
    assert not a.cross_store_epoch_proven
    assert not a.current_state_proven
    assert not a.authorizes_collector_or_cli
