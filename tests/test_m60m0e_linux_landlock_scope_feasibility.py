"""M6.0 M0e: optional Linux Landlock, strictly disposable process lab.

Landlock is per-process/descendant confinement; it CANNOT retrofit running
legacy v2 clients, revoke preopened file descriptors or exclude unmanaged
writers. These tests never sandbox the pytest host or signal external PIDs.
No production migrator, gate, RunStore API, or user service is modified.
"""
from __future__ import annotations

import ctypes
import errno
import multiprocessing
import os
import platform
import sqlite3
import sys
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
    sys.platform != "linux",
    reason="M0e Linux Landlock child-process-only experiment",
)

_RUN = "run-m0e"
_NOW = datetime(2026, 10, 17, tzinfo=timezone.utc)
_SYSCALL_CREATE = 444
_SYSCALL_RESTRICT = 446
_PR_SET_NO_NEW_PRIVS = 38
_LANDLOCK_VERSION = 1
_WRITE_FILE = 1 << 1
_REMOVE_DIR = 1 << 4
_REMOVE_FILE = 1 << 5
_MAKE = sum(1 << bit for bit in range(6, 13))
_REFER = 1 << 13
_TRUNCATE = 1 << 14


class LandlockUnavailable(RuntimeError):
    """Kernel or sandbox does not support the explicitly tested mechanism."""


class _Ruleset(ctypes.Structure):
    _fields_ = [("handled_access_fs", ctypes.c_uint64)]


def _install_child_only_landlock() -> int:
    """Deny filesystem writes for calling child + descendants (not the host).

    ABI 1 supports open-for-write/create/delete; newer ABIs additionally
    constrain file reparenting and truncation. No allow rules are added.
    Older kernels or seccomp-disabled syscalls cause explicit UNAVAILABLE.
    This has NO power over already-open descriptors or other processes.
    """
    if sys.platform != "linux" or platform.machine() not in ("x86_64", "aarch64"):
        raise LandlockUnavailable("unsupported_linux_architecture")

    libc = ctypes.CDLL(None, use_errno=True)
    libc.syscall.restype = ctypes.c_long
    abi = libc.syscall(_SYSCALL_CREATE, 0, 0, _LANDLOCK_VERSION)
    if abi < 1:
        raise LandlockUnavailable("kernel_landlock_unavailable")
    rights = _WRITE_FILE | _REMOVE_DIR | _REMOVE_FILE | _MAKE
    if abi >= 2:
        rights |= _REFER
    if abi >= 3:
        rights |= _TRUNCATE
    ruleset = _Ruleset(rights)
    fd = libc.syscall(
        _SYSCALL_CREATE, ctypes.byref(ruleset), ctypes.sizeof(ruleset), 0
    )
    if fd < 0:
        raise LandlockUnavailable("landlock_ruleset_refused")
    try:
        # NO_NEW_PRIVS and Landlock changes are ONLY applied to this
        # spawned child, never pytest/the operator/current shell.
        if libc.prctl(_PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) != 0:
            raise LandlockUnavailable("no_new_privileges_refused")
        if libc.syscall(_SYSCALL_RESTRICT, fd, 0) != 0:
            raise LandlockUnavailable("landlock_restrict_refused")
    finally:
        os.close(fd)
    return int(abi)


def _fixture(tmp_path: Path) -> tuple[Path, RunStore]:
    root = tmp_path / "disposable-m0e"
    db = root / ".projectctl" / "state.sqlite"
    initialize_project_state_db(db)
    store = RunStore(root)
    store.create(
        RunManifest(
            run_id=_RUN,
            task_id="task-m0e",
            execution_plan_digest="m0e-fixture-only",
            status=RunStatus.PLANNED,
            base_commit="abcdef1",
            branch_name="projectctl/run/run-m0e",
            worktree_id="run-m0e",
            worker=WorkerDescriptor(
                provider="codex",
                model_profile=ModelProfile.BALANCED,
                reasoning=ReasoningLevel.MEDIUM,
            ),
        ),
        worktree_path=tmp_path / "not-a-real-worktree",
        now=_NOW,
    )
    assert inspect_db(db) == (APPLICATION_ID, 2)
    return root, store


def _write(root: Path, mode: str) -> None:
    if mode == "db":
        RunStore(root).append_event(
            _RUN, "m0e.fixture", {"test_only": True}, now=_NOW
        )
    elif mode == "json":
        dest = root / ".projectctl" / "m0e-evidence.json"
        stage = root / ".projectctl" / "m0e-evidence.stage"
        stage.write_text('{"test_only":true}', encoding="utf-8")
        os.replace(stage, dest)
    else:
        raise AssertionError("unknown_test_write")


def _child(root_str: str, channel, mode: str, confined: bool) -> None:
    fd = None
    try:
        root = Path(root_str)
        # Construct a genuine v2 RunStore before admission, as in M0b/M0d.
        RunStore(root)
        if mode == "preopened":
            fd = os.open(
                root / ".projectctl" / "m0e-preopened.json",
                os.O_WRONLY | os.O_NOFOLLOW,
            )
        channel.send(("ready", os.getpid()))
        if channel.recv() != "go":
            raise AssertionError("invalid_test_command")
        if confined:
            try:
                abi = _install_child_only_landlock()
            except LandlockUnavailable as error:
                channel.send(("unsupported", str(error)))
                return
        else:
            abi = 0
        if mode == "preopened":
            # An already writable fd survives Landlock; no pathname open.
            os.write(fd, b"still-writable")
            os.fsync(fd)
            channel.send(("wrote", abi))
            return
        if mode == "descendant":
            # Restriction is inherited by fork, but not by independent
            # processes launched outside this lineage.
            child = os.fork()
            if child == 0:
                try:
                    _write(root, "json")
                except OSError as error:
                    os._exit(20 if error.errno in (errno.EPERM, errno.EACCES) else 21)
                except Exception:
                    os._exit(21)
                os._exit(0)
            _pid, status = os.waitpid(child, 0)
            if not os.WIFEXITED(status):
                channel.send(("unexpected_child_signal", status))
            else:
                channel.send(("descendant_status", os.WEXITSTATUS(status)))
            return
        try:
            _write(root, mode)
        except (OSError, sqlite3.Error) as error:
            channel.send(("blocked", type(error).__name__))
        else:
            channel.send(("wrote", abi))
    except BaseException as error:
        try:
            channel.send(("error", type(error).__name__))
        except (BrokenPipeError, OSError):
            pass
    finally:
        if fd is not None:
            os.close(fd)
        channel.close()


def _run_child(root: Path, mode: str, *, confined: bool):
    ctx = multiprocessing.get_context("spawn")
    parent, child = ctx.Pipe(duplex=True)
    proc = ctx.Process(target=_child, args=(str(root), child, mode, confined))
    proc.start()
    child.close()
    try:
        assert parent.poll(15), "m0e_child_start_timeout"
        assert parent.recv() == ("ready", proc.pid)
        parent.send("go")
        assert parent.poll(15), "m0e_child_result_timeout"
        result = parent.recv()
        proc.join(timeout=6)
        assert not proc.is_alive(), "m0e_child_did_not_exit"
        return result
    finally:
        if proc.is_alive():
            proc.kill()
        proc.join(timeout=6)
        parent.close()


def _require_kernel(result):
    if result[0] == "unsupported":
        pytest.skip("Linux Landlock not available to CI runner: " + result[1])
    assert result[0] != "error", result


@dataclass(frozen=True)
class ExclusionEvidence:
    # Hypothetical operator claims; NEVER authenticated by this test.
    child_landlock_enforced: bool = False
    preexisting_fd_holders_stopped: bool = False
    external_writers_excluded: bool = False
    all_launch_channels_blocked: bool = False
    descendants_contained: bool = False
    process_supervisor_persistent: bool = False
    filesystem_scope_verified: bool = False
    recovery_and_backup_validated: bool = False


def _review(evidence: ExclusionEvidence) -> str:
    """No path grants production migration authority."""
    if not evidence.child_landlock_enforced:
        return "NO_GO_KERNEL_ENFORCEMENT_UNPROVEN"
    if not evidence.preexisting_fd_holders_stopped:
        return "NO_GO_EXISTING_OPEN_HANDLES"
    if not evidence.external_writers_excluded:
        return "NO_GO_OUT_OF_SCOPE_WRITER"
    if not evidence.all_launch_channels_blocked:
        return "NO_GO_RESTART_OR_ALT_LAUNCH"
    if not evidence.descendants_contained or not evidence.process_supervisor_persistent:
        return "NO_GO_PROCESS_LIFECYCLE"
    if not evidence.filesystem_scope_verified or not evidence.recovery_and_backup_validated:
        return "NO_GO_FILESYSTEM_OR_RECOVERY"
    return "LAB_REVIEW_ONLY"


@pytest.mark.parametrize("mode", ["db", "json"])
def test_kernel_restriction_denies_new_legacy_writes_in_confined_child(tmp_path, mode):
    root, store = _fixture(tmp_path)
    before = tuple(event.event_type for event in store.events(_RUN))
    result = _run_child(root, mode, confined=True)
    _require_kernel(result)
    assert result[0] == "blocked", result
    assert tuple(event.event_type for event in store.events(_RUN)) == before
    assert not (root / ".projectctl" / "m0e-evidence.json").exists()
    assert not (root / ".projectctl" / "m0e-evidence.stage").exists()
    assert inspect_db(store.db_path) == (APPLICATION_ID, 2)


def test_kernel_restriction_is_inherited_by_forked_writer(tmp_path):
    root, store = _fixture(tmp_path)
    result = _run_child(root, "descendant", confined=True)
    _require_kernel(result)
    assert result == ("descendant_status", 20)
    assert not (root / ".projectctl" / "m0e-evidence.json").exists()
    assert inspect_db(store.db_path) == (APPLICATION_ID, 2)


def test_preopened_writable_fd_survives_later_landlock_restriction(tmp_path):
    root, store = _fixture(tmp_path)
    leaf = root / ".projectctl" / "m0e-preopened.json"
    leaf.write_bytes(b"")
    result = _run_child(root, "preopened", confined=True)
    _require_kernel(result)
    assert result[0] == "wrote", result
    assert leaf.read_bytes() == b"still-writable"
    assert inspect_db(store.db_path) == (APPLICATION_ID, 2)
    # Even real Linux access controls cannot be retrofitted over a
    # preexisting writable fd through this Landlock mechanism alone.
    assert _review(ExclusionEvidence(child_landlock_enforced=True)) == (
        "NO_GO_EXISTING_OPEN_HANDLES"
    )


@pytest.mark.parametrize("mode", ["db", "json"])
def test_independent_unmanaged_v2_process_can_still_write(tmp_path, mode):
    root, store = _fixture(tmp_path)
    result = _run_child(root, mode, confined=False)
    assert result == ("wrote", 0)
    if mode == "db":
        assert store.events(_RUN)[-1].event_type == "m0e.fixture"
    else:
        assert (root / ".projectctl" / "m0e-evidence.json").read_text(
            encoding="utf-8"
        ) == '{"test_only":true}'
    assert inspect_db(store.db_path) == (APPLICATION_ID, 2)
    assert _review(ExclusionEvidence(
        child_landlock_enforced=True,
        preexisting_fd_holders_stopped=True,
    )) == "NO_GO_OUT_OF_SCOPE_WRITER"


def test_every_untrusted_gate_is_mandatory_and_success_is_not_go():
    good = ExclusionEvidence(**{
        name: True for name in ExclusionEvidence.__dataclass_fields__
    })
    assert _review(good) == "LAB_REVIEW_ONLY"
    expected = {
        "child_landlock_enforced": "NO_GO_KERNEL_ENFORCEMENT_UNPROVEN",
        "preexisting_fd_holders_stopped": "NO_GO_EXISTING_OPEN_HANDLES",
        "external_writers_excluded": "NO_GO_OUT_OF_SCOPE_WRITER",
        "all_launch_channels_blocked": "NO_GO_RESTART_OR_ALT_LAUNCH",
        "descendants_contained": "NO_GO_PROCESS_LIFECYCLE",
        "process_supervisor_persistent": "NO_GO_PROCESS_LIFECYCLE",
        "filesystem_scope_verified": "NO_GO_FILESYSTEM_OR_RECOVERY",
        "recovery_and_backup_validated": "NO_GO_FILESYSTEM_OR_RECOVERY",
    }
    for field, refusal in expected.items():
        assert _review(replace(good, **{field: False})) == refusal
    assert PROJECT_STATE_DB_VERSION == 2
