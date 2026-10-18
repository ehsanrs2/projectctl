"""M6.0 M0n — real Linux owned-child FD drain + unmanaged bypass.

Positive *limited* proof: exact writable DB + JSON descriptors are pinned
to fixture inode identities in a test-owned child; after verified child
exit, those descriptors cannot be used by that child. A cooperative test
launcher refuses further starts. Independently launched v2 writers and
preexisting unmanaged FD holders remain able to write. This is NO-GO.

NO sudo, host signals, service/cgroup/mount modifications or production DB.
"""
from __future__ import annotations

import json
import os
import select
import signal
import subprocess
import sys
from dataclasses import dataclass, fields, replace
from datetime import datetime, timezone
from pathlib import Path

import pytest

from projectctl.core.enums import ModelProfile, ReasoningLevel, RunStatus
from projectctl.schemas.run import RunManifest, WorkerDescriptor
from projectctl.storage.runs import RunStore
from projectctl.storage.sqlite import (
    APPLICATION_ID, PROJECT_STATE_DB_VERSION, initialize_project_state_db,
    inspect_db,
)
from scripts.m0n_owned_fd_exit_witness import (
    ScopeObservation, ScopeRefused, decide, pidfd_exit_observed,
    witness_owned_fd,
)

pytestmark = pytest.mark.skipif(
    sys.platform != "linux" or not hasattr(os, "pidfd_open"),
    reason="M0n requires Linux proc fdinfo and pidfd; no synthetic success",
)

_RUN = "run-m0n"
_NOW = datetime(2026, 10, 18, tzinfo=timezone.utc)

# Runs only as a subprocess owned by the test on a private disposable v2 DB.
_ACTOR = r"""
import json
import os
import signal
import sys
from datetime import datetime, timezone
from pathlib import Path
from projectctl.storage.runs import RunStore

root = Path(sys.argv[1])
ignore_term = sys.argv[2] == "ignore"
base = root / ".projectctl"
json_file = base / "m0n-evidence.json"
db_file = base / "state.sqlite"
store = RunStore(root)  # actual old-v2-capable object before stop
db_fd = os.open(db_file, os.O_RDWR | os.O_NOFOLLOW)
json_fd = os.open(json_file, os.O_WRONLY | os.O_APPEND | os.O_NOFOLLOW)
readonly_fd = os.open(json_file, os.O_RDONLY | os.O_NOFOLLOW)
if ignore_term:
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
print(json.dumps({
    "phase": "ready", "pid": os.getpid(),
    "db_fd": db_fd, "json_fd": json_fd, "readonly_fd": readonly_fd,
}), flush=True)
for command in sys.stdin:
    cmd = command.strip()
    if cmd == "WRITE":
        count = os.write(json_fd, b"M0N_FD_WROTE")
        os.fsync(json_fd)
        store.append_event(
            "run-m0n", "m0n.fixture",
            {"disposable": True},
            now=datetime(2026, 10, 18, tzinfo=timezone.utc),
        )
        print(json.dumps({"phase": "wrote", "count": count}), flush=True)
    elif cmd == "EXIT":
        print(json.dumps({"phase": "exiting"}), flush=True)
        break
    else:
        print(json.dumps({"phase": "bad_command"}), flush=True)
        sys.exit(43)
os.close(readonly_fd)
os.close(json_fd)
os.close(db_fd)
"""


def _fixture(tmp_path: Path) -> tuple[Path, RunStore, Path]:
    root = tmp_path / "m0n-disposable-only"
    initialize_project_state_db(root / ".projectctl" / "state.sqlite")
    store = RunStore(root)
    store.create(
        RunManifest(
            run_id=_RUN,
            task_id="task-m0n",
            execution_plan_digest="m0n-fixture-only",
            status=RunStatus.PLANNED,
            base_commit="abcdef1",
            branch_name="projectctl/run/run-m0n",
            worktree_id="run-m0n",
            worker=WorkerDescriptor(
                provider="codex",
                model_profile=ModelProfile.BALANCED,
                reasoning=ReasoningLevel.MEDIUM,
            ),
        ),
        worktree_path=tmp_path / "not-a-real-worktree",
        now=_NOW,
    )
    leaf = root / ".projectctl" / "m0n-evidence.json"
    leaf.write_bytes(b"start-")
    assert inspect_db(store.db_path) == (APPLICATION_ID, 2)
    return root, store, leaf


@dataclass
class OwnedActor:
    proc: subprocess.Popen
    pidfd: int
    ready: dict


def _line(proc: subprocess.Popen, timeout: float = 8) -> dict:
    if proc.stdout is None:
        raise ScopeRefused("OWNED_CHILD_STDOUT_MISSING")
    readable, _, _ = select.select([proc.stdout], [], [], timeout)
    if not readable:
        raise ScopeRefused("OWNED_CHILD_RESPONSE_TIMEOUT")
    try:
        return json.loads(proc.stdout.readline())
    except (ValueError, TypeError) as exc:
        raise ScopeRefused("MALFORMED_OWNED_CHILD_RESPONSE") from exc


def _spawn(root: Path, *, ignore_term: bool = False) -> OwnedActor:
    proc = subprocess.Popen(
        [sys.executable, "-u", "-B", "-c", _ACTOR, str(root),
         "ignore" if ignore_term else "normal"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True, bufsize=1,
    )
    pidfd = None
    try:
        ready = _line(proc)
        if ready.get("phase") != "ready" or ready.get("pid") != proc.pid:
            raise ScopeRefused("OWNED_CHILD_IDENTITY_UNVERIFIED")
        pidfd = os.pidfd_open(proc.pid)
        if pidfd_exit_observed(pidfd):
            raise ScopeRefused("OWNED_CHILD_EXITED_BEFORE_ENROLLMENT")
        return OwnedActor(proc, pidfd, ready)
    except BaseException:
        if proc.poll() is None:
            proc.kill()  # only child spawned in this helper
        proc.communicate(timeout=5)
        if pidfd is not None:
            os.close(pidfd)
        raise


def _write(actor: OwnedActor) -> dict:
    if actor.proc.stdin is None:
        raise ScopeRefused("OWNED_CHILD_STDIN_MISSING")
    actor.proc.stdin.write("WRITE\n")
    actor.proc.stdin.flush()
    return _line(actor.proc)


def _cleanup(actor: OwnedActor) -> None:
    if actor.proc.poll() is None:
        actor.proc.kill()  # only our Popen child, NEVER arbitrary /proc PIDs
    try:
        actor.proc.communicate(timeout=5)
    finally:
        os.close(actor.pidfd)


class PrivateLauncher:
    """Voluntary *test-owned* launch boundary, not OS-wide start embargo."""

    def __init__(self, root: Path):
        self.root = root
        self.closed = False
        self.owned: list[OwnedActor] = []

    def launch(self, *, ignore_term: bool = False) -> OwnedActor:
        if self.closed:
            raise ScopeRefused("TEST_LAUNCHER_CLOSED")
        actor = _spawn(self.root, ignore_term=ignore_term)
        self.owned.append(actor)
        return actor

    def close_and_drain(self, *, timeout: float = 3) -> bool:
        self.closed = True  # FIRST stop starts in this voluntary launcher
        for actor in self.owned:
            if actor.proc.poll() is None:
                actor.proc.terminate()  # ONLY our Popen child
                try:
                    actor.proc.wait(timeout=timeout)
                except subprocess.TimeoutExpired:
                    return False   # no false "drained"; cleanup uses owned kill
            if not pidfd_exit_observed(actor.pidfd):
                return False
        return True

    def cleanup(self) -> None:
        for actor in self.owned:
            _cleanup(actor)
        self.owned.clear()


def _all_true() -> ScopeObservation:
    return ScopeObservation(**{
        field.name: True for field in fields(ScopeObservation)
    })


def test_actual_fd_identity_pidfd_draining_and_independent_writer_bypass(tmp_path):
    root, store, leaf = _fixture(tmp_path)
    scope = PrivateLauncher(root)
    external = None
    fresh = None
    try:
        controlled = scope.launch()
        external = _spawn(root)  # NOT enrolled in scope; prior FD held open
        expected_json = leaf.stat()
        expected_db = store.db_path.stat()

        for actor in (controlled, external):
            seen_json = witness_owned_fd(
                actor.proc, actor.ready["json_fd"], leaf,
            )
            seen_db = witness_owned_fd(
                actor.proc, actor.ready["db_fd"], store.db_path,
            )
            assert (seen_json.device, seen_json.inode) == (
                expected_json.st_dev, expected_json.st_ino,
            )
            assert (seen_db.device, seen_db.inode) == (
                expected_db.st_dev, expected_db.st_ino,
            )
            assert seen_json.open_mode == "wronly"
            assert seen_db.open_mode == "rdwr"

        events_before = len(store.events(_RUN))
        assert scope.close_and_drain()
        assert controlled.proc.poll() is not None
        assert pidfd_exit_observed(controlled.pidfd)
        assert len(store.events(_RUN)) == events_before
        assert leaf.read_bytes() == b"start-"
        with pytest.raises(ScopeRefused, match="TEST_LAUNCHER_CLOSED"):
            scope.launch()

        # Unmanaged *preexisting* actor retains its DB and JSON handles.
        assert not pidfd_exit_observed(external.pidfd)
        assert _write(external) == {
            "phase": "wrote", "count": len(b"M0N_FD_WROTE"),
        }
        assert leaf.read_bytes() == b"start-M0N_FD_WROTE"
        assert store.events(_RUN)[-1].event_type == "m0n.fixture"

        # A *new* independent v2 writer bypasses the voluntary launcher.
        fresh = _spawn(root)
        assert _write(fresh)["phase"] == "wrote"
        assert leaf.read_bytes() == b"start-M0N_FD_WROTEM0N_FD_WROTE"

        result = decide(_all_true())
        assert result.decision == "NO_GO_UNMANAGED_FD_AND_START_BYPASS"
        assert result.authorizes_migration is False
        assert inspect_db(store.db_path) == (APPLICATION_ID, 2)
        assert PROJECT_STATE_DB_VERSION == 2
    finally:
        scope.cleanup()
        if external is not None:
            _cleanup(external)
        if fresh is not None:
            _cleanup(fresh)


def test_sigterm_resistant_owned_actor_is_not_declared_drained(tmp_path):
    root, _store, _leaf = _fixture(tmp_path)
    scope = PrivateLauncher(root)
    try:
        owned = scope.launch(ignore_term=True)
        assert not scope.close_and_drain(timeout=0.15)
        assert owned.proc.poll() is None
        assert not pidfd_exit_observed(owned.pidfd)
        assert decide(replace(
            _all_true(), owned_process_exited_via_pidfd=False
        )).decision == "NO_GO_UNVERIFIED_OWNED_PROCESS_EXITED_VIA_PIDFD"
        with pytest.raises(ScopeRefused, match="TEST_LAUNCHER_CLOSED"):
            scope.launch()
    finally:
        scope.cleanup()  # only the test-owned resistant child is killed


def test_inode_and_open_flags_fail_closed_on_owned_live_child(tmp_path):
    root, store, leaf = _fixture(tmp_path)
    actor = _spawn(root)
    try:
        with pytest.raises(ScopeRefused, match="FD_NOT_OPENED_FOR_WRITE"):
            witness_owned_fd(actor.proc, actor.ready["readonly_fd"], leaf)
        with pytest.raises(ScopeRefused, match="FD_TARGET_INODE_MISMATCH"):
            witness_owned_fd(actor.proc, actor.ready["json_fd"], store.db_path)
        with pytest.raises(ScopeRefused, match="INVALID_OWNED_FD_NUMBER"):
            witness_owned_fd(actor.proc, -1, leaf)
        with pytest.raises(ScopeRefused, match="INVALID_OWNED_FD_NUMBER"):
            witness_owned_fd(actor.proc, True, leaf)
    finally:
        _cleanup(actor)
    with pytest.raises(ScopeRefused, match="OWNED_CHILD_ALREADY_EXITED"):
        witness_owned_fd(actor.proc, actor.ready["db_fd"], store.db_path)


@pytest.mark.parametrize("field_name", [
    field.name for field in fields(ScopeObservation)
])
@pytest.mark.parametrize("bad", [False, None, 1, "yes"])
def test_unverified_or_truthy_scope_observation_never_authorizes(field_name, bad):
    claim = replace(_all_true(), **{field_name: bad})
    result = decide(claim)
    assert result.decision == "NO_GO_UNVERIFIED_" + field_name.upper()
    assert result.authorizes_migration is False


def test_even_all_claimed_scope_is_negative_evidence():
    assert decide(_all_true()).decision == (
        "NO_GO_UNMANAGED_FD_AND_START_BYPASS"
    )
    assert decide({}).decision == "NO_GO_INVALID_SCOPE_OBSERVATION"
    assert decide(None).authorizes_migration is False
