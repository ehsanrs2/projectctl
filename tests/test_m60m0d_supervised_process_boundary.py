"""M6.0 M0d: bounded Linux supervised-process exclusion experiment.

Uses only spawned children and real v2 RunStore in disposable pytest tmp_path.
Terminating tracked fixture-owned PIDs is NOT an enforced project maintenance
barrier: untracked local/remote clients, descendants and restart managers can
still write. No production process is discovered, stopped or signaled.
"""
from __future__ import annotations

import multiprocessing
import os
import signal
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import pytest

from projectctl.core.enums import ModelProfile, ReasoningLevel, RunStatus
from projectctl.schemas.run import RunManifest, WorkerDescriptor
from projectctl.storage.runs import RunStore
from projectctl.storage.sqlite import (
    APPLICATION_ID,
    PROJECT_STATE_DB_VERSION,
    initialize_project_state_db,
    inspect_db,
)

pytestmark = pytest.mark.skipif(
    sys.platform != "linux" or not Path("/proc/self/stat").exists(),
    reason="M0d process-birth witness laboratory targets Linux /proc only",
)

_RUN = "run-m0d"
_NOW = datetime(2026, 10, 17, tzinfo=timezone.utc)


class ScopeRefused(RuntimeError):
    """A private test launcher refused enrollment; not a runtime error API."""


@dataclass(frozen=True)
class Identity:
    pid: int
    start_ticks: int


def _birth(pid: int) -> Identity:
    """Read Linux /proc PID + starttime; never use it to signal arbitrary PIDs."""
    try:
        stat_line = (Path("/proc") / str(pid) / "stat").read_text(
            encoding="utf-8"
        )
        after_comm = stat_line.rsplit(") ", 1)[1].split()
        return Identity(pid=pid, start_ticks=int(after_comm[19]))
    except (OSError, IndexError, ValueError) as error:
        raise ScopeRefused("process_identity_unavailable") from error


def _fixture(tmp_path: Path) -> tuple[Path, RunStore]:
    root = tmp_path / "m0d-disposable"
    db = root / ".projectctl" / "state.sqlite"
    initialize_project_state_db(db)
    store = RunStore(root)
    store.create(
        RunManifest(
            run_id=_RUN,
            task_id="task-m0d",
            execution_plan_digest="m0d-fixture-only",
            status=RunStatus.PLANNED,
            base_commit="abcdef1",
            branch_name="projectctl/run/run-m0d",
            worktree_id="run-m0d",
            worker=WorkerDescriptor(
                provider="codex",
                model_profile=ModelProfile.BALANCED,
                reasoning=ReasoningLevel.MEDIUM,
            ),
        ),
        worktree_path=tmp_path / "not-a-worktree",
        now=_NOW,
    )
    assert inspect_db(db) == (APPLICATION_ID, 2)
    return root, store


def _old_writer(root: str, channel, *, ignore_sigterm: bool = False) -> None:
    try:
        # Construct the real legacy RunStore before any maintenance action.
        store = RunStore(Path(root))
        if ignore_sigterm:
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
        channel.send(("ready", os.getpid()))
        command = channel.recv()
        if command == "db":
            store.append_event(
                _RUN, "m0d.fixture", {"disposable": True}, now=_NOW
            )
        elif command == "json":
            leaf = Path(root) / ".projectctl" / "m0d-evidence.json"
            staged = leaf.with_suffix(".stage")
            staged.write_text('{"changed":true}', encoding="utf-8")
            os.replace(staged, leaf)
        else:
            raise AssertionError("unexpected_test_command")
        channel.send(("done", command))
    except EOFError:
        pass
    except BaseException as error:
        try:
            channel.send(("error", type(error).__name__))
        except (OSError, BrokenPipeError):
            pass
    finally:
        channel.close()


def _launch(root: Path, *, ignore_sigterm: bool = False):
    ctx = multiprocessing.get_context("spawn")
    parent, child = ctx.Pipe(duplex=True)
    process = ctx.Process(
        target=_old_writer,
        args=(str(root), child),
        kwargs={"ignore_sigterm": ignore_sigterm},
    )
    process.start()
    child.close()
    try:
        if not parent.poll(12):
            raise ScopeRefused("actor_ready_timeout")
        kind, value = parent.recv()
        if kind != "ready" or value != process.pid:
            raise ScopeRefused("actor_not_ready")
        identity = _birth(process.pid)
        return process, parent, identity
    except BaseException:
        if process.is_alive():
            process.kill()
        process.join(timeout=5)
        parent.close()
        raise


def _recv(pipe):
    if not pipe.poll(12):
        raise ScopeRefused("actor_reply_timeout")
    return pipe.recv()


def _stop_owned(process, identity: Identity, *, timeout: float = 0.4) -> bool:
    """Signal ONLY a Process object spawned by this very test."""
    if not process.is_alive():
        process.join(timeout=timeout)
        return process.exitcode is not None
    if process.pid != identity.pid or _birth(process.pid) != identity:
        raise ScopeRefused("process_identity_drift")
    process.terminate()
    process.join(timeout=timeout)
    return not process.is_alive() and process.exitcode is not None


def _decision(
    *,
    tracked_terminated: bool,
    controlled_starts_blocked: bool,
    identities_verified: bool,
    unmanaged_writer_seen: bool,
    full_external_scope_proven: bool = False,
) -> str:
    """Even an ideal controlled experiment NEVER emits production GO."""
    if not identities_verified:
        return "NO_GO_IDENTITY_UNCERTAIN"
    if not tracked_terminated:
        return "NO_GO_UNDRAINED_PROCESS"
    if not controlled_starts_blocked:
        return "NO_GO_RESTART_ALLOWED"
    if unmanaged_writer_seen or not full_external_scope_proven:
        return "NO_GO_UNMANAGED_WRITER_SCOPE"
    return "LAB_EVIDENCE_ONLY"


class _TestSupervisor:
    """Voluntary fixture launcher only; not an OS service/start barrier."""

    def __init__(self, root: Path):
        self.root = root
        self.closed = False
        self.owned = []

    def launch(self, *, ignore_sigterm: bool = False):
        if self.closed:
            raise ScopeRefused("fixture_launcher_closed")
        actor = _launch(self.root, ignore_sigterm=ignore_sigterm)
        self.owned.append(actor)
        return actor

    def close_starts(self):
        self.closed = True

    def stop_all(self) -> bool:
        # False if any previously enrolled worker did not exit in time.
        return all(
            _stop_owned(proc, identity)
            for proc, _pipe, identity in self.owned
        )

    def cleanup(self):
        for proc, pipe, _identity in self.owned:
            if proc.is_alive():
                proc.kill()
            proc.join(timeout=5)
            pipe.close()


def test_preexisting_v2_db_and_json_writers_stop_under_explicit_supervision(
    tmp_path,
):
    root, store = _fixture(tmp_path)
    scope = _TestSupervisor(root)
    try:
        sql_actor = scope.launch()
        json_actor = scope.launch()
        assert all(proc.is_alive() for proc, _, _ in (sql_actor, json_actor))
        assert all(_birth(identity.pid) == identity for _, _, identity in (
            sql_actor, json_actor
        ))
        initial_events = len(store.events(_RUN))
        scope.close_starts()
        assert scope.stop_all()
        assert all(not proc.is_alive() for proc, _, _ in scope.owned)
        assert len(store.events(_RUN)) == initial_events
        assert not (root / ".projectctl" / "m0d-evidence.json").exists()
        assert _decision(
            tracked_terminated=True,
            controlled_starts_blocked=scope.closed,
            identities_verified=True,
            unmanaged_writer_seen=False,
        ) == "NO_GO_UNMANAGED_WRITER_SCOPE"
        assert PROJECT_STATE_DB_VERSION == 2
    finally:
        scope.cleanup()


def test_controlled_relaunch_refused_without_creating_process(tmp_path):
    root, store = _fixture(tmp_path)
    scope = _TestSupervisor(root)
    try:
        scope.close_starts()
        with pytest.raises(ScopeRefused, match="fixture_launcher_closed"):
            scope.launch()
        assert scope.owned == []
        assert store.events(_RUN)
        assert _decision(
            tracked_terminated=True,
            controlled_starts_blocked=True,
            identities_verified=True,
            unmanaged_writer_seen=False,
            full_external_scope_proven=True,  # an untrusted model input
        ) == "LAB_EVIDENCE_ONLY"
    finally:
        scope.cleanup()


@pytest.mark.parametrize("command", ["db", "json"])
def test_unmanaged_preexisting_v2_process_bypasses_fixture_start_block(
    tmp_path, command,
):
    root, store = _fixture(tmp_path)
    scope = _TestSupervisor(root)
    outsider = None
    try:
        outsider = _launch(root)
        assert outsider[0].is_alive()  # constructed before the barrier
        managed = scope.launch()
        scope.close_starts()
        assert scope.stop_all()
        assert not managed[0].is_alive()
        outsider[1].send(command)
        assert _recv(outsider[1]) == ("done", command)
        if command == "db":
            assert store.events(_RUN)[-1].event_type == "m0d.fixture"
        else:
            assert (root / ".projectctl" / "m0d-evidence.json").read_text(
                encoding="utf-8"
            ) == '{"changed":true}'
        assert _decision(
            tracked_terminated=True,
            controlled_starts_blocked=True,
            identities_verified=True,
            unmanaged_writer_seen=True,
            full_external_scope_proven=True,
        ) == "NO_GO_UNMANAGED_WRITER_SCOPE"
        assert inspect_db(store.db_path) == (APPLICATION_ID, 2)
    finally:
        scope.cleanup()
        if outsider is not None:
            proc, pipe, _ = outsider
            if proc.is_alive():
                proc.kill()
            proc.join(timeout=5)
            pipe.close()


def test_noncooperative_process_refuses_termination_and_blocks_admission(
    tmp_path,
):
    root, _store = _fixture(tmp_path)
    scope = _TestSupervisor(root)
    try:
        proc, _pipe, identity = scope.launch(ignore_sigterm=True)
        assert _birth(identity.pid) == identity
        scope.close_starts()
        assert scope.stop_all() is False
        assert proc.is_alive()
        assert _decision(
            tracked_terminated=False,
            controlled_starts_blocked=True,
            identities_verified=True,
            unmanaged_writer_seen=False,
        ) == "NO_GO_UNDRAINED_PROCESS"
    finally:
        scope.cleanup()


def test_birth_witness_and_unknown_startup_state_are_fail_closed(tmp_path):
    root, _store = _fixture(tmp_path)
    scope = _TestSupervisor(root)
    try:
        proc, _pipe, identity = scope.launch()
        forged = Identity(identity.pid, identity.start_ticks + 1)
        with pytest.raises(ScopeRefused, match="process_identity_drift"):
            _stop_owned(proc, forged)
        assert proc.is_alive()
        assert _decision(
            tracked_terminated=True,
            controlled_starts_blocked=True,
            identities_verified=False,
            unmanaged_writer_seen=False,
        ) == "NO_GO_IDENTITY_UNCERTAIN"
        assert _decision(
            tracked_terminated=True,
            controlled_starts_blocked=False,
            identities_verified=True,
            unmanaged_writer_seen=False,
        ) == "NO_GO_RESTART_ALLOWED"
    finally:
        scope.cleanup()
