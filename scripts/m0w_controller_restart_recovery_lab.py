"""M6.0-M0w — ordinary-user controller-death / fresh-process private recovery.

NEVER install or load systemd/AppArmor; never touch a real ProjectCTL DB.
A NEW controller process is SIGKILLed after fsyncing a private effect.
A NEW, separate Python interpreter recovers only a bounded fixture using
a persistent journal. The surviving harness launches that process: this
is NOT automatic boot recovery, power-loss durability or kernel attestation.
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
_PREFIX = "projectctl-m0w-"
_JOURNAL = "m0w-intent.json"
_EFFECT = "m0w-private-effect.bin"
_EFFECT_BYTES = b"M0w test-only controller effect\n"
_ACK = "NONROOT_M0W_CONTROLLER_RESTART_PRIVATE_RECOVERY"
_JOURNAL_LIMIT = 4096

# The only controller program is embedded and fixed; it never opens project data.
_CONTROLLER = r"""
import os
import signal
import sys
from pathlib import Path
root = Path(sys.argv[1])
notify = int(sys.argv[2])
fd = os.open(root / "m0w-private-effect.bin",
             os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
try:
    with os.fdopen(fd, "wb", closefd=False) as out:
        out.write(b"M0w test-only controller effect\n")
        out.flush()
    os.fsync(fd)
finally:
    os.close(fd)
directory_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
try:
    os.fsync(directory_fd)
finally:
    os.close(directory_fd)
os.write(notify, b"R")
os.close(notify)
while True:
    signal.pause()
"""


class Refused(RuntimeError):
    """Unexpected fixture state: preserve evidence instead of deleting."""


def _no_privilege() -> None:
    if sys.platform != "linux" or os.getuid() == 0 or os.geteuid() == 0:
        raise Refused("NONROOT_LINUX_ONLY")


def _sync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _scope(root: Path, parent: Path) -> None:
    _no_privilege()
    if not root.is_absolute() or root.parent != parent or not root.name.startswith(_PREFIX):
        raise Refused("OUT_OF_PRIVATE_SCOPE")
    if not parent.is_absolute() or parent.is_symlink():
        raise Refused("UNSAFE_PARENT")
    try:
        rs, bs = root.lstat(), parent.lstat()
    except OSError as exc:
        raise Refused("UNKNOWN_PARENT_OR_FIXTURE") from exc
    if (not stat.S_ISDIR(bs.st_mode) or not stat.S_ISDIR(rs.st_mode)
            or rs.st_dev != bs.st_dev or rs.st_uid != os.getuid()
            or stat.S_IMODE(rs.st_mode) != 0o700):
        raise Refused("UNTRUSTED_PRIVATE_ROOT")


def _record(root: Path) -> bytes:
    return (json.dumps({
        "format": "m0w-nonroot-journal-v1",
        "fixture": root.name,
        "phase": "prepared-before-controller",
        "effect_sha256": hashlib.sha256(_EFFECT_BYTES).hexdigest(),
        "authorizes_root_trial": False,
        "authorizes_policy_install": False,
        "authorizes_migration": False,
    }, sort_keys=True, separators=(",", ":")) + "\n").encode("ascii")


def _write_new(root: Path, name: str, value: bytes) -> None:
    fd = os.open(
        root / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
        0o600,
    )
    try:
        with os.fdopen(fd, "wb", closefd=False) as out:
            out.write(value)
            out.flush()
        os.fsync(fd)
    finally:
        os.close(fd)
    _sync_dir(root)


def _read_owned_leaf(root: Path, name: str) -> bytes:
    path = root / name
    try:
        before = path.lstat()
    except OSError as exc:
        raise Refused("MISSING_PRIVATE_LEAF_" + name) from exc
    if (not stat.S_ISREG(before.st_mode) or before.st_uid != os.getuid()
            or before.st_nlink != 1 or stat.S_IMODE(before.st_mode) != 0o600):
        raise Refused("UNTRUSTED_PRIVATE_LEAF_" + name)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        after = os.fstat(fd)
        if (after.st_dev, after.st_ino) != (before.st_dev, before.st_ino):
            raise Refused("PRIVATE_INODE_CHANGED_" + name)
        result = os.read(fd, _JOURNAL_LIMIT + 1)
        if len(result) > _JOURNAL_LIMIT:
            raise Refused("OVERSIZED_PRIVATE_LEAF_" + name)
        return result
    finally:
        os.close(fd)


def reconcile_private(root: Path, parent: Path) -> dict[str, object]:
    """Fresh-process recovery from disk; unknown/changed objects quarantine."""
    _scope(root, parent)
    children = {entry.name for entry in root.iterdir()}
    if _JOURNAL not in children or children - {_JOURNAL, _EFFECT}:
        raise Refused("QUARANTINE_MISSING_JOURNAL_OR_UNEXPECTED_LEAF")
    if _read_owned_leaf(root, _JOURNAL) != _record(root):
        raise Refused("QUARANTINE_JOURNAL_CONTENT_DRIFT")
    if _EFFECT in children and _read_owned_leaf(root, _EFFECT) != _EFFECT_BYTES:
        raise Refused("QUARANTINE_EFFECT_CONTENT_DRIFT")
    if _EFFECT in children:
        (root / _EFFECT).unlink()
        _sync_dir(root)
    (root / _JOURNAL).unlink()
    _sync_dir(root)
    root.rmdir()
    _sync_dir(parent)
    return {
        "decision": "NO_GO_FRESH_PROCESS_PRIVATE_RECOVERY_OBSERVED",
        "journal_replayed_from_disk": True,
        "fixture_absent_after_recovery": not root.exists(),
        "authorizes_root_trial": False,
        "authorizes_policy_install": False,
        "authorizes_migration": False,
    }


def _worker_main(root_argument: str) -> int:
    """Internal-only, nonroot, fixed /var/tmp restricted. No generic rm CLI."""
    try:
        outcome = reconcile_private(Path(root_argument), _PARENT)
    except (OSError, Refused) as exc:
        outcome = {
            "decision": "QUARANTINE_PRIVATE_RECOVERY_REVIEW_REQUIRED",
            "reason": str(exc)[:120],
            "authorizes_root_trial": False,
            "authorizes_policy_install": False,
            "authorizes_migration": False,
        }
    print(json.dumps(outcome, sort_keys=True))
    return 0 if outcome.get("journal_replayed_from_disk") is True else 1


def exercise() -> dict[str, object]:
    """The disposable harness survives; both controller and recovery are new PIDs."""
    _no_privilege()
    if not _PARENT.is_dir() or _PARENT.is_symlink():
        raise Refused("UNSAFE_FIXED_VAR_TMP")
    root = Path(tempfile.mkdtemp(prefix=_PREFIX, dir=_PARENT))
    _scope(root, _PARENT)
    _sync_dir(_PARENT)
    _write_new(root, _JOURNAL, _record(root))  # journal is durable *first*
    read_fd, notify_fd = os.pipe()
    try:
        controller = subprocess.Popen(
            [sys.executable, "-I", "-B", "-c", _CONTROLLER, str(root), str(notify_fd)],
            pass_fds=(notify_fd,),
            cwd="/", stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            env={"PATH": "/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE": "1"},
        )
    except BaseException:
        os.close(read_fd)
        os.close(notify_fd)
        raise
    os.close(notify_fd)
    try:
        readable, _, _ = select.select([read_fd], [], [], 5)
        ack = bool(readable and os.read(read_fd, 1) == b"R")
    finally:
        os.close(read_fd)
        if controller.poll() is None:
            controller.kill()  # only direct test controller, never arbitrary guest PID
        exit_code = controller.wait(timeout=5)
    if not ack or exit_code != -signal.SIGKILL:
        raise Refused("QUARANTINE_CONTROLLER_ACK_OR_SIGKILL_NOT_VERIFIED")
    # Starts a completely fresh interpreter after the controller is dead.
    # No inherited Python globals or IPC descriptors pass to recovery.
    try:
        recovery = subprocess.run(
            [sys.executable, "-I", "-B", str(Path(__file__).resolve()),
             "--internal-recover-private", str(root)],
            cwd="/", stdin=subprocess.DEVNULL, capture_output=True,
            text=True, check=False, timeout=10,
            env={"PATH": "/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE": "1"},
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise Refused("QUARANTINE_INDEPENDENT_PROCESS_RECOVERY_FAILED") from exc
    if recovery.returncode != 0 or len(recovery.stdout) > 4096:
        raise Refused("QUARANTINE_RECOVERY_PROCESS_DID_NOT_VERIFY")
    try:
        parsed = json.loads(recovery.stdout)
    except ValueError as exc:
        raise Refused("QUARANTINE_RECOVERY_OUTPUT_MALFORMED") from exc
    if (type(parsed) is not dict
            or parsed.get("decision") != "NO_GO_FRESH_PROCESS_PRIVATE_RECOVERY_OBSERVED"
            or parsed.get("journal_replayed_from_disk") is not True
            or parsed.get("fixture_absent_after_recovery") is not True
            or root.exists()):
        raise Refused("QUARANTINE_RECOVERY_ATTESTATION_MISMATCH")
    return {
        "stage": "M6.0-M0w",
        "decision": parsed["decision"],
        "scope": "nonroot_disk_journal_new_recovery_process_after_controller_sigkill",
        "controller_sigkill_observed": True,
        "fresh_recovery_process_completed": True,
        "journal_replayed_from_disk": True,
        "fixture_absent_after_recovery": True,
        "authorizes_root_trial": False,
        "authorizes_policy_install": False,
        "authorizes_migration": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--inspect", action="store_true")
    action.add_argument("--exercise", action="store_true")
    action.add_argument("--internal-recover-private", metavar="ROOT", help=argparse.SUPPRESS)
    parser.add_argument("--acknowledge")
    args = parser.parse_args(argv)
    if args.internal_recover_private is not None:
        if args.acknowledge is not None:
            parser.error("internal recovery cannot accept acknowledgement")
        return _worker_main(args.internal_recover_private)
    if args.inspect:
        outcome = {
            "stage": "M6.0-M0w", "decision": "NO_GO_PRIVATE_CONTROLLER_RECOVERY_NOT_RUN",
            "scope": "read_only_no_kernel_inspection",
            "authorizes_root_trial": False,
            "authorizes_policy_install": False,
            "authorizes_migration": False,
        }
    elif args.acknowledge != _ACK:
        outcome = {
            "stage": "M6.0-M0w", "decision": "NO_GO_NONROOT_EXERCISE_ACK_MISSING",
            "authorizes_root_trial": False,
            "authorizes_policy_install": False,
            "authorizes_migration": False,
        }
    else:
        try:
            outcome = exercise()
        except (Refused, OSError) as exc:
            outcome = {
                "stage": "M6.0-M0w",
                "decision": "QUARANTINE_PRIVATE_CONTROLLER_RECOVERY_REVIEW_REQUIRED",
                "error": type(exc).__name__,
                "authorizes_root_trial": False,
                "authorizes_policy_install": False,
                "authorizes_migration": False,
            }
    print(json.dumps(outcome, sort_keys=True))
    return 0 if args.inspect or outcome.get("fresh_recovery_process_completed") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
