"""M6.0 M0n — narrow, non-authorizing Linux FD / pidfd exit witness.

Inputs are live, *test-owned* Popen children, not arbitrary host PIDs.
The witness proves a particular child held a writable descriptor to an
expected inode at one instant, and that its pidfd signaled exit later.
Neither a sample nor pidfd exit can enumerate all writers / aliases.

No projectctl runtime or production mutation authority is exposed here.
"""
from __future__ import annotations

import os
import select
import stat
import subprocess
from dataclasses import dataclass, fields
from pathlib import Path


class ScopeRefused(RuntimeError):
    """An owned-child observation cannot be authenticated."""


@dataclass(frozen=True)
class FDIdentity:
    pid: int
    fd: int
    device: int
    inode: int
    open_mode: str


@dataclass(frozen=True)
class ScopeObservation:
    # All observations intentionally concern a declared disposable lab.
    owned_db_fd_verified: bool | None = None
    owned_json_fd_verified: bool | None = None
    owned_process_exited_via_pidfd: bool | None = None
    controlled_restart_refused: bool | None = None
    unmanaged_preopened_fd_wrote: bool | None = None
    unmanaged_independent_v2_writer_wrote: bool | None = None


@dataclass(frozen=True)
class ScopeDecision:
    decision: str
    authorizes_migration: bool = False


def decide(observation: ScopeObservation) -> ScopeDecision:
    if type(observation) is not ScopeObservation:
        return ScopeDecision("NO_GO_INVALID_SCOPE_OBSERVATION")
    for field in fields(observation):
        if getattr(observation, field.name) is not True:
            return ScopeDecision("NO_GO_UNVERIFIED_" + field.name.upper())
    # Positive bypasses are an intentional, required part of the lab.
    # Even if independent writers were absent in a sample, a lab cannot GO.
    return ScopeDecision("NO_GO_UNMANAGED_FD_AND_START_BYPASS")


def witness_owned_fd(
    child: subprocess.Popen,
    fd: int,
    expected_file: Path,
) -> FDIdentity:
    """Examine /proc ONLY for a live subprocess owned by the test.

    Require inode identity and a writable access mode, not a textual
    symlink match; fdinfo is a Linux-kernel flag observation only.
    """
    if not isinstance(child, subprocess.Popen) or child.pid is None:
        raise ScopeRefused("NOT_AN_OWNED_POPEN_CHILD")
    if child.poll() is not None:
        raise ScopeRefused("OWNED_CHILD_ALREADY_EXITED")
    if type(fd) is not int or fd < 0 or fd > 1048576:
        raise ScopeRefused("INVALID_OWNED_FD_NUMBER")
    try:
        target = os.stat(expected_file, follow_symlinks=False)
        if not stat.S_ISREG(target.st_mode) or target.st_nlink != 1:
            raise ScopeRefused("INVALID_DISPOSABLE_TARGET")
        proc_fd = Path("/proc") / str(child.pid) / "fd" / str(fd)
        actual = proc_fd.stat()
        if (target.st_dev, target.st_ino) != (actual.st_dev, actual.st_ino):
            raise ScopeRefused("FD_TARGET_INODE_MISMATCH")
        info = (Path("/proc") / str(child.pid) / "fdinfo" / str(fd)).read_text(
            encoding="ascii"
        )
        flags_lines = [line for line in info.splitlines() if line.startswith("flags:")]
        if len(flags_lines) != 1:
            raise ScopeRefused("FDINFO_FLAGS_MISSING_OR_AMBIGUOUS")
        flags = int(flags_lines[0].split(":", 1)[1].strip(), 8)
        acc = flags & os.O_ACCMODE
        if acc not in (os.O_WRONLY, os.O_RDWR):
            raise ScopeRefused("FD_NOT_OPENED_FOR_WRITE")
        return FDIdentity(
            pid=child.pid, fd=fd, device=actual.st_dev,
            inode=actual.st_ino,
            open_mode="wronly" if acc == os.O_WRONLY else "rdwr",
        )
    except (OSError, ValueError, IndexError) as exc:
        raise ScopeRefused("OWNED_FD_WITNESS_UNAVAILABLE") from exc


def pidfd_exit_observed(pidfd: int) -> bool:
    """Only use a pidfd opened for an owned child, not its numeric PID."""
    if type(pidfd) is not int or pidfd < 0:
        raise ScopeRefused("INVALID_OWNED_PIDFD")
    try:
        poll = select.poll()
        poll.register(pidfd, select.POLLIN | select.POLLHUP)
        return bool(poll.poll(0))
    except OSError as exc:
        raise ScopeRefused("PIDFD_EXIT_WITNESS_UNAVAILABLE") from exc
