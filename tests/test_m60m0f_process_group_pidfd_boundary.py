"""M6.0 M0f: Linux process-group/pidfd cutover laboratory, NOT a migrator.

All processes and ProjectCTL v2 DBs are disposable fixtures under tmp_path.
No production PIDs, systemd units, cgroups, mount namespaces or service
configurations are changed. A session/process group is NOT an all-writer
exclusion mechanism: a child can escape with setsid and an independent
legacy v2 launcher can write after supervised group termination.
"""
from __future__ import annotations

import json
import os
import select
import signal
import subprocess
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass, replace
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
    sys.platform != "linux"
    or not hasattr(os, "pidfd_open")
    or not hasattr(signal, "pidfd_send_signal"),
    reason="M0f requires Linux /proc, new session and pidfd",
)

_RUN = "run-m0f"
_NOW = datetime(2026, 10, 17, tzinfo=timezone.utc)

# Separate interpreter: actual pre-existing v2 RunStore constructed
# BEFORE the supervisor stop. This program is run only on tmp_path fixtures.
_ACTOR = r"""
import json
import os
import sys
import time
from pathlib import Path
from datetime import datetime, timezone
from projectctl.storage.runs import RunStore

root, mode, escape, trigger, ready, done = sys.argv[1:]
root, trigger, ready, done = map(Path, (root, trigger, ready, done))
RunStore(root)
child = os.fork()
if child == 0:
    try:
        if escape == "yes":
            os.setsid()  # explicit process-group escape
        ready.write_text("child-ready", encoding="utf-8")
        deadline = time.monotonic() + 15
        while not trigger.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        if not trigger.exists():
            os._exit(0)
        if mode == "db":
            RunStore(root).append_event(
                "run-m0f", "m0f.fixture", {"disposable": True},
                now=datetime(2026, 10, 17, tzinfo=timezone.utc),
            )
        elif mode == "json":
            stage = root / ".projectctl" / "m0f-evidence.stage"
            dest = root / ".projectctl" / "m0f-evidence.json"
            stage.write_text('{"disposable":true}', encoding="utf-8")
            os.replace(stage, dest)
        else:
            os._exit(33)
        done.write_text("wrote", encoding="utf-8")
        os._exit(0)
    except BaseException:
        os._exit(34)
else:
    deadline = time.monotonic() + 10
    while not ready.exists() and time.monotonic() < deadline:
        time.sleep(0.02)
    if not ready.exists():
        sys.exit(35)
    print(json.dumps({"leader": os.getpid(), "child": child}), flush=True)
    while True:
        time.sleep(1)
"""


class LabRefused(RuntimeError):
    """Refusal is test-only; there is no operator migration API."""


@dataclass(frozen=True)
class ProcessIdentity:
    pid: int
    group: int
    start_ticks: int


@dataclass
class Actor:
    leader: subprocess.Popen
    leader_identity: ProcessIdentity
    descendant_identity: ProcessIdentity
    descendant_pidfd: int
    trigger: Path
    done: Path


def _identity(pid: int) -> ProcessIdentity:
    """Observe one fixture PID; no process inventory or ownership proof."""
    try:
        body = (Path("/proc") / str(pid) / "stat").read_text(
            encoding="utf-8"
        ).rsplit(") ", 1)[1].split()
        return ProcessIdentity(pid, int(body[2]), int(body[19]))
    except (IndexError, OSError, ValueError) as error:
        raise LabRefused("pid_identity_missing") from error


def _dead(pidfd: int, timeout_ms: int = 0) -> bool:
    poller = select.poll()
    poller.register(pidfd, select.POLLIN)
    return bool(poller.poll(timeout_ms))


def _fixture(tmp_path: Path) -> tuple[Path, RunStore]:
    root = tmp_path / "m0f-disposable"
    initialize_project_state_db(root / ".projectctl" / "state.sqlite")
    store = RunStore(root)
    store.create(
        RunManifest(
            run_id=_RUN,
            task_id="task-m0f",
            execution_plan_digest="m0f-fixture-only",
            status=RunStatus.PLANNED,
            base_commit="abcdef1",
            branch_name="projectctl/run/run-m0f",
            worktree_id="run-m0f",
            worker=WorkerDescriptor(
                provider="codex",
                model_profile=ModelProfile.BALANCED,
                reasoning=ReasoningLevel.MEDIUM,
            ),
        ),
        worktree_path=tmp_path / "not-a-real-worktree",
        now=_NOW,
    )
    assert inspect_db(store.db_path) == (APPLICATION_ID, 2)
    return root, store


def _stop_owned_group(actor: Actor, *, claimed: ProcessIdentity) -> None:
    """Kill ONLY our still-live newly spawned session leader's group."""
    proc = actor.leader
    if proc.poll() is not None:
        raise LabRefused("leader_already_exited")
    if (
        proc.pid != claimed.pid
        or claimed != actor.leader_identity
        or _identity(proc.pid) != claimed
        or claimed.group != proc.pid
        or os.getpgrp() == claimed.group
    ):
        raise LabRefused("group_identity_untrusted")
    os.killpg(proc.pid, signal.SIGTERM)
    proc.wait(timeout=6)


@contextmanager
def _spawn(root: Path, tmp_path: Path, *, mode: str, escape: bool):
    """Own the only leader session and pin descendant identity with pidfd."""
    trigger = tmp_path / "trigger"
    ready = tmp_path / "child-ready"
    done = tmp_path / "child-done"
    proc = subprocess.Popen(
        [
            sys.executable, "-u", "-c", _ACTOR,
            str(root), mode, "yes" if escape else "no",
            str(trigger), str(ready), str(done),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
        text=True,
    )
    pidfd = None
    actor = None
    try:
        # Bounded IPC; readline only after data becomes readable.
        readable, _, _ = select.select([proc.stdout], [], [], 12)
        if not readable:
            raise LabRefused("fixture_process_start_timeout")
        line = proc.stdout.readline()
        info = json.loads(line)
        if info["leader"] != proc.pid:
            raise LabRefused("leader_identity_mismatch")
        leader = _identity(proc.pid)
        if leader.group != proc.pid or leader.group == os.getpgrp():
            raise LabRefused("fixture_not_isolated")
        child_pid = info["child"]
        child_identity = _identity(child_pid)
        if escape and child_identity.group == proc.pid:
            raise LabRefused("escape_not_established")
        if not escape and child_identity.group != proc.pid:
            raise LabRefused("unexpected_group_escape")
        try:
            pidfd = os.pidfd_open(child_pid, 0)
        except OSError as error:
            pytest.skip("pidfd unavailable on this Linux runner: " + str(error))
        actor = Actor(proc, leader, child_identity, pidfd, trigger, done)
        yield actor
    finally:
        # Never signal an arbitrary discovered PID; a pidfd refers to the
        # observed child kernel process even if its numeric PID is reused.
        if pidfd is not None:
            if not _dead(pidfd):
                try:
                    signal.pidfd_send_signal(pidfd, signal.SIGKILL, None, 0)
                except ProcessLookupError:
                    pass
            os.close(pidfd)
        if proc.poll() is None:
            # Only our own fresh start_new_session=True leader's group.
            if os.getpgid(proc.pid) == proc.pid and proc.pid != os.getpgrp():
                os.killpg(proc.pid, signal.SIGKILL)
        try:
            proc.wait(timeout=6)
        finally:
            if proc.stdout is not None:
                proc.stdout.close()


def _await_done(actor: Actor) -> bool:
    limit = time.monotonic() + 6
    while time.monotonic() < limit and not actor.done.exists():
        if _dead(actor.descendant_pidfd):
            break
        time.sleep(0.02)
    return actor.done.exists()


@dataclass(frozen=True)
class CutoverEvidence:
    """Hypothetical external operator claims, NOT authenticated evidence."""
    verified_owned_process_group: bool = False
    all_legacy_descendants_reaped: bool = False
    escaped_sessions_excluded: bool = False
    all_other_process_groups_excluded: bool = False
    independent_start_paths_embargoed: bool = False
    existing_writable_fds_closed: bool = False
    all_filesystem_identities_anchored: bool = False
    durable_recovery_validated: bool = False


def _admission_decision(evidence: CutoverEvidence) -> str:
    """No combination, including all True, permits migration."""
    for name in CutoverEvidence.__dataclass_fields__:
        if not getattr(evidence, name):
            return "NO_GO_" + name.upper()
    return "LAB_REVIEW_ONLY"


@pytest.mark.parametrize("mode", ["db", "json"])
def test_own_process_group_stop_reaps_non_escaping_legacy_descendant(
    tmp_path, mode,
):
    root, store = _fixture(tmp_path)
    before = tuple(x.event_type for x in store.events(_RUN))
    with _spawn(root, tmp_path, mode=mode, escape=False) as actor:
        _stop_owned_group(actor, claimed=actor.leader_identity)
        assert _dead(actor.descendant_pidfd, 4000)
        actor.trigger.write_text("go", encoding="utf-8")
        assert not actor.done.exists()
    assert tuple(x.event_type for x in store.events(_RUN)) == before
    assert not (root / ".projectctl" / "m0f-evidence.json").exists()
    assert PROJECT_STATE_DB_VERSION == 2


@pytest.mark.parametrize("mode", ["db", "json"])
def test_sets_id_escape_survives_group_stop_and_writes_real_v2(
    tmp_path, mode,
):
    root, store = _fixture(tmp_path)
    with _spawn(root, tmp_path, mode=mode, escape=True) as actor:
        _stop_owned_group(actor, claimed=actor.leader_identity)
        assert not _dead(actor.descendant_pidfd)
        actor.trigger.write_text("go", encoding="utf-8")
        assert _await_done(actor), "escaped_legacy_writer_did_not_complete"
        if mode == "db":
            assert store.events(_RUN)[-1].event_type == "m0f.fixture"
        else:
            assert (root / ".projectctl" / "m0f-evidence.json").read_text(
                encoding="utf-8"
            ) == '{"disposable":true}'
    assert inspect_db(store.db_path) == (APPLICATION_ID, 2)
    assert _admission_decision(
        replace(
            CutoverEvidence(), verified_owned_process_group=True,
            all_legacy_descendants_reaped=True,
        )
    ) == "NO_GO_ESCAPED_SESSIONS_EXCLUDED"


def test_claimed_wrong_process_birth_cannot_stop_owned_group(tmp_path):
    root, store = _fixture(tmp_path)
    with _spawn(root, tmp_path, mode="json", escape=False) as actor:
        forged = replace(
            actor.leader_identity,
            start_ticks=actor.leader_identity.start_ticks + 1,
        )
        with pytest.raises(LabRefused, match="group_identity_untrusted"):
            _stop_owned_group(actor, claimed=forged)
        assert actor.leader.poll() is None
        assert not _dead(actor.descendant_pidfd)
        _stop_owned_group(actor, claimed=actor.leader_identity)
        assert _dead(actor.descendant_pidfd, 4000)
    assert inspect_db(store.db_path) == (APPLICATION_ID, 2)


def test_independent_new_session_after_stop_remains_unblocked(tmp_path):
    root, store = _fixture(tmp_path)
    before = len(store.events(_RUN))
    first = tmp_path / "first"
    first.mkdir()
    with _spawn(root, first, mode="db", escape=False) as actor:
        _stop_owned_group(actor, claimed=actor.leader_identity)
        assert _dead(actor.descendant_pidfd, 4000)
    # Another launch path outside the terminated process group remains
    # fully able to start a real v2 RunStore and publish afterwards.
    other = tmp_path / "independent"
    other.mkdir()
    with _spawn(root, other, mode="db", escape=False) as outsider:
        outsider.trigger.write_text("go", encoding="utf-8")
        assert _await_done(outsider)
    assert len(store.events(_RUN)) == before + 1
    assert _admission_decision(
        replace(
            CutoverEvidence(), verified_owned_process_group=True,
            all_legacy_descendants_reaped=True,
            escaped_sessions_excluded=True,
            all_other_process_groups_excluded=True,
        )
    ) == "NO_GO_INDEPENDENT_START_PATHS_EMBARGOED"


def test_every_external_gate_fails_closed_including_all_true():
    all_claimed = CutoverEvidence(**{
        field: True for field in CutoverEvidence.__dataclass_fields__
    })
    assert _admission_decision(all_claimed) == "LAB_REVIEW_ONLY"
    for field in CutoverEvidence.__dataclass_fields__:
        incomplete = replace(all_claimed, **{field: False})
        assert _admission_decision(incomplete) == "NO_GO_" + field.upper()
