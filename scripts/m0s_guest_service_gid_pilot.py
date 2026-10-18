"""M6.0 M0s — opt-in, KVM-GUEST-ONLY, root-owned disposable GID counterexample.

No systemd unit, AppArmor profile, OS account, existing project, WAL
backup, SQLite v3 schema or source migration is changed by this script.
Never run --run on a host or any guest with host/production shared mounts.

The synthetic "approved" and "old" actors deliberately execute exactly
the same embedded Python code with different credentials. This is a
negative proof about DAC credential distribution, NOT authentication of a
future real ProjectCTL trusted v3 writer.
"""
from __future__ import annotations

import argparse
import errno
import grp
import json
import os
import pwd
import shutil
import sqlite3
import stat
import subprocess
import sys
import tempfile
from dataclasses import fields
from pathlib import Path

from projectctl.storage.sqlite import (
    APPLICATION_ID, PROJECT_STATE_DB_VERSION, initialize_project_state_db,
    inspect_db,
)
from scripts.m0s_service_gid_contract import GidWitnesses, review

_PARENT = Path("/var/tmp")
_PREFIX = "projectctl-m0s-"
_LEGACY_UID = 63071
_CANDIDATE_UID = 63072
_SERVICE_WRITE_GID = 63073
_ACK = "DISPOSABLE_KVM_GUEST_M0S_SERVICE_ONLY_GID_NEGATIVE_LAB"

_ACTOR = r"""
import json
import os
import sqlite3
import sys
from pathlib import Path

root, op, label = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
os.umask(0o007)  # restrict newly staged dummy JSON and sidecars
p = root / ".projectctl"
try:
    if op == "probe":
        fd = os.open(p / "state.sqlite", os.O_RDWR | os.O_NOFOLLOW)
        os.close(fd)
    elif op == "db":
        with sqlite3.connect(p / "state.sqlite", timeout=3) as db:
            db.execute(
                "INSERT INTO m0s_disposable_probe(actor) VALUES (?)", (label,)
            )
    elif op == "json":
        stage = p / "m0s-stage.tmp"
        stage.write_bytes(json.dumps({"m0s": label}).encode("utf-8"))
        os.replace(stage, p / "m0s.json")
    else:
        raise RuntimeError("unknown_owned_actor_operation")
except (OSError, sqlite3.Error) as error:
    print(json.dumps({
        "status": "denied",
        "errno": getattr(error, "errno", None),
        "error": type(error).__name__,
    }), flush=True)
else:
    print(json.dumps({"status": "wrote"}), flush=True)
"""


class Refused(RuntimeError):
    """Treat any unexpected host/fixture state as a lab failure."""


def _fixed_capture(args: list[str]) -> str:
    try:
        result = subprocess.run(
            args, check=False, text=True, capture_output=True, timeout=6,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"
    if result.returncode != 0:
        return "unknown"
    return result.stdout.strip()


def _vm() -> str:
    return _fixed_capture(["systemd-detect-virt", "--vm"])


def _fstype() -> str:
    return _fixed_capture(["findmnt", "-T", str(_PARENT), "-no", "FSTYPE"])


def _unused_nss_identifier(value: int) -> bool:
    try:
        pwd.getpwuid(value)
    except KeyError:
        pass
    else:
        return False
    try:
        grp.getgrgid(value)
    except KeyError:
        pass
    else:
        return False
    return True


def _guest_python() -> str:
    p = Path(sys.executable).resolve()
    if p.parent != Path("/usr/bin") or not p.name.startswith("python3"):
        raise Refused("SYSTEM_PYTHON_IN_USR_BIN_REQUIRED")
    if not p.is_file():
        raise Refused("SYSTEM_PYTHON_NOT_REGULAR")
    return str(p)


def _preflight(acknowledge: str | None) -> None:
    if sys.platform != "linux" or _vm() not in ("kvm", "qemu"):
        raise Refused("NOT_DISPOSABLE_KVM_QEMU_LINUX_GUEST")
    if _fstype() != "ext4":
        raise Refused("VAR_TMP_NOT_EXT4")
    if acknowledge != _ACK:
        raise Refused("EXACT_DISPOSABLE_GUEST_ACK_MISSING")
    if os.getuid() != 0 or os.geteuid() != 0:
        raise Refused("ROOT_IN_GUEST_REQUIRED")
    origin = (
        os.environ.get("SUDO_UID"), os.environ.get("SUDO_GID"),
        os.environ.get("SUDO_USER"),
    )
    if not all(origin) or not origin[0].isdecimal() or not origin[1].isdecimal():
        raise Refused("NONROOT_SUDO_INVOKER_REQUIRED")
    uid, gid = int(origin[0]), int(origin[1])
    if uid <= 0 or gid <= 0:
        raise Refused("INVALID_SUDO_INVOKER")
    try:
        account = pwd.getpwuid(uid)
    except KeyError as exc:
        raise Refused("UNKNOWN_SUDO_INVOKER") from exc
    if account.pw_name != origin[2] or account.pw_gid != gid:
        raise Refused("SUDO_INVOKER_IDENTITY_MISMATCH")
    directory = _PARENT.lstat()
    if (not stat.S_ISDIR(directory.st_mode)
            or directory.st_uid != 0
            or (directory.st_mode & stat.S_IWOTH
                and not directory.st_mode & stat.S_ISVTX)):
        raise Refused("UNSAFE_VAR_TMP_PARENT")
    for identifier in (_LEGACY_UID, _CANDIDATE_UID, _SERVICE_WRITE_GID):
        if not _unused_nss_identifier(identifier):
            raise Refused("FIXED_TEST_UID_OR_GID_ALREADY_REGISTERED")
    _guest_python()


def _drop_credentials(uid: int, with_writer_group: bool) -> None:
    # Fixed guest-only numeric identities, never supplied by a CLI caller.
    os.setgroups([_SERVICE_WRITE_GID] if with_writer_group else [])
    os.setresgid(uid, uid, uid)
    os.setresuid(uid, uid, uid)


def _actor(root: Path, uid: int, writer_group: bool, op: str, label: str) -> dict:
    if uid not in (_LEGACY_UID, _CANDIDATE_UID):
        raise Refused("UNKNOWN_TEST_ACTOR_UID")
    if op not in ("probe", "db", "json"):
        raise Refused("UNKNOWN_TEST_ACTOR_OPERATION")
    result = subprocess.run(
        [_guest_python(), "-I", "-B", "-c", _ACTOR, str(root), op, label],
        check=False, timeout=15, text=True, capture_output=True, cwd="/",
        stdin=subprocess.DEVNULL,
        preexec_fn=lambda: _drop_credentials(uid, writer_group),
        env={"PATH": "/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE": "1"},
    )
    if result.returncode != 0:
        raise Refused("OWNED_SYNTHETIC_ACTOR_EXITED_NONZERO")
    try:
        obj = json.loads(result.stdout.strip())
    except (ValueError, TypeError) as exc:
        raise Refused("OWNED_SYNTHETIC_ACTOR_BAD_JSON") from exc
    if type(obj) is not dict or obj.get("status") not in ("wrote", "denied"):
        raise Refused("OWNED_SYNTHETIC_ACTOR_BAD_STATUS")
    return obj


def _attempt(root: Path, uid: int, writer_group: bool, label: str) -> dict:
    return {
        op: _actor(root, uid, writer_group, op, label)
        for op in ("probe", "db", "json")
    }


def _denied(outcomes: dict) -> bool:
    return (
        outcomes["probe"].get("status") == "denied"
        and outcomes["probe"].get("errno") in (errno.EACCES, errno.EPERM)
        and all(outcomes[op].get("status") == "denied" for op in ("db", "json"))
    )


def _wrote(outcomes: dict) -> bool:
    return all(
        outcomes[op].get("status") == "wrote"
        for op in ("probe", "db", "json")
    )


def _fixture(root: Path) -> Path:
    if root.parent != _PARENT or not root.name.startswith(_PREFIX):
        raise Refused("NOT_NEW_PRIVATE_M0S_FIXTURE")
    if os.path.ismount(root):
        raise Refused("FIXTURE_MUST_NOT_BE_MOUNT")
    top = root.lstat()
    if not stat.S_ISDIR(top.st_mode) or top.st_uid != 0:
        raise Refused("FIXTURE_NOT_ROOT_OWNED")
    state = root / ".projectctl"
    state.mkdir(mode=0o700)
    initialize_project_state_db(state / "state.sqlite")
    if PROJECT_STATE_DB_VERSION != 2 or inspect_db(
        state / "state.sqlite"
    ) != (APPLICATION_ID, 2):
        raise Refused("NOT_REAL_INITIALIZED_V2_SQLITE")
    with sqlite3.connect(state / "state.sqlite") as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute(
            "CREATE TABLE m0s_disposable_probe("
            "id INTEGER PRIMARY KEY, actor TEXT NOT NULL)"
        )
    (state / "m0s.json").write_bytes(b'{"m0s":"initial"}')
    os.chmod(root, 0o711)
    return state


def _check_private_scope(root: Path, state: Path) -> list[Path]:
    top = root.lstat()
    expected = {"state.sqlite", "state.sqlite-wal", "state.sqlite-shm",
                "m0s.json"}
    if state.parent != root or state.name != ".projectctl":
        raise Refused("UNKNOWN_FIXTURE_STATE_ANCESTRY")
    directory = state.lstat()
    if (not stat.S_ISDIR(directory.st_mode)
            or directory.st_uid != 0 or directory.st_dev != top.st_dev
            or os.path.ismount(state)):
        raise Refused("UNEXPECTED_STATE_DIRECTORY")
    listed = list(state.iterdir())
    if {p.name for p in listed} - expected:
        raise Refused("UNEXPECTED_DISPOSABLE_STATE_LEAF")
    if "state.sqlite" not in {p.name for p in listed}:
        raise Refused("MISSING_DISPOSABLE_STATE_DB")
    for path in listed:
        entry = path.lstat()
        if (not stat.S_ISREG(entry.st_mode) or entry.st_uid != 0
                or entry.st_nlink != 1 or entry.st_dev != top.st_dev):
            raise Refused("UNSAFE_FIXTURE_INODE_OR_HARDLINK")
    return listed


def _snapshot(root: Path) -> tuple[int, bytes]:
    state = root / ".projectctl"
    with sqlite3.connect(state / "state.sqlite") as db:
        count = db.execute(
            "SELECT COUNT(*) FROM m0s_disposable_probe"
        ).fetchone()[0]
    return count, (state / "m0s.json").read_bytes()


def _grant_only_fixture_group(root: Path, state: Path) -> None:
    # Unlike a production migration, no recursion, no caller-chosen path.
    # Check each script-created inode before mutating its group/permissions.
    leaves = _check_private_scope(root, state)
    for path in leaves:
        os.chown(path, 0, _SERVICE_WRITE_GID, follow_symlinks=False)
        os.chmod(path, 0o660, follow_symlinks=False)
    os.chown(state, 0, _SERVICE_WRITE_GID, follow_symlinks=False)
    # setgid ensures *new* SQLite WAL/SHM and JSON staging inherit GID.
    os.chmod(state, 0o2770, follow_symlinks=False)


def _trial() -> dict:
    root = Path(tempfile.mkdtemp(prefix=_PREFIX, dir=_PARENT))
    try:
        state = _fixture(root)
        anchored = bool(_check_private_scope(root, state))
        baseline = _snapshot(root)
        # With no private writer group on the state tree, both UID-only actors
        # must be unable to open new DB or create staging leaves.
        legacy_off = _denied(_attempt(root, _LEGACY_UID, False, "legacy-off"))
        candidate_off = _denied(
            _attempt(root, _CANDIDATE_UID, False, "candidate-off")
        )
        if _snapshot(root) != baseline:
            raise Refused("EMBARGO_FIXTURE_WAS_MUTATED")
        _grant_only_fixture_group(root, state)

        # Simulated fixture release: no actual v3 runtime or service exists.
        legacy_denied = _denied(
            _attempt(root, _LEGACY_UID, False, "legacy-after-release")
        )
        candidate_denied = _denied(
            _attempt(root, _CANDIDATE_UID, False, "direct-without-gid")
        )
        negatives_preserved = _snapshot(root) == baseline
        if not negatives_preserved:
            raise Refused("DIRECT_UID_ACTOR_MUTATED_GROUP_GATED_FIXTURE")

        approved_synthetic = _wrote(
            _attempt(root, _CANDIDATE_UID, True, "candidate-with-gid")
        )
        # NEGATIVE finding: exactly the same Python program, using the
        # same candidate UID + private GID, writes under an old-code label.
        old_synthetic_same_credentials = _wrote(
            _attempt(root, _CANDIDATE_UID, True, "old-code-with-gid")
        )
        observations = GidWitnesses(
            source_stayed_v2=inspect_db(
                state / "state.sqlite"
            ) == (APPLICATION_ID, 2),
            fixture_root_anchored=anchored,
            embargo_denied_legacy_uid=legacy_off,
            embargo_denied_candidate_uid=candidate_off,
            released_legacy_uid_denied_db_json=legacy_denied,
            released_candidate_uid_without_gid_denied_db_json=candidate_denied,
            candidate_uid_with_gid_wrote_db_json=approved_synthetic,
            old_code_with_candidate_uid_and_gid_wrote_db_json=(
                old_synthetic_same_credentials
            ),
            negatives_preserved_sqlite_and_json=negatives_preserved,
        )
        decision = review(observations)
        return {
            "stage": "M6.0-M0s",
            "decision": decision.decision,
            "authorizes_migration": False,
            "authorizes_policy_install": False,
            "guest_virt": _vm(),
            "guest_fs": _fstype(),
            "observations": {
                item.name: getattr(observations, item.name)
                for item in fields(GidWitnesses)
            },
            "coverage": (
                "disposable-root-file DAC + numeric UID/supplementary GID "
                "only; synthetic Python, no AppArmor/profile, systemd unit, "
                "real v3, all-writer/FD drain or global start embargo"
            ),
        }
    finally:
        # Only remove this fresh, locally created fixture; no glob cleanup.
        shutil.rmtree(root)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--inspect", action="store_true")
    action.add_argument("--run", action="store_true")
    parser.add_argument("--acknowledge")
    options = parser.parse_args(argv)
    if options.inspect:
        print(json.dumps({
            "stage": "M6.0-M0s",
            "decision": "OWNER_GUEST_REVIEW_REQUIRED",
            "authorizes_migration": False,
            "authorizes_policy_install": False,
            "guest_virt": _vm(),
            "guest_fs": _fstype(),
            "scope": "read_only_hints_not_closed_world_attestation",
        }, sort_keys=True))
        return 0
    try:
        _preflight(options.acknowledge)
        report = _trial()
    except Exception as error:
        report = {
            "stage": "M6.0-M0s",
            "decision": "NO_GO_DISPOSABLE_LAB_REFUSED",
            "reason": str(error) if isinstance(error, Refused)
                      else type(error).__name__,
            "authorizes_migration": False,
            "authorizes_policy_install": False,
        }
    print(json.dumps(report, sort_keys=True))
    return (
        0 if report["decision"] == "NO_GO_OLD_CODE_WITH_SERVICE_GID_CAN_WRITE"
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
