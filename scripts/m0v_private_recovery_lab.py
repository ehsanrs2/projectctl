"""M6.0 M0v: actual nonroot SIGKILL + fsynced private-fixture recovery.

No policy, systemd, credentials, ProjectCTL DB or global filesystem writes.
The exercise owns only a fresh unpredictable 0700 test directory. This is
NOT an independently surviving controller or reboot/power-loss test.
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

_BASE = Path("/var/tmp")
_PREFIX = "projectctl-m0v-"
_ACK = "NONROOT_PRIVATE_M0V_SIGKILL_RECOVERY_LAB"
_RECORD = "m0v-journal.json"
_EFFECT = "m0v-effect.marker"
_PAYLOAD = b"M0v disposable effect v1\n"


class Refused(RuntimeError):
    pass


def _fsync_directory(directory: Path) -> None:
    fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _root_scope(root: Path, base: Path) -> None:
    if root.parent != base or not root.name.startswith(_PREFIX):
        raise Refused("OUTSIDE_FIXED_PRIVATE_FIXTURE_SCOPE")
    try:
        p = root.lstat()
        b = base.lstat()
    except OSError as exc:
        raise Refused("FIXTURE_ANCESTRY_UNAVAILABLE") from exc
    if (not stat.S_ISDIR(p.st_mode) or stat.S_IMODE(p.st_mode) != 0o700
            or p.st_uid != os.getuid() or p.st_dev != b.st_dev
            or not stat.S_ISDIR(b.st_mode)):
        raise Refused("UNTRUSTED_FIXTURE_ROOT")


def _write_exclusive(root: Path, leaf: str, raw: bytes) -> None:
    fd = os.open(
        root / leaf, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
        0o600,
    )
    try:
        with os.fdopen(fd, "wb", closefd=False) as out:
            out.write(raw)
            out.flush()
        os.fsync(fd)
    finally:
        os.close(fd)
    _fsync_directory(root)


def _record(root: Path) -> bytes:
    return json.dumps({
        "format": "M0v-private-fixture-v1",
        "nonce": root.name,
        "phase": "armed-before-effect",
        "expected_sha256": hashlib.sha256(_PAYLOAD).hexdigest(),
        "authorizes_policy_install": False,
        "authorizes_migration": False,
    }, sort_keys=True, separators=(",", ":")).encode("ascii") + b"\n"


def _checked_leaf(root: Path, name: str) -> bytes:
    path = root / name
    info = path.lstat()  # no symlink-follow
    if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
            or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) != 0o600):
        raise Refused("UNTRUSTED_PRIVATE_INODE_" + name)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        live = os.fstat(fd)
        if (live.st_dev, live.st_ino) != (info.st_dev, info.st_ino):
            raise Refused("INODE_RACE_" + name)
        data = os.read(fd, 4097)
        if len(data) > 4096:
            raise Refused("OVERSIZED_PRIVATE_LEAF")
        return data
    finally:
        os.close(fd)


def recover_private(root: Path, base: Path) -> str:
    """Known leaves only; unknown/corrupt objects quarantine, never delete."""
    _root_scope(root, base)
    entries = {entry.name for entry in root.iterdir()}
    if entries - {_RECORD, _EFFECT} or _RECORD not in entries:
        raise Refused("QUARANTINE_UNKNOWN_OR_MISSING_JOURNAL")
    if _checked_leaf(root, _RECORD) != _record(root):
        raise Refused("QUARANTINE_JOURNAL_CONTENT_DRIFT")
    if _EFFECT in entries and _checked_leaf(root, _EFFECT) != _PAYLOAD:
        raise Refused("QUARANTINE_EFFECT_CONTENT_DRIFT")
    if _EFFECT in entries:
        (root / _EFFECT).unlink()
        _fsync_directory(root)
    (root / _RECORD).unlink()
    _fsync_directory(root)
    root.rmdir()
    _fsync_directory(base)
    return "NO_GO_PRIVATE_SIGKILL_RECOVERY_OBSERVED"


# Fixed embedded worker, never a user-supplied binary/script or source path.
# Spawn/exec avoids Python-after-fork deadlocks in multi-threaded runners.
_WORKER = r"""
import os
import signal
import sys
from pathlib import Path
root = Path(sys.argv[1])
writefd = int(sys.argv[2])
payload = b'M0v disposable effect v1\n'
fd = os.open(root / 'm0v-effect.marker',
             os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
try:
    os.write(fd, payload)
    os.fsync(fd)
finally:
    os.close(fd)
fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
try:
    os.fsync(fd)
finally:
    os.close(fd)
os.write(writefd, b'1')
os.close(writefd)
while True:
    signal.pause()
"""


def exercise(base: Path = _BASE) -> dict[str, object]:
    """Call only as nonroot; CLI does not expose the base argument."""
    if sys.platform != "linux" or os.getuid() == 0 or os.geteuid() == 0:
        raise Refused("NONROOT_LINUX_REQUIRED")
    if not base.is_dir() or base.is_symlink():
        raise Refused("UNSAFE_FIXTURE_PARENT")
    root = Path(tempfile.mkdtemp(prefix=_PREFIX, dir=base))
    _root_scope(root, base)
    _fsync_directory(base)  # persist newly created directory entry
    _write_exclusive(root, _RECORD, _record(root))
    readfd, writefd = os.pipe()
    try:
        child = subprocess.Popen(
            [sys.executable, "-I", "-B", "-c", _WORKER,
             str(root), str(writefd)],
            pass_fds=(writefd,),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            cwd="/",
            env={"PATH": "/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE": "1"},
        )
    except BaseException:
        os.close(readfd)
        os.close(writefd)
        raise
    os.close(writefd)
    acked = False
    status = None
    try:
        ready, _, _ = select.select([readfd], [], [], 5.0)
        acked = bool(ready and os.read(readfd, 1) == b"1")
    finally:
        os.close(readfd)
        # Kill only our direct subprocess handle, never search for other PIDs.
        if child.poll() is None:
            child.kill()
        status = child.wait(timeout=5)
    if not acked or status != -signal.SIGKILL:
        raise Refused("QUARANTINE_CHILD_ACK_OR_KILL_NOT_VERIFIED")
    decision = recover_private(root, base)
    return {
        "stage": "M6.0-M0v",
        "decision": decision,
        "evidence_scope": "real_nonroot_sigkill_plus_private_fsynced_fixture_only",
        "child_sigkill_observed": True,
        "private_journal_reconciled": True,
        "fixture_absent_after_recovery": not root.exists(),
        "authorizes_root_trial": False,
        "authorizes_policy_install": False,
        "authorizes_migration": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--inspect", action="store_true")
    action.add_argument("--exercise", action="store_true")
    parser.add_argument("--acknowledge")
    args = parser.parse_args(argv)
    if args.inspect:
        result = {
            "stage": "M6.0-M0v",
            "decision": "NO_GO_PRIVATE_RECOVERY_EXERCISE_NOT_RUN",
            "scope": "read_only_cli_contract",
            "authorizes_root_trial": False,
            "authorizes_policy_install": False,
            "authorizes_migration": False,
        }
    elif args.acknowledge != _ACK:
        result = {
            "stage": "M6.0-M0v",
            "decision": "NO_GO_EXPLICIT_NONROOT_FIXTURE_ACK_REQUIRED",
            "authorizes_root_trial": False,
            "authorizes_policy_install": False,
            "authorizes_migration": False,
        }
    else:
        try:
            result = exercise()
        except (Refused, OSError) as exc:
            result = {
                "stage": "M6.0-M0v",
                "decision": "QUARANTINE_PRIVATE_FIXTURE_REVIEW_REQUIRED",
                "error": type(exc).__name__,
                "authorizes_root_trial": False,
                "authorizes_policy_install": False,
                "authorizes_migration": False,
            }
    print(json.dumps(result, sort_keys=True))
    return 0 if result.get("private_journal_reconciled") or args.inspect else 1


if __name__ == "__main__":
    raise SystemExit(main())
