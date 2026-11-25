"""G10 D1: WAL-to-rollback diagnostic bridge on generated fixtures only.

The parent creates and controls every writer action. It retains a byte
inventory and expected logical outcome outside the child normalization
workspace. The child is a separate process, NOT an independent security
principal or sandbox. No source project, importer, or runtime API is added.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import sqlite3
import stat
import subprocess
import sys
from contextlib import closing, contextmanager
from pathlib import Path

import pytest

from scripts import m6a_g4_stdin_preview as g4
from scripts.bdiag_detached_input_lab import PROJECT, RUN
from scripts.m6a_g2_private_byte_diagnostic import G2Refused
from test_m60bdiag_detached_input_gate import _source, _SECRET

pytestmark = pytest.mark.skipif(
    not sys.platform.startswith("linux") or not all(
        hasattr(os, flag) for flag in ("O_NOATIME", "O_NOFOLLOW", "geteuid")
    ) or os.geteuid() == 0,
    reason="G10-D1 requires ordinary nonroot Linux and test-owned fixtures",
)
_DB_LIMIT = 16 * 1024 * 1024
_CONTEXT_LIMIT = 2 * 1024 * 1024
_EVENT_TIME = "2026-10-19T08:01:00+00:00"
_EVENT_TYPE = "run.transition"
_PAYLOAD = '{"private":"G10_WAL_ONLY_PRIVATE_PAYLOAD"}'

# Fixed test subprocess. Its only on-disk input is the fixed filename inside
# the fresh, test-owned working directory. No original source path is passed.
# A separate interpreter does not itself enforce an OS security boundary.
_NORMALIZER = """
import sqlite3
from contextlib import closing

with closing(sqlite3.connect("clone.sqlite", timeout=0.5)) as conn:
    conn.execute("PRAGMA trusted_schema=OFF")
    assert conn.execute("PRAGMA application_id").fetchone()[0] == 0x50544354
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 2
    assert conn.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
    assert conn.execute("PRAGMA journal_mode=DELETE").fetchone()[0] == "delete"
    assert conn.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
"""


def _identity(st):
    return (st.st_dev, st.st_ino, st.st_mode, st.st_nlink, st.st_size,
            st.st_mtime_ns, st.st_ctime_ns, st.st_atime_ns)


def _sample_leaf(path: Path, limit: int = _DB_LIMIT):
    """Bounded fixture observation without a plain-read atime fallback."""
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NOATIME
                 | os.O_CLOEXEC | os.O_NONBLOCK)
    try:
        before = os.fstat(fd)
        assert stat.S_ISREG(before.st_mode)
        assert before.st_uid == os.geteuid() and before.st_nlink == 1
        assert 0 < before.st_size <= limit
        chunks = []
        remaining = before.st_size
        while remaining:
            chunk = os.read(fd, min(remaining, 64 * 1024))
            assert chunk
            chunks.append(chunk)
            remaining -= len(chunk)
        assert os.read(fd, 1) == b""
        assert _identity(os.fstat(fd)) == _identity(before)
        assert _identity(path.lstat()) == _identity(before)
        return b"".join(chunks), _identity(before)
    finally:
        os.close(fd)


def _sidecar(db, suffix):
    return db.with_name(db.name + suffix)


def _source_sample(db, context):
    # No enumeration or SQLite connection is made by this observer.
    paths = (db, _sidecar(db, "-wal"), _sidecar(db, "-shm"), context)
    leaves = tuple(_sample_leaf(path, _CONTEXT_LIMIT if path == context
                                else _DB_LIMIT) for path in paths)
    parents = tuple(_identity(path.lstat()) for path in
                    (db.parent, context.parent))
    assert not _sidecar(db, "-journal").exists()
    return leaves, parents


def _append_event(conn):
    cursor = conn.execute(
        "INSERT INTO run_events(run_id,created_at,event_type,payload_json)"
        " VALUES(?,?,?,?)",
        (RUN, _EVENT_TIME, _EVENT_TYPE, _PAYLOAD),
    )
    conn.commit()
    return cursor.lastrowid


def _digest_pair(pair):
    return tuple(hashlib.sha256(raw).hexdigest() for raw in pair)


@contextmanager
def _fixture(tmp_path):
    root = _source(tmp_path / "origin")
    db = root / ".projectctl/state.sqlite"
    context = root / ".projectctl/runs" / RUN / "context-manifest.json"
    base = _sample_leaf(db)[0]
    assert base[18:20] == b"\x01\x01"
    # Independent construction of the expected logical rollback result:
    # take the original rollback image and execute the same known test event.
    oracle_dir = tmp_path / "oracle"
    oracle_dir.mkdir(mode=0o700)
    oracle = oracle_dir / "expected.sqlite"
    oracle.write_bytes(base)
    oracle.chmod(0o600)
    with closing(sqlite3.connect(oracle)) as conn:
        assert conn.execute("PRAGMA journal_mode=DELETE").fetchone()[0] == "delete"
        event_id = _append_event(conn)
    expected = oracle.read_bytes()

    with closing(sqlite3.connect(db)) as writer:
        assert writer.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"
        writer.execute("PRAGMA wal_autocheckpoint=0")
        assert writer.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()[0] == 0
        before_commit = _sample_leaf(db)[0]
        assert before_commit[18:20] == b"\x02\x02"
        assert _append_event(writer) == event_id
        sample = _source_sample(db, context)
        leaves, _ = sample
        raw_db, raw_wal, _, raw_context = (item[0] for item in leaves)
        # The only new commit is in the WAL, not in the main DB bytes.
        assert raw_db == before_commit and len(raw_wal) > 32
        pair = (raw_db, raw_wal, raw_context)
        pinned = _digest_pair(pair)
        # Hold the controlled writer idle until observation is complete;
        # no production quiescence or hostile-writer exclusion is proved.
        yield db, context, sample, pair, pinned, base, expected, event_id


def _stage_and_normalize(work: Path, raw_db: bytes, raw_wal: bytes | None):
    """Test helper only, with a fresh directory and fixed child code."""
    work.mkdir(mode=0o700)
    db = work / "clone.sqlite"
    db.write_bytes(raw_db)
    db.chmod(0o600)
    if raw_wal is not None:
        wal = _sidecar(db, "-wal")
        wal.write_bytes(raw_wal)
        wal.chmod(0o600)
    result = subprocess.run(
        [sys.executable, "-I", "-c", _NORMALIZER],
        cwd=work, capture_output=True, timeout=20, check=False,
    )
    assert result.returncode == 0, "synthetic clone normalization failed"
    assert result.stdout == b""
    assert not any(_sidecar(db, suffix).exists()
                   for suffix in ("-wal", "-shm", "-journal"))
    normalized = db.read_bytes()
    assert normalized[18:20] == b"\x01\x01"
    assert len(normalized) <= _DB_LIMIT
    return normalized


def _normalize_pinned(work, pair, pinned):
    # This is an external *fixture* control, never a source admission gate.
    # A missing/truncated/replaced candidate is distinguishable only because
    # the test retained the expected raw identity before the mutation.
    if (len(pair) != 3 or any(type(raw) is not bytes or not raw
                              for raw in pair)
            or len(pair[0]) > _DB_LIMIT or len(pair[1]) > _DB_LIMIT
            or len(pair[2]) > _CONTEXT_LIMIT
            or _digest_pair(pair) != pinned):
        raise ValueError("FIXTURE_RAW_IDENTITY_MISMATCH")
    return _stage_and_normalize(work, pair[0], pair[1])


def _wire(db, context):
    def b64(raw):
        return base64.b64encode(raw).decode("ascii")
    return json.dumps({
        "format": g4._INPUT_FORMAT,
        "project_id": PROJECT,
        "run_id": RUN,
        "db_b64": b64(db),
        "artifacts_b64": {
            "context_manifest": b64(context),
            "verification_manifest": None,
            "evidence_manifest": None,
        },
    }, sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n"


def _preview(db, context):
    rendered = g4.render_supplied_wire(_wire(db, context))
    data = json.loads(rendered)
    assert data["source_origin"] == "UNATTESTED"
    assert data["cross_store_epoch"] == "UNATTESTED"
    assert data["source_current"] == "UNKNOWN"
    assert data["source_capture_nonmutation"] == "UNPROVEN"
    assert data["authenticated_custody"] == "UNPROVEN"
    assert data["assessment_authority"] == "NONE"
    assert data["authorizes_export_cli"] is False
    assert data["authorizes_retry"] is False
    assert data["trace"]["completeness"] == "incomplete"
    assert data["trace"]["assessments"] == []
    assert _SECRET.encode() not in rendered
    assert b"G10_WAL_ONLY_PRIVATE_PAYLOAD" not in rendered
    return rendered, data


def test_wal_clone_bridge_preserves_known_commit_and_exact_g4_preview(tmp_path):
    with _fixture(tmp_path) as (
        db, context, sample, pair, pinned, base, expected, event_id
    ):
        old_wire, old = _preview(base, pair[2])
        wanted_wire, wanted = _preview(expected, pair[2])
        assert len(wanted["trace"]["events"]) == len(old["trace"]["events"]) + 1
        assert wanted["trace"]["events"][-1]["sequence"] == event_id
        assert old_wire != wanted_wire

        # Observe the actual G2/G4 refusal before any supported normalization.
        with pytest.raises(G2Refused, match="UNSUPPORTED_WAL_INPUT"):
            g4.render_supplied_wire(_wire(pair[0], pair[2]))

        normalized = _normalize_pinned(tmp_path / "normalization", pair, pinned)
        actual, data = _preview(normalized, pair[2])
        assert actual == wanted_wire
        assert _preview(normalized, pair[2])[0] == actual
        assert data["trace"]["events"][-1]["sequence"] == event_id
        # The raw retained candidate and original fixture are unchanged at
        # observation boundaries. No full-window source-nonmutation proof.
        assert _digest_pair(pair) == pinned
        assert _source_sample(db, context) == sample


@pytest.mark.parametrize("fault", ["missing", "truncated", "altered"])
def test_fixture_pin_rejects_changed_wal_before_child_start(
    tmp_path, monkeypatch, fault
):
    with _fixture(tmp_path) as (db, context, sample, pair, pinned, *_):
        wal = pair[1]
        broken = {
            "missing": None,
            "truncated": wal[:-1],
            "altered": wal[:-1] + bytes([wal[-1] ^ 1]),
        }[fault]
        work = tmp_path / "must-not-create"

        def forbidden(*args, **kwargs):
            raise AssertionError("must not invoke SQLite normalization")

        monkeypatch.setattr(subprocess, "run", forbidden)
        with pytest.raises(ValueError, match="^FIXTURE_RAW_IDENTITY_MISMATCH$"):
            _normalize_pinned(work, (pair[0], broken, pair[2]), pinned)
        assert not work.exists()
        assert _source_sample(db, context) == sample


def test_unsafe_db_only_clone_can_be_readable_but_lose_known_commit(tmp_path):
    # Negative control deliberately bypasses the fixture pin on generated
    # bytes. This is NOT a proposed reader path. SQLite integrity alone is
    # not evidence that all committed WAL frames were included in a copy.
    with _fixture(tmp_path) as (
        db, context, sample, pair, pinned, base, expected, event_id
    ):
        stale = _stage_and_normalize(tmp_path / "negative-db-only", pair[0], None)
        stale_preview, stale_data = _preview(stale, pair[2])
        assert stale_preview == _preview(base, pair[2])[0]
        assert stale_preview != _preview(expected, pair[2])[0]
        assert event_id not in [item["sequence"]
                                for item in stale_data["trace"]["events"]]
        assert _digest_pair(pair) == pinned
        assert _source_sample(db, context) == sample
