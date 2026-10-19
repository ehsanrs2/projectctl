"""M6.0 M0x: bounded NONROOT external-anchor crash-window fixture.

A stable, fsynced anchor OUTSIDE the disposable work/ directory remains
readable when the inner journal has already been unlinked. The ordinary-
user harness kills only its own direct phase worker, then starts a fresh
interpreter to reconcile the private fixture. Neither process survives a
VM reboot by design. NO root, policy, systemd, actual project DB or GO.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import select
import signal
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

_PARENT = Path("/var/tmp")
_PREFIX = "projectctl-m0x-"
_ANCHOR = "m0x-anchor.json"
_WORK = "work"
_JOURNAL = "m0x-journal.json"
_EFFECT = "m0x-effect.bin"
_PAYLOAD = b"M0x private crash-window effect\n"
_ACK = "NONROOT_M0X_ANCHORED_CRASH_WINDOW_LAB"
_PHASES = (
    "before_effect_unlink",
    "after_effect_unlink",
    "after_journal_unlink",
    "after_work_rmdir",
)
_CEILING = {
    "authorizes_root_trial": False,
    "authorizes_policy_install": False,
    "authorizes_migration": False,
}


class Refused(RuntimeError):
    """Quarantine unknown file/credential/process state."""


def _ordinary_user() -> None:
    if sys.platform != "linux" or os.getuid() == 0 or os.geteuid() == 0:
        raise Refused("NONROOT_LINUX_REQUIRED")


def _fsync_dir(path: Path) -> None:
    fd = os.open(path, os.O_DIRECTORY | os.O_RDONLY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _private_dir(path: Path, parent: Path) -> None:
    _ordinary_user()
    if (not path.is_absolute() or not parent.is_absolute()
            or path.parent != parent or parent.is_symlink()):
        raise Refused("UNSAFE_PRIVATE_ANCESTRY")
    try:
        p, b = path.lstat(), parent.lstat()
    except OSError as exc:
        raise Refused("PRIVATE_SCOPE_MISSING") from exc
    if (not stat.S_ISDIR(p.st_mode) or not stat.S_ISDIR(b.st_mode)
            or p.st_uid != os.getuid() or stat.S_IMODE(p.st_mode) != 0o700
            or p.st_dev != b.st_dev):
        raise Refused("UNTRUSTED_PRIVATE_DIRECTORY")


def _scope(root: Path, base: Path) -> None:
    if root.parent != base or not root.name.startswith(_PREFIX):
        raise Refused("OUTSIDE_FIXED_NONROOT_FIXTURE")
    _private_dir(root, base)


def _anchor_bytes(root: Path) -> bytes:
    return (json.dumps({
        "format": "m0x-private-anchor-v1",
        "fixture": root.name,
        "inner_journal_sha256": hashlib.sha256(_journal_bytes(root)).hexdigest(),
        "payload_sha256": hashlib.sha256(_PAYLOAD).hexdigest(),
        **_CEILING,
    }, sort_keys=True, separators=(",", ":")) + "\n").encode("ascii")


def _journal_bytes(root: Path) -> bytes:
    return (json.dumps({
        "format": "m0x-private-work-v1",
        "fixture": root.name,
        "phase": "prepared-before-effect",
        **_CEILING,
    }, sort_keys=True, separators=(",", ":")) + "\n").encode("ascii")


def _publish(root: Path, name: str, data: bytes) -> None:
    fd = os.open(root / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, "wb", closefd=False) as out:
            out.write(data)
            out.flush()
        os.fsync(fd)
    finally:
        os.close(fd)
    _fsync_dir(root)


def _owned_leaf(root: Path, name: str) -> bytes:
    try:
        a = (root / name).lstat()
    except OSError as exc:
        raise Refused("MISSING_PRIVATE_LEAF") from exc
    if (not stat.S_ISREG(a.st_mode) or a.st_uid != os.getuid()
            or a.st_nlink != 1 or stat.S_IMODE(a.st_mode) != 0o600):
        raise Refused("UNTRUSTED_PRIVATE_LEAF")
    fd = os.open(root / name, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        b = os.fstat(fd)
        if (a.st_dev, a.st_ino) != (b.st_dev, b.st_ino):
            raise Refused("LEAF_IDENTITY_DRIFT")
        data = os.read(fd, 4097)
        if len(data) > 4096:
            raise Refused("OVERSIZED_LEAF")
        return data
    finally:
        os.close(fd)


def _verified_state(root: Path, base: Path) -> Path | None:
    _scope(root, base)
    entries = {p.name for p in root.iterdir()}
    if _ANCHOR not in entries or entries - {_ANCHOR, _WORK}:
        raise Refused("QUARANTINE_UNKNOWN_ROOT_ENTRY")
    if _owned_leaf(root, _ANCHOR) != _anchor_bytes(root):
        raise Refused("QUARANTINE_ANCHOR_DRIFT")
    if _WORK not in entries:
        return None
    work = root / _WORK
    _private_dir(work, root)
    leaves = {p.name for p in work.iterdir()}
    if leaves - {_JOURNAL, _EFFECT}:
        raise Refused("QUARANTINE_UNKNOWN_WORK_LEAF")
    if _JOURNAL in leaves:
        if _owned_leaf(work, _JOURNAL) != _journal_bytes(root):
            raise Refused("QUARANTINE_INNER_JOURNAL_DRIFT")
    if _EFFECT in leaves:
        if _JOURNAL not in leaves:
            raise Refused("QUARANTINE_EFFECT_WITHOUT_JOURNAL")
        if _owned_leaf(work, _EFFECT) != _PAYLOAD:
            raise Refused("QUARANTINE_EFFECT_DRIFT")
    # If work/ is empty, the immutable outer anchor is the recovery
    # evidence for the deliberate post-journal-unlink crash window.
    return work


def prepare_private(base: Path) -> Path:
    """Fresh test-owned directory, persist the anchor before work/ creation."""
    _ordinary_user()
    if not base.is_absolute() or base.is_symlink() or not base.is_dir():
        raise Refused("UNSAFE_FIXED_PARENT")
    root = Path(tempfile.mkdtemp(prefix=_PREFIX, dir=base))
    _scope(root, base)
    _fsync_dir(base)
    _publish(root, _ANCHOR, _anchor_bytes(root))
    work = root / _WORK
    work.mkdir(mode=0o700)
    _fsync_dir(root)
    _publish(work, _JOURNAL, _journal_bytes(root))
    _publish(work, _EFFECT, _PAYLOAD)
    return root


def apply_private_phase(root: Path, base: Path, phase: str) -> None:
    """Only used by disposable worker; never an installer/remover."""
    if phase not in _PHASES:
        raise Refused("INVALID_PRIVATE_PHASE")
    work = _verified_state(root, base)
    if work is None:
        raise Refused("ALREADY_RECONCILED")
    if _JOURNAL not in {p.name for p in work.iterdir()}:
        raise Refused("PHASE_REQUIRES_JOURNAL")
    if phase == "before_effect_unlink":
        return
    if not (work / _EFFECT).exists():
        raise Refused("EFFECT_REQUIRED_FOR_PHASE")
    (work / _EFFECT).unlink()
    _fsync_dir(work)
    if phase == "after_effect_unlink":
        return
    (work / _JOURNAL).unlink()
    _fsync_dir(work)
    if phase == "after_journal_unlink":
        return
    work.rmdir()
    _fsync_dir(root)


def reconcile_private(root: Path, base: Path) -> dict[str, object]:
    """From durable root anchor: replay despite inner journal being absent."""
    work = _verified_state(root, base)
    if work is not None:
        if (work / _EFFECT).exists():
            (work / _EFFECT).unlink()
            _fsync_dir(work)
        if (work / _JOURNAL).exists():
            (work / _JOURNAL).unlink()
            _fsync_dir(work)
        work.rmdir()
        _fsync_dir(root)
    if {p.name for p in root.iterdir()} != {_ANCHOR}:
        raise Refused("QUARANTINE_RECONCILIATION_INCOMPLETE")
    return {
        "decision": "NO_GO_ANCHORED_PRIVATE_REPLAY_OBSERVED",
        "outer_anchor_preserved": True,
        "work_absent": True,
        **_CEILING,
    }


def retire_fixture(root: Path, base: Path) -> None:
    """Post-test teardown, NOT crash-safe and NOT part of transaction proof.

    The anchor is retained THROUGH reconciliation, then removed only in a
    separate harness-owned teardown step. Interruption of this final step
    can leave a journal-less empty outer dir requiring manual review.
    """
    if _verified_state(root, base) is not None:
        raise Refused("UNFINISHED_WORK_PREVENTS_TEARDOWN")
    (root / _ANCHOR).unlink()
    _fsync_dir(root)
    root.rmdir()
    _fsync_dir(base)


def _phase_worker(root: Path, stage: str, ack_fd: int) -> int:
    _ordinary_user()
    apply_private_phase(root, _PARENT, stage)
    os.write(ack_fd, b"1")
    os.close(ack_fd)
    while True:
        signal.pause()


def _fresh_recovery_worker(root: Path) -> int:
    try:
        answer = reconcile_private(root, _PARENT)
    except (Refused, OSError) as exc:
        answer = {"decision": "QUARANTINE_PRIVATE_REPLAY_REVIEW_REQUIRED",
                  "error": type(exc).__name__, **_CEILING}
    print(json.dumps(answer, sort_keys=True), flush=True)
    return 0 if answer.get("outer_anchor_preserved") is True else 1


def exercise() -> dict[str, object]:
    _ordinary_user()
    results = []
    for stage in _PHASES:
        root = prepare_private(_PARENT)
        read_fd, write_fd = os.pipe()
        try:
            worker = subprocess.Popen(
                [sys.executable, "-I", "-B", str(Path(__file__).resolve()),
                 "--internal-phase", stage, "--internal-root", str(root),
                 "--internal-ack-fd", str(write_fd)],
                pass_fds=(write_fd,), cwd="/", stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                env={"PATH": "/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE": "1"},
            )
        except BaseException:
            os.close(read_fd)
            os.close(write_fd)
            raise
        os.close(write_fd)
        try:
            ready, _, _ = select.select([read_fd], [], [], 5)
            ack = bool(ready and os.read(read_fd, 1) == b"1")
        finally:
            os.close(read_fd)
            if worker.poll() is None:
                worker.kill()  # direct owned worker, never a foreign PID
            status = worker.wait(timeout=5)
        if not ack or status != -signal.SIGKILL:
            raise Refused("QUARANTINE_PHASE_ACK_OR_SIGKILL")
        process = subprocess.run(
            [sys.executable, "-I", "-B", str(Path(__file__).resolve()),
             "--internal-recover", str(root)],
            cwd="/", stdin=subprocess.DEVNULL, capture_output=True,
            text=True, check=False, timeout=10,
            env={"PATH": "/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE": "1"},
        )
        if process.returncode != 0 or len(process.stdout) > 4096:
            raise Refused("QUARANTINE_FRESH_REPLAY_FAILED")
        try:
            outcome = json.loads(process.stdout)
        except ValueError as exc:
            raise Refused("QUARANTINE_REPLAY_OUTPUT_INVALID") from exc
        if (type(outcome) is not dict
                or outcome.get("decision") != "NO_GO_ANCHORED_PRIVATE_REPLAY_OBSERVED"
                or outcome.get("work_absent") is not True
                or outcome.get("outer_anchor_preserved") is not True
                or not (root / _ANCHOR).is_file()
                or (root / _WORK).exists()):
            raise Refused("QUARANTINE_RECOVERY_WITNESS_MISMATCH")
        results.append(stage)
        # Outside crash-safe replay scope: bounded harness teardown.
        retire_fixture(root, _PARENT)
        if root.exists():
            raise Refused("QUARANTINE_PRIVATE_TEARDOWN_LEFTOVER")
    return {
        "stage": "M6.0-M0x",
        "decision": "NO_GO_PRIVATE_CRASH_WINDOWS_REPLAYED",
        "scope": "nonroot_four_sigkill_points_outer_anchor_replayed",
        "crash_points_verified": results,
        "fresh_recovery_processes": len(results),
        "fixture_absent_after_harness_teardown": True,
        **_CEILING,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--inspect", action="store_true")
    action.add_argument("--exercise", action="store_true")
    action.add_argument("--internal-recover", metavar="ROOT", help=argparse.SUPPRESS)
    action.add_argument("--internal-phase", choices=_PHASES, help=argparse.SUPPRESS)
    parser.add_argument("--internal-root", help=argparse.SUPPRESS)
    parser.add_argument("--internal-ack-fd", type=int, help=argparse.SUPPRESS)
    parser.add_argument("--acknowledge")
    args = parser.parse_args(argv)
    if args.internal_phase is not None:
        if (args.internal_root is None or args.internal_ack_fd is None
                or args.acknowledge is not None):
            parser.error("internal phase needs fixed fixture and pipe")
        return _phase_worker(Path(args.internal_root), args.internal_phase,
                             args.internal_ack_fd)
    if args.internal_recover is not None:
        if args.internal_root is not None or args.acknowledge is not None:
            parser.error("internal recovery accepts only fixed fixture")
        return _fresh_recovery_worker(Path(args.internal_recover))
    if args.internal_root is not None or args.internal_ack_fd is not None:
        parser.error("no caller-selected paths or descriptors")
    if args.inspect:
        outcome = {
            "stage": "M6.0-M0x", "decision": "NO_GO_RECOVERY_EXERCISE_NOT_RUN",
            "scope": "read_only_no_kernel_or_guest_state_inspection", **_CEILING,
        }
    elif args.acknowledge != _ACK:
        outcome = {"stage": "M6.0-M0x",
                   "decision": "NO_GO_EXPLICIT_NONROOT_ACK_REQUIRED", **_CEILING}
    else:
        try:
            outcome = exercise()
        except (Refused, OSError, subprocess.TimeoutExpired) as exc:
            outcome = {"stage": "M6.0-M0x",
                       "decision": "QUARANTINE_PRIVATE_LAB_REVIEW_REQUIRED",
                       "error": type(exc).__name__, **_CEILING}
    print(json.dumps(outcome, sort_keys=True))
    return 0 if args.inspect or outcome.get("fixture_absent_after_harness_teardown") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
