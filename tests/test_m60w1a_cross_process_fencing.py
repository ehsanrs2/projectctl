"""M6.0 W1a: TWO-PROCESS fencing proof on disposable real v2 project DBs.

TEST-ONLY lab: the extra w1a_epochs table is not a ProjectCTL migration.
The fixed JSON leaf is a dummy payload, not a Verification/Evidence Manifest.
No production writer/RunStore methods, schema or exporter are modified.
"""
from __future__ import annotations

import fcntl
import multiprocessing
import os
import secrets
import sqlite3
import stat
import tempfile
from contextlib import closing, contextmanager
from pathlib import Path

import pytest

from projectctl.storage.sqlite import (
    APPLICATION_ID,
    PROJECT_STATE_DB_VERSION,
    initialize_project_state_db,
    inspect_db,
)

pytestmark = pytest.mark.skipif(
    os.name != "posix" or not hasattr(os, "O_NOFOLLOW")
    or not hasattr(fcntl, "flock"),
    reason="W1a lab requires local POSIX advisory flock",
)

_RUN = "test-run"
_OWNER = "same-host:same-pid-label"
_NOW = 1000
_MAX_GENERATION = (1 << 63) - 1


class W1aRefused(ValueError):
    pass


def _connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path, isolation_level=None, timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


@contextmanager
def _mutex(lock: Path, *, nonblocking: bool = False):
    # Lab fixture path is under a trusted disposable tmp_path. Production
    # requires descriptor-anchored directory traversal and parent checks.
    fd = os.open(lock, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise W1aRefused("unsafe_lock_leaf")
        flags = fcntl.LOCK_EX | (fcntl.LOCK_NB if nonblocking else 0)
        fcntl.flock(fd, flags)
        try:
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    root = tmp_path / "disposable"
    db = root / ".projectctl" / "state.sqlite"
    initialize_project_state_db(db)
    lock_dir = root / ".projectctl" / "locks"
    lock_dir.mkdir(exist_ok=True)
    # This table is created ONLY in a disposable v2 DB, never registered in
    # storage/sqlite.py and never queried by production RunStore methods.
    with closing(_connect(db)) as conn:
        conn.execute("""
            CREATE TABLE w1a_epochs (
                run_id TEXT PRIMARY KEY,
                owner TEXT NOT NULL,
                generation INTEGER NOT NULL CHECK(generation>=0),
                token TEXT,
                expires_at INTEGER NOT NULL,
                status TEXT NOT NULL,
                publications INTEGER NOT NULL DEFAULT 0
            )
        """)
        conn.execute(
            "INSERT INTO w1a_epochs VALUES (?, ?, 0, NULL, 0, 'verifying', 0)",
            (_RUN, "none"),
        )
    assert inspect_db(db) == (APPLICATION_ID, 2)
    return db, lock_dir / "w1a-run.lock", root / "w1a-evidence.json"


def _grant(db: Path, lock: Path, *, owner: str = _OWNER, now: int = _NOW):
    # Crucially, BOTH lease takeover and artifact publication use the SAME
    # mutex. A DB-only lease CAS cannot fence the filesystem gap.
    with _mutex(lock):
        conn = _connect(db)
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT generation FROM w1a_epochs WHERE run_id=?", (_RUN,),
            ).fetchone()
            if row is None or row["generation"] >= _MAX_GENERATION:
                raise W1aRefused("generation_unavailable")
            generation = row["generation"] + 1
            token = secrets.token_hex(16)
            count = conn.execute(
                "UPDATE w1a_epochs SET generation=?, token=?, owner=?, "
                "expires_at=? WHERE run_id=? AND generation=? "
                "AND status='verifying'",
                (generation, token, owner, now + 300, _RUN, row["generation"]),
            ).rowcount
            if count != 1:
                raise W1aRefused("lease_grant_conflict")
            conn.commit()
            return generation, token
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()


def _validate(conn, generation, token, now):
    row = conn.execute(
        "SELECT 1 FROM w1a_epochs WHERE run_id=? AND generation=? "
        "AND token=? AND expires_at>? AND status='verifying'",
        (_RUN, generation, token, now),
    ).fetchone()
    if row is None:
        raise W1aRefused("stale_lease_epoch")


def _heartbeat(db, generation, token, now=_NOW):
    conn = _connect(db)
    try:
        conn.execute("BEGIN IMMEDIATE")
        rowcount = conn.execute(
            "UPDATE w1a_epochs SET expires_at=? WHERE run_id=? "
            "AND generation=? AND token=? AND expires_at>? "
            "AND status='verifying'",
            (now + 300, _RUN, generation, token, now),
        ).rowcount
        if rowcount != 1:
            raise W1aRefused("stale_lease_epoch")
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def _release(db, generation, token, now=_NOW):
    conn = _connect(db)
    try:
        conn.execute("BEGIN IMMEDIATE")
        rowcount = conn.execute(
            "UPDATE w1a_epochs SET token=NULL, expires_at=0 WHERE run_id=? "
            "AND generation=? AND token=? AND expires_at>?",
            (_RUN, generation, token, now),
        ).rowcount
        if rowcount != 1:
            raise W1aRefused("stale_lease_epoch")
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def _publish_under_lock(
    db, evidence, generation, token, now=_NOW, *, paused_pipe=None, fault=False
):
    lock = evidence.parent / ".projectctl" / "locks" / "w1a-run.lock"
    with _mutex(lock):
        # Short independent DB read, not an SQLite write transaction held
        # across filesystem fsync. Takeover also takes this mutex.
        conn = _connect(db)
        try:
            conn.execute("BEGIN")
            _validate(conn, generation, token, now)
            conn.rollback()
        finally:
            conn.close()

        if paused_pipe is not None:
            paused_pipe.send("artifact_mutex_held")
            command = paused_pipe.recv()
            if command != "continue":
                raise W1aRefused("aborted_publication")

        if fault:
            raise W1aRefused("injected_before_publication")

        fd, staging = tempfile.mkstemp(
            prefix=".w1a-", suffix=".json", dir=evidence.parent
        )
        try:
            with os.fdopen(fd, "wb") as out:
                out.write(b'{"dummy": "fenced"}\n')
                out.flush()
                os.fsync(out.fileno())
            os.replace(staging, evidence)
            parentfd = os.open(
                evidence.parent,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
            )
            try:
                os.fsync(parentfd)
            finally:
                os.close(parentfd)
        finally:
            Path(staging).unlink(missing_ok=True)

        conn = _connect(db)
        try:
            conn.execute("BEGIN IMMEDIATE")
            _validate(conn, generation, token, now)
            count = conn.execute(
                "UPDATE w1a_epochs SET publications=publications+1 "
                "WHERE run_id=? AND generation=? AND token=? "
                "AND expires_at>? AND status='verifying'",
                (_RUN, generation, token, now),
            ).rowcount
            if count != 1:
                raise W1aRefused("stale_lease_epoch")
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()


def _state(db):
    with closing(_connect(db)) as conn:
        row = conn.execute(
            "SELECT generation, token, expires_at, publications "
            "FROM w1a_epochs WHERE run_id=?", (_RUN,),
        ).fetchone()
        return tuple(row)


def _worker_initial(db, lock, pipe):
    try:
        grant = _grant(Path(db), Path(lock))
        pipe.send(("initial", grant))
        if pipe.recv() != "attempt_stale":
            return
        denied = []
        try:
            _heartbeat(Path(db), *grant)
        except W1aRefused as exc:
            denied.append(str(exc))
        try:
            _release(Path(db), *grant)
        except W1aRefused as exc:
            denied.append(str(exc))
        try:
            _publish_under_lock(
                Path(db),
                Path(db).parent.parent / "w1a-evidence.json",
                *grant,
            )
        except W1aRefused as exc:
            denied.append(str(exc))
        pipe.send(("stale_denials", denied))
    except BaseException as exc:
        pipe.send(("error", type(exc).__name__))


def _worker_paused(db, evidence, generation, token, pipe):
    try:
        _publish_under_lock(
            Path(db), Path(evidence), generation, token, paused_pipe=pipe
        )
        pipe.send("published")
    except BaseException as exc:
        pipe.send("error:" + type(exc).__name__)


def _worker_takeover(db, lock, pipe):
    try:
        pipe.send("started")
        value = _grant(Path(db), Path(lock))
        pipe.send(("granted", value))
    except BaseException as exc:
        pipe.send(("error", type(exc).__name__))


def _worker_hold_lock_then_exit(lock, pipe):
    with _mutex(Path(lock)):
        pipe.send("held")
        if pipe.recv() != "crash":
            return
        os._exit(23)


def _receive(pipe, timeout=12):
    if not pipe.poll(timeout):
        raise AssertionError("child_process_timeout")
    return pipe.recv()


def _join_or_kill(process):
    process.join(timeout=10)
    if process.is_alive():
        process.terminate()
        process.join(timeout=5)
    assert not process.is_alive()


def test_two_process_same_owner_reacquisition_blocks_old_heartbeat_release_and_files(
    tmp_path,
):
    db, lock, evidence = _fixture(tmp_path)
    ctx = multiprocessing.get_context("spawn")
    parent, child = ctx.Pipe()
    writer_a = ctx.Process(target=_worker_initial, args=(str(db), str(lock), child))
    writer_a.start()
    try:
        label, first = _receive(parent)
        assert label == "initial"
        assert first[0] == 1
        second = _grant(db, lock, owner=_OWNER)
        assert second[0] == 2 and second[1] != first[1]
        _publish_under_lock(db, evidence, *second)
        baseline = (evidence.read_bytes(), _state(db))
        parent.send("attempt_stale")
        label, denied = _receive(parent)
        assert label == "stale_denials"
        assert denied == ["stale_lease_epoch"] * 3
        assert (evidence.read_bytes(), _state(db)) == baseline
    finally:
        _join_or_kill(writer_a)
        parent.close()
        child.close()


def test_takeover_waits_while_other_process_publishes_under_same_mutex(tmp_path):
    db, lock, evidence = _fixture(tmp_path)
    first = _grant(db, lock)
    ctx = multiprocessing.get_context("spawn")
    parent_a, child_a = ctx.Pipe()
    parent_b, child_b = ctx.Pipe()
    writer_a = ctx.Process(
        target=_worker_paused,
        args=(str(db), str(evidence), first[0], first[1], child_a),
    )
    writer_b = ctx.Process(
        target=_worker_takeover, args=(str(db), str(lock), child_b)
    )
    writer_a.start()
    try:
        assert _receive(parent_a) == "artifact_mutex_held"
        writer_b.start()
        assert _receive(parent_b) == "started"
        # Process B must not acquire the new epoch while A owns the mutex.
        assert not parent_b.poll(0.3)
        assert _state(db)[0] == first[0]
        parent_a.send("continue")
        assert _receive(parent_a) == "published"
        label, new_lease = _receive(parent_b)
        assert label == "granted"
        assert new_lease[0] == first[0] + 1
        assert _state(db)[3] == 1
        assert evidence.read_bytes() == b'{"dummy": "fenced"}\n'
        with pytest.raises(W1aRefused, match="stale_lease_epoch"):
            _publish_under_lock(db, evidence, *first)
    finally:
        _join_or_kill(writer_a)
        if writer_b.pid is not None:
            _join_or_kill(writer_b)
        parent_a.close()
        child_a.close()
        parent_b.close()
        child_b.close()


def test_process_crash_releases_flock_without_unlinking_inode(tmp_path):
    db, lock, _ = _fixture(tmp_path)
    ctx = multiprocessing.get_context("spawn")
    parent, child = ctx.Pipe()
    process = ctx.Process(target=_worker_hold_lock_then_exit, args=(str(lock), child))
    process.start()
    try:
        assert _receive(parent) == "held"
        inode = lock.stat().st_ino
        with pytest.raises(BlockingIOError):
            with _mutex(lock, nonblocking=True):
                raise AssertionError("should_not_acquire")
        parent.send("crash")
        _join_or_kill(process)
        assert process.exitcode == 23
        with _mutex(lock, nonblocking=True):
            assert lock.stat().st_ino == inode
        assert PROJECT_STATE_DB_VERSION == 2
        assert inspect_db(db) == (APPLICATION_ID, 2)
    finally:
        if process.is_alive():
            _join_or_kill(process)
        parent.close()
        child.close()


def test_released_and_expired_epochs_cannot_heartbeat_or_publish(tmp_path):
    db, lock, evidence = _fixture(tmp_path)
    first = _grant(db, lock)
    _release(db, *first)
    with pytest.raises(W1aRefused, match="stale_lease_epoch"):
        _heartbeat(db, *first)
    with pytest.raises(W1aRefused, match="stale_lease_epoch"):
        _publish_under_lock(db, evidence, *first)
    second = _grant(db, lock)
    with pytest.raises(W1aRefused, match="stale_lease_epoch"):
        _heartbeat(db, *second, now=_NOW + 301)
    with pytest.raises(W1aRefused, match="stale_lease_epoch"):
        _publish_under_lock(db, evidence, *second, now=_NOW + 301)
    assert not evidence.exists()
    assert _state(db)[3] == 0


def test_injected_prepublication_failure_keeps_file_unmodified(tmp_path):
    db, lock, evidence = _fixture(tmp_path)
    lease = _grant(db, lock)
    baseline = _state(db)
    with pytest.raises(W1aRefused, match="injected_before_publication"):
        _publish_under_lock(db, evidence, *lease, fault=True)
    assert not evidence.exists()
    assert _state(db) == baseline


def test_db_only_takeover_cannot_be_assumed_to_fence_file_write_gap(tmp_path):
    # A conscious negative model: a bypassing writer can alter the table
    # without taking the artifact mutex. Therefore all lease grant/regrant,
    # rebind and relevant file writers must cooperate in any real W1 design.
    db, lock, evidence = _fixture(tmp_path)
    old = _grant(db, lock)
    with _mutex(lock):
        with closing(_connect(db)) as conn:
            conn.execute("BEGIN")
            _validate(conn, *old, _NOW)
            conn.rollback()
        # Simulated non-participant: takes over only in SQLite.
        with closing(_connect(db)) as conn:
            conn.execute(
                "UPDATE w1a_epochs SET generation=generation+1, token=? "
                "WHERE run_id=?", ("nonparticipating-token", _RUN),
            )
        # The old validation is now stale BEFORE any file publication.
        assert _state(db)[0] == old[0] + 1
        # This is precisely why the protocol MUST guard ALL owner transfers:
        # never publish based solely on the earlier validation.
    with pytest.raises(W1aRefused, match="stale_lease_epoch"):
        _publish_under_lock(db, evidence, *old)
    assert not evidence.exists()
