"""M6.0 W1c: bounded disposable as-of Seal + fault-window experiment.

TEST-ONLY. Neither ProjectCTL's real v2 RunStore nor a production writer is
used; all state lives under pytest tmp_path. A successful outcome is a
conditional fixture observation, never an authenticated P0/P1 witness.
W1a already tests true interprocess fencing; W1b proves real v2 lacks it.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import multiprocessing
import os
from contextlib import contextmanager, closing
from pathlib import Path
import sqlite3
import stat
import tempfile

import pytest


pytestmark = pytest.mark.skipif(
    os.name != "posix" or not all(hasattr(os, name) for name in
                                 ("O_NOFOLLOW", "O_DIRECTORY")),
    reason="W1c disposable lock and durability model requires POSIX",
)

_RUN = "synthetic-run"
_STATUS_PRE = "verifying"
_STATUS_POST = "ready_to_integrate"
_NAMES = ("verification-manifest.json", "evidence-manifest.json")
_NOW = 100
_SUCCESS = "W1C_DISPOSABLE_FIXTURE_ONLY"
_REFUSE_NO_SEAL = "REFUSE_NO_COMMITTED_SEAL"
_REFUSE_COHERENCE = "REFUSE_UNBOUND_STATUS_EVENTS"
_REFUSE_EXACT_BYTES = "REFUSE_EXACT_HISTORICAL_BYTES_UNAVAILABLE"
_REFUSE_CURRENT = "REFUSE_UNPROVEN_CURRENT"
_REFUSE_STALE = "REFUSE_STALE_GENERATION_TOKEN"
_REFUSE_EPOCH = "REFUSE_MIXED_LEAF_EPOCH"
_REFUSE_RETRY = "REFUSE_ALREADY_COMMITTED_NO_RETRY"


class Refused(ValueError):
    pass


class InjectedCrash(RuntimeError):
    """A deterministic fault window; NOT a physical power-cut simulation."""


def _hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _payloads(epoch: int) -> tuple[bytes, bytes]:
    # Deliberately *not* the production verification/evidence schema.
    return tuple(
        (json.dumps({"dummy_kind": kind, "epoch": epoch},
                    sort_keys=True, separators=(",", ":")) + "\n").encode()
        for kind in ("verification", "evidence")
    )


def _connect(root: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(root / "synthetic-authority.sqlite3",
                           isolation_level=None, timeout=3.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=3000")
    conn.execute("PRAGMA synchronous=FULL")
    return conn


def _fixture(tmp_path: Path) -> Path:
    root = tmp_path / "w1c-disposable"
    root.mkdir(mode=0o700)
    db = root / "synthetic-authority.sqlite3"
    with closing(sqlite3.connect(db)) as conn:
        assert conn.execute("PRAGMA journal_mode=DELETE").fetchone()[0] == "delete"
        conn.executescript("""
            CREATE TABLE run (
                run_id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                owner TEXT NOT NULL,
                generation INTEGER NOT NULL,
                token TEXT NOT NULL,
                expires_at INTEGER NOT NULL
            );
            CREATE TABLE event (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                generation INTEGER NOT NULL
            );
            CREATE TABLE seal (
                run_id TEXT PRIMARY KEY,
                epoch INTEGER NOT NULL,
                generation INTEGER NOT NULL,
                verification_event_id INTEGER NOT NULL,
                transition_event_id INTEGER NOT NULL,
                verification_sha256 TEXT NOT NULL,
                evidence_sha256 TEXT NOT NULL
            );
        """)
        conn.execute("INSERT INTO run VALUES (?, ?, ?, 0, '', 0)",
                     (_RUN, _STATUS_PRE, "none"))
        conn.commit()  # closing() alone does not commit the seed transaction
    return root


@contextmanager
def _mutex(root: Path):
    # Trusted test fixture directory only: real P0 needs independently
    # constrained dirfds, start-origin embargo and open-FD alias exclusion.
    fd = os.open(root / "stable-w1c.lock",
                 os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        assert stat.S_ISREG(os.fstat(fd).st_mode)
        fcntl.flock(fd, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def _grant(root: Path, owner: str = "reused-owner") -> tuple[int, str]:
    # Models acquisition uniqueness even if the textual owner is reused.
    with _mutex(root), closing(_connect(root)) as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT generation, status FROM run WHERE run_id=?",
                           (_RUN,)).fetchone()
        if row["status"] != _STATUS_PRE:
            conn.rollback()
            raise Refused(_REFUSE_RETRY)
        generation = row["generation"] + 1
        token = "fixture-token-" + str(generation)
        conn.execute("UPDATE run SET owner=?, generation=?, token=?, "
                     "expires_at=? WHERE run_id=? AND generation=?",
                     (owner, generation, token, _NOW + 300, _RUN,
                      row["generation"]))
        conn.commit()
    return generation, token


def _check_lease(conn: sqlite3.Connection, grant: tuple[int, str]) -> None:
    row = conn.execute(
        "SELECT status FROM run WHERE run_id=? AND generation=? "
        "AND token=? AND expires_at>?",
        (_RUN, grant[0], grant[1], _NOW),
    ).fetchone()
    if row is None or row["status"] != _STATUS_PRE:
        raise Refused(_REFUSE_STALE)


def _fsync_parent(root: Path, observation: list[str]) -> None:
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
        observation.append("directory_fsync")
    finally:
        os.close(fd)


def _publish(
    root: Path,
    grant: tuple[int, str],
    payloads: tuple[bytes, bytes],
    *,
    epoch: int = 1,
    fault: str | None = None,
    observation: list[str] | None = None,
) -> tuple[str, ...]:
    """One participating-writer model; fault windows are deterministic.

    The stable mutex covers *both* file replacement and DB transition.
    The SQL transaction covers status + TWO events + Seal (no split commit).
    """
    steps = [] if observation is None else observation
    with _mutex(root):
        with closing(_connect(root)) as conn:
            _check_lease(conn, grant)

        if len(payloads) != 2 or any(type(p) is not bytes for p in payloads):
            raise Refused("REFUSE_BAD_ARTIFACT_INPUT")
        try:
            ep = tuple(json.loads(p)["epoch"] for p in payloads)
        except (ValueError, KeyError, TypeError):
            raise Refused(_REFUSE_EPOCH) from None
        if (type(epoch) is not int or type(ep[0]) is not int
                or type(ep[1]) is not int or ep != (epoch, epoch)):
            raise Refused(_REFUSE_EPOCH)

        for name, raw in zip(_NAMES, payloads):
            fd, temp = tempfile.mkstemp(prefix=".w1c-staging-", dir=root)
            try:
                with os.fdopen(fd, "wb") as out:
                    out.write(raw)
                    out.flush()
                    if fault == "before_file_fsync":
                        raise InjectedCrash("before_file_fsync")
                    os.fsync(out.fileno())
                    steps.append("file_fsync")
                os.replace(temp, root / name)
                steps.append("replace")
                if fault == "after_replace_before_dir_fsync":
                    raise InjectedCrash("after_replace_before_dir_fsync")
                _fsync_parent(root, steps)
            finally:
                Path(temp).unlink(missing_ok=True)

        if fault == "before_begin":
            raise InjectedCrash("before_begin")
        assert steps == ["file_fsync", "replace", "directory_fsync"] * 2

        with closing(_connect(root)) as conn:
            try:
                conn.execute("BEGIN IMMEDIATE")
                steps.append("begin_immediate")
                _check_lease(conn, grant)
                changed = conn.execute(
                    "UPDATE run SET status=? WHERE run_id=? AND status=? "
                    "AND generation=? AND token=? AND expires_at>?",
                    (_STATUS_POST, _RUN, _STATUS_PRE, *grant, _NOW),
                ).rowcount
                if changed != 1:
                    raise Refused(_REFUSE_STALE)
                first = conn.execute(
                    "INSERT INTO event (run_id, event_type, generation) "
                    "VALUES (?, 'verification.passed', ?)",
                    (_RUN, grant[0]),
                ).lastrowid
                second = conn.execute(
                    "INSERT INTO event (run_id, event_type, generation) "
                    "VALUES (?, 'run.transition', ?)",
                    (_RUN, grant[0]),
                ).lastrowid
                if fault == "after_events_before_seal":
                    raise InjectedCrash("after_events_before_seal")
                conn.execute(
                    "INSERT INTO seal VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (_RUN, epoch, grant[0], first, second,
                     _hash(payloads[0]), _hash(payloads[1])),
                )
                if fault == "before_commit":
                    raise InjectedCrash("before_commit")
                if fault == "hard_exit_before_commit":
                    # Real process death with an open SQLite transaction.
                    # This is a disposable test DB, never a production source.
                    os._exit(73)
                conn.commit()
                steps.append("commit")
            except BaseException:
                conn.rollback()
                raise

        if fault == "after_commit_before_ack":
            raise InjectedCrash("after_commit_before_ack")
        if fault == "hard_exit_after_commit":
            os._exit(73)
        steps.append("ack")
    return tuple(steps)


def _read_exact(root: Path, name: str) -> bytes:
    fd = os.open(root / name, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        st = os.fstat(fd)
        if (not stat.S_ISREG(st.st_mode)
                or stat.S_IMODE(st.st_mode) != 0o600
                or st.st_nlink != 1 or st.st_size > 2048):
            raise ValueError("wrong_object_attributes")
        with os.fdopen(os.dup(fd), "rb") as f:
            return f.read(2049)
    finally:
        os.close(fd)


def _inspect(root: Path, *, claim_current: bool = False) -> str:
    """Independent new-connection check, NOT authenticated source observation."""
    if claim_current:
        return _REFUSE_CURRENT  # no independent freshness witness exists
    with closing(_connect(root)) as conn:
        seal = conn.execute("SELECT * FROM seal WHERE run_id=?", (_RUN,)).fetchone()
        if seal is None:
            return _REFUSE_NO_SEAL
        state = conn.execute(
            "SELECT status, generation FROM run WHERE run_id=?", (_RUN,),
        ).fetchone()
        events = conn.execute(
            "SELECT event_id, event_type, generation FROM event "
            "WHERE run_id=? ORDER BY event_id", (_RUN,),
        ).fetchall()
    if (state is None or state["status"] != _STATUS_POST
            or state["generation"] != seal["generation"]
            or len(events) != 2
            or [e["event_type"] for e in events] !=
            ["verification.passed", "run.transition"]
            or [e["event_id"] for e in events] !=
            [seal["verification_event_id"], seal["transition_event_id"]]
            or any(e["generation"] != seal["generation"] for e in events)):
        return _REFUSE_COHERENCE
    try:
        raw = tuple(_read_exact(root, name) for name in _NAMES)
        if any(_hash(r) != expected for r, expected in zip(
            raw, (seal["verification_sha256"], seal["evidence_sha256"])
        )):
            return _REFUSE_EXACT_BYTES
        observed_epochs = tuple(json.loads(b)["epoch"] for b in raw)
        if observed_epochs != (seal["epoch"], seal["epoch"]):
            return _REFUSE_EXACT_BYTES
    except (OSError, ValueError, KeyError, TypeError):
        return _REFUSE_EXACT_BYTES
    return _SUCCESS


def test_w1c_one_status_two_events_and_seal_commit_after_durable_leaves(tmp_path):
    root = _fixture(tmp_path)
    steps = _publish(root, _grant(root), _payloads(1))
    assert steps == (
        "file_fsync", "replace", "directory_fsync",
        "file_fsync", "replace", "directory_fsync",
        "begin_immediate", "commit", "ack",
    )
    with closing(_connect(root)) as conn:
        assert conn.execute("SELECT status FROM run").fetchone()[0] == _STATUS_POST
        assert conn.execute("SELECT count(*) FROM seal").fetchone()[0] == 1
        assert [e[0] for e in conn.execute(
            "SELECT event_type FROM event ORDER BY event_id"
        )] == ["verification.passed", "run.transition"]
    for name in _NAMES:
        assert stat.S_IMODE((root / name).stat().st_mode) == 0o600
    assert _inspect(root) == _SUCCESS
    assert _inspect(root, claim_current=True) == _REFUSE_CURRENT


def test_same_owner_aba_lease_denies_stale_file_and_db_mutation(tmp_path):
    root = _fixture(tmp_path)
    first = _grant(root, "same")
    second = _grant(root, "same")
    assert first[0] + 1 == second[0] and first[1] != second[1]
    with pytest.raises(Refused, match=_REFUSE_STALE):
        _publish(root, first, _payloads(1))
    assert all(not (root / name).exists() for name in _NAMES)
    assert _inspect(root) == _REFUSE_NO_SEAL
    _publish(root, second, _payloads(1))
    assert _inspect(root) == _SUCCESS


@pytest.mark.parametrize("fault", [
    "before_file_fsync", "after_replace_before_dir_fsync", "before_begin",
    "after_events_before_seal", "before_commit",
])
def test_deterministic_precommit_crash_windows_never_publish_a_seal(tmp_path, fault):
    root = _fixture(tmp_path)
    with pytest.raises(InjectedCrash, match=fault):
        _publish(root, _grant(root), _payloads(1), fault=fault)
    assert _inspect(root) == _REFUSE_NO_SEAL
    with closing(_connect(root)) as conn:
        assert conn.execute("SELECT status FROM run").fetchone()[0] == _STATUS_PRE
        assert conn.execute("SELECT COUNT(*) FROM event").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM seal").fetchone()[0] == 0


def test_commit_before_ack_must_reconcile_and_not_blind_retry(tmp_path):
    root = _fixture(tmp_path)
    grant = _grant(root)
    with pytest.raises(InjectedCrash, match="after_commit_before_ack"):
        _publish(root, grant, _payloads(1), fault="after_commit_before_ack")
    assert _inspect(root) == _SUCCESS
    with pytest.raises(Refused, match=_REFUSE_STALE):
        _publish(root, grant, _payloads(1))
    with pytest.raises(Refused, match=_REFUSE_RETRY):
        _grant(root)


def test_separately_committed_event_or_transition_is_not_a_seal(tmp_path):
    root = _fixture(tmp_path)
    with closing(_connect(root)) as conn:
        conn.execute("INSERT INTO event (run_id, event_type, generation) "
                     "VALUES (?, 'verification.passed', 0)", (_RUN,))
    assert _inspect(root) == _REFUSE_NO_SEAL
    with closing(_connect(root)) as conn:
        conn.execute("UPDATE run SET status=? WHERE run_id=?",
                     (_STATUS_POST, _RUN))
        conn.execute("INSERT INTO event (run_id, event_type, generation) "
                     "VALUES (?, 'run.transition', 0)", (_RUN,))
    assert _inspect(root) == _REFUSE_NO_SEAL


def test_mixed_epoch_rehashed_individual_leaves_refused_before_seal(tmp_path):
    root = _fixture(tmp_path)
    mismatch = (_payloads(1)[0], _payloads(2)[1])
    assert all(len(_hash(x)) == 64 for x in mismatch)
    with pytest.raises(Refused, match=_REFUSE_EPOCH):
        _publish(root, _grant(root), mismatch, epoch=1)
    assert _inspect(root) == _REFUSE_NO_SEAL


def test_old_exact_bytes_overwritten_by_nonparticipant_become_unavailable(tmp_path):
    root = _fixture(tmp_path)
    _publish(root, _grant(root), _payloads(1))
    assert _inspect(root) == _SUCCESS
    # Simulated non-cooperating actor violates the publication mutex/P0:
    # local SHA can be recomputed but does not authorize old as-of N.
    replacement = _payloads(2)[1]
    assert len(_hash(replacement)) == 64
    (root / _NAMES[1]).write_bytes(replacement)
    assert _inspect(root) == _REFUSE_EXACT_BYTES


def test_valid_self_claim_or_forged_oracle_cannot_create_authority(tmp_path):
    root = _fixture(tmp_path)
    forged = {"source_admitted": True, "epoch": 1,
              "issuer_claim_id": "self", "sha256": _hash(_payloads(1)[0])}
    assert forged["source_admitted"]
    assert _inspect(root) == _REFUSE_NO_SEAL
    _publish(root, _grant(root), _payloads(1))
    # Even a complete matching fixture is only a conditional model result.
    assert _inspect(root) == _SUCCESS and "FIXTURE_ONLY" in _SUCCESS
    assert _inspect(root, claim_current=True) == _REFUSE_CURRENT


def test_tampered_transition_event_and_prefix_never_pass_inspection(tmp_path):
    root = _fixture(tmp_path)
    _publish(root, _grant(root), _payloads(1))
    with closing(_connect(root)) as conn:
        conn.execute("UPDATE event SET event_type='other' WHERE event_type='run.transition'")
    assert _inspect(root) == _REFUSE_COHERENCE


def _process_crash(root: str, grant: tuple[int, str], fault: str) -> None:
    try:
        _publish(Path(root), grant, _payloads(1), fault=fault)
    except InjectedCrash:
        os._exit(73)
    os._exit(99)


@pytest.mark.parametrize(("fault", "expected"), [
    ("hard_exit_before_commit", _REFUSE_NO_SEAL),
    ("hard_exit_after_commit", _SUCCESS),
])
def test_process_exit_at_commit_boundary_is_reconciled_from_fresh_reader(
    tmp_path, fault, expected
):
    root = _fixture(tmp_path)
    grant = _grant(root)
    ctx = multiprocessing.get_context("spawn")
    child = ctx.Process(target=_process_crash, args=(str(root), grant, fault))
    child.start()
    child.join(timeout=12)
    try:
        assert not child.is_alive()
        assert child.exitcode == 73
        assert _inspect(root) == expected
    finally:
        if child.is_alive():
            child.terminate()
            child.join(timeout=5)


def test_fixture_creates_no_real_projectctl_state_and_no_runtime_import():
    # All SQL and file publication code lives in this test module. No
    # production RunStore or external ProjectCTL store can be reached.
    source = Path(__file__).read_text(encoding="utf-8")
    source = source.split("def test_fixture_creates_no_real_projectctl_state_and_no_runtime_import():")[0]
    for forbidden in ("from projectctl", "import projectctl", "subprocess.",
                      "socket.", "codex", "os.system("):
        assert forbidden not in source.lower()
