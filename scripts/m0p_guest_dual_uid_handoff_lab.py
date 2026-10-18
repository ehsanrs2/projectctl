"""M6.0 M0p: ROOT-OPT-IN DISPOSABLE Debian KVM dual-UID *negative* pilot.

NEVER execute on a production host. No project path, user name, service unit,
migration command, or UID is caller-selectable. Creates and mutates ONLY an
owned unique disposable fixture under guest-local /var/tmp. Synthetic writers
use sqlite3 from the standard library against a real initialized v2 DB;
they are NOT an operational v3 writer, an attested v2 binary, or an embargo.
"""
from __future__ import annotations

import argparse
import errno
import grp
import json
import os
import pwd
import select
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
from scripts.m0p_guest_handoff_contract import LabObservations, review

_ACK = "DISPOSABLE_KVM_GUEST_M0P_DUAL_UID_NEGATIVE_LAB"
_PARENT = Path("/var/tmp")
_LEGACY_UID = 63071
_CANDIDATE_UID = 63072
# No NSS passwd or group entries are created; these temporary numeric
# credentials are permitted only in a separately reviewed disposable VM.
_ACTOR = r"""
import json
import os
import sqlite3
import sys
from pathlib import Path

root, op = Path(sys.argv[1]), sys.argv[2]
state = root / ".projectctl"
try:
    if op == "db":
        with sqlite3.connect(state / "state.sqlite", timeout=2) as db:
            db.execute(
                "INSERT INTO m0p_disposable_probe (actor) VALUES (?)",
                (sys.argv[3],),
            )
    elif op == "json":
        stage = state / "m0p.stage"
        stage.write_bytes(b'{"disposable":true}')
        os.replace(stage, state / "m0p.json")
    elif op == "probe":
        fd = os.open(
            state / "m0p-preopened.bin",
            os.O_WRONLY | os.O_NOFOLLOW,
        )
        os.close(fd)
    elif op == "fd":
        fd = os.open(
            state / "m0p-preopened.bin",
            os.O_WRONLY | os.O_APPEND | os.O_NOFOLLOW,
        )
        print(json.dumps({"phase": "ready"}), flush=True)
        if sys.stdin.readline().strip() != "GO":
            raise RuntimeError("owned_fd_actor_invalid_handshake")
        try:
            count = os.write(fd, b"M0P_OLD_FD")
            os.fsync(fd)
        finally:
            os.close(fd)
        print(json.dumps({"phase": "wrote", "count": count}), flush=True)
        sys.exit(0)
    else:
        raise RuntimeError("unexpected_disposable_operation")
except (OSError, sqlite3.Error) as error:
    print(json.dumps({
        "status": "denied",
        "errno": getattr(error, "errno", None),
        "error": type(error).__name__,
    }), flush=True)
else:
    print(json.dumps({"status": "wrote"}), flush=True)
"""


class GuestLabRefused(RuntimeError):
    """Refuse an unreviewed or anomalous guest experiment."""


def _output(command: list[str]) -> str:
    try:
        cp = subprocess.run(
            command, check=False, capture_output=True, text=True, timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"
    return cp.stdout.strip() if cp.returncode == 0 else "unknown"


def _virtualization() -> str:
    return _output(["systemd-detect-virt", "--vm"])


def _filesystem() -> str:
    return _output(["findmnt", "-T", str(_PARENT), "-no", "FSTYPE"])


def _must_be_unused(uid: int) -> None:
    try:
        pwd.getpwuid(uid)
    except KeyError:
        pass
    else:
        raise GuestLabRefused("FIXED_TEST_UID_ALREADY_IN_PASSWD")
    try:
        grp.getgrgid(uid)
    except KeyError:
        pass
    else:
        raise GuestLabRefused("FIXED_TEST_GID_ALREADY_IN_GROUP")


def _preflight(ack: str | None) -> None:
    if sys.platform != "linux" or _virtualization() not in {"kvm", "qemu"}:
        raise GuestLabRefused("NOT_A_KVM_QEMU_LINUX_GUEST")
    if _filesystem() != "ext4":
        raise GuestLabRefused("VAR_TMP_NOT_GUEST_LOCAL_EXT4")
    if ack != _ACK:
        raise GuestLabRefused("EXPLICIT_DISPOSABLE_GUEST_ACK_MISSING")
    if os.getuid() != 0 or os.geteuid() != 0:
        raise GuestLabRefused("ROOT_WITHIN_GUEST_REQUIRED")
    suid, sgid, sname = (
        os.environ.get("SUDO_UID"),
        os.environ.get("SUDO_GID"),
        os.environ.get("SUDO_USER"),
    )
    if not suid or not sgid or not suid.isdecimal() or not sgid.isdecimal():
        raise GuestLabRefused("SUDO_NONROOT_INVOKER_REQUIRED")
    invoking_uid, invoking_gid = int(suid), int(sgid)
    if invoking_uid <= 0 or invoking_gid <= 0 or not sname:
        raise GuestLabRefused("INVALID_NONROOT_SUDO_INVOKER")
    try:
        user = pwd.getpwuid(invoking_uid)
    except KeyError as exc:
        raise GuestLabRefused("SUDO_ACCOUNT_NOT_IN_PASSWD") from exc
    if user.pw_name != sname or user.pw_gid != invoking_gid:
        raise GuestLabRefused("SUDO_IDENTITY_MISMATCH")
    parent = _PARENT.lstat()
    if (not stat.S_ISDIR(parent.st_mode) or parent.st_uid != 0
            or (parent.st_mode & stat.S_IWOTH
                and not parent.st_mode & stat.S_ISVTX)):
        raise GuestLabRefused("UNSAFE_GUEST_TMP_PARENT")
    _must_be_unused(_LEGACY_UID)
    _must_be_unused(_CANDIDATE_UID)


def _drop(uid: int) -> None:
    os.setgroups([])
    os.setgid(uid)
    os.setuid(uid)


def _command(root: Path, operation: str, tag: str) -> list[str]:
    python = str(Path(sys.executable).resolve())
    if not python.startswith("/usr/bin/"):
        # Actors must never need to traverse the operator's private venv.
        raise GuestLabRefused("GUEST_SYSTEM_PYTHON_REQUIRED")
    return [python, "-B", "-c", _ACTOR, str(root), operation, tag]


def _execute(root: Path, op: str, uid: int, tag: str = "SYNTHETIC") -> dict:
    cp = subprocess.run(
        _command(root, op, tag),
        preexec_fn=lambda: _drop(uid),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd="/",
        env={"PATH": "/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE": "1"},
        check=False,
        timeout=12,
    )
    if cp.returncode != 0:
        raise GuestLabRefused("DISPOSABLE_ACTOR_FAILED_NONZERO")
    try:
        result = json.loads(cp.stdout.strip())
        if type(result) is not dict or result.get("status") not in ("denied", "wrote"):
            raise ValueError("invalid_actor_status")
        return result
    except (ValueError, TypeError) as exc:
        raise GuestLabRefused("DISPOSABLE_ACTOR_MALFORMED_OUTPUT") from exc


def _controlled_tree_ownership(root: Path, uid: int) -> None:
    """Operate only on a script-owned random child, never caller-provided data.

    No symlinks, hardlinks or mount/device crossings are permitted; this is
    NOT a generic secure recursive chown implementation for live projects.
    """
    if root.parent != _PARENT or not root.name.startswith("projectctl-m0p-"):
        raise GuestLabRefused("NOT_A_SCRIPT_OWNED_DISPOSABLE_ROOT")
    anchor = root.lstat()
    if not stat.S_ISDIR(anchor.st_mode) or anchor.st_uid != 0:
        raise GuestLabRefused("DISPOSABLE_ROOT_IDENTITY_INVALID")
    state = root / ".projectctl"
    entries = [state, *state.rglob("*")]
    for p in entries:
        s = p.lstat()
        if s.st_dev != anchor.st_dev or not (
            stat.S_ISDIR(s.st_mode) or stat.S_ISREG(s.st_mode)
        ):
            raise GuestLabRefused("UNSAFE_LAB_PATH_OR_DEVICE")
        if stat.S_ISREG(s.st_mode) and s.st_nlink != 1:
            raise GuestLabRefused("UNSAFE_LAB_HARDLINK")
        if os.path.ismount(p):
            raise GuestLabRefused("UNSAFE_LAB_NESTED_MOUNT")
    for p in sorted(entries, key=lambda item: len(item.parts), reverse=True):
        is_dir = stat.S_ISDIR(p.lstat().st_mode)
        os.chown(p, uid, uid, follow_symlinks=False)
        os.chmod(p, 0o700 if is_dir else 0o600, follow_symlinks=False)


def _create_fixture(root: Path) -> None:
    state = root / ".projectctl"
    initialize_project_state_db(state / "state.sqlite")
    if inspect_db(state / "state.sqlite") != (APPLICATION_ID, 2):
        raise GuestLabRefused("NOT_A_DISPOSABLE_V2_DB")
    if PROJECT_STATE_DB_VERSION != 2:
        raise GuestLabRefused("PROJECT_VERSION_NOT_V2")
    with sqlite3.connect(state / "state.sqlite") as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute(
            "CREATE TABLE m0p_disposable_probe ("
            "id INTEGER PRIMARY KEY, actor TEXT NOT NULL)"
        )
    (state / "m0p.json").write_bytes(b"original")
    (state / "m0p-preopened.bin").write_bytes(b"")


def _count(root: Path) -> int:
    with sqlite3.connect(root / ".projectctl" / "state.sqlite") as db:
        return db.execute(
            "SELECT COUNT(*) FROM m0p_disposable_probe"
        ).fetchone()[0]


def _denied(result: dict) -> bool:
    return result.get("status") == "denied"


def _open_denied(result: dict) -> bool:
    return _denied(result) and result.get("errno") in (
        errno.EACCES, errno.EPERM,
    )


def _dual_write(root: Path, uid: int, tag: str) -> bool:
    return (
        _execute(root, "db", uid, tag).get("status") == "wrote"
        and _execute(root, "json", uid, tag).get("status") == "wrote"
    )


def _dual_denied(root: Path, uid: int) -> bool:
    return (
        _denied(_execute(root, "db", uid))
        and _denied(_execute(root, "json", uid))
    )


def _trial() -> dict:
    # The only affected tree is script-created, random, rooted in /var/tmp.
    root = Path(tempfile.mkdtemp(prefix="projectctl-m0p-", dir=_PARENT))
    owned_fd = None
    pidfd = None
    try:
        os.chmod(root, 0o711)
        _create_fixture(root)
        _controlled_tree_ownership(root, _LEGACY_UID)
        baseline_sql = _execute(root, "db", _LEGACY_UID, "LEGACY_BASELINE")
        baseline_json = _execute(root, "json", _LEGACY_UID)
        if baseline_sql.get("status") != "wrote" or baseline_json.get("status") != "wrote":
            raise GuestLabRefused("DISPOSABLE_LEGACY_BASELINE_FAILED")
        before_gate_count = _count(root)
        before_gate_json = (root / ".projectctl" / "m0p.json").read_bytes()

        owned_fd = subprocess.Popen(
            _command(root, "fd", "PREOPEN"),
            preexec_fn=lambda: _drop(_LEGACY_UID),
            text=True, cwd="/",
            env={"PATH": "/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE": "1"},
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        if owned_fd.stdout is None or owned_fd.stdin is None:
            raise GuestLabRefused("OWNED_FD_PIPES_MISSING")
        readable, _, _ = select.select([owned_fd.stdout], [], [], 8)
        if not readable:
            raise GuestLabRefused("OWNED_FD_READY_TIMEOUT")
        try:
            ready = json.loads(owned_fd.stdout.readline())
        except ValueError as exc:
            raise GuestLabRefused("OWNED_FD_READY_MALFORMED") from exc
        if ready != {"phase": "ready"}:
            raise GuestLabRefused("OWNED_FD_NOT_READY")
        if not hasattr(os, "pidfd_open"):
            raise GuestLabRefused("GUEST_PIDFD_NOT_SUPPORTED")
        pidfd = os.pidfd_open(owned_fd.pid)

        # Root takes back only the disposable state tree. The FD already
        # held by the synthetic old identity is NOT revoked.
        _controlled_tree_ownership(root, 0)
        old_fresh_denied = (
            _open_denied(_execute(root, "probe", _LEGACY_UID))
            and _dual_denied(root, _LEGACY_UID)
        )
        candidate_fresh_denied = (
            _open_denied(_execute(root, "probe", _CANDIDATE_UID))
            and _dual_denied(root, _CANDIDATE_UID)
        )
        if _count(root) != before_gate_count:
            raise GuestLabRefused("GATE_ALLOWED_UNEXPECTED_DB_MUTATION")
        if (root / ".projectctl" / "m0p.json").read_bytes() != before_gate_json:
            raise GuestLabRefused("GATE_ALLOWED_UNEXPECTED_JSON_MUTATION")

        owned_fd.stdin.write("GO\n")
        owned_fd.stdin.flush()
        out, _stderr = owned_fd.communicate(timeout=10)
        try:
            written = json.loads(out.strip())
        except ValueError:
            written = {}
        wrote_preopen = (
            owned_fd.returncode == 0 and written ==
            {"phase": "wrote", "count": len(b"M0P_OLD_FD")}
            and (root / ".projectctl" / "m0p-preopened.bin").read_bytes()
            == b"M0P_OLD_FD"
        )
        poll = select.poll()
        poll.register(pidfd, select.POLLIN | select.POLLHUP)
        owned_exited = bool(poll.poll(0))
        os.close(pidfd)
        pidfd = None
        owned_fd = None

        # In a real cutover this point is NOT yet eligible for release:
        # the trusted v3 runtime is absent. Here we only study credentials
        # and write surfaces on a disposable DB that deliberately stays v2.
        _controlled_tree_ownership(root, _CANDIDATE_UID)
        old_denied = (
            _open_denied(_execute(root, "probe", _LEGACY_UID))
            and _dual_denied(root, _LEGACY_UID)
        )
        candidate_wrote = _dual_write(root, _CANDIDATE_UID, "CANDIDATE_SYNTHETIC")
        # Synthetic unchanged writer code can also write when given the new
        # candidate credential. UID separation alone cannot attest binary.
        legacy_code_candidate_credential = _dual_write(
            root, _CANDIDATE_UID, "SAME_LEGACY_SYNTHETIC_CODE"
        )
        observations = LabObservations(
            legacy_baseline_sqlite_wrote=baseline_sql.get("status") == "wrote",
            legacy_baseline_json_wrote=baseline_json.get("status") == "wrote",
            gate_denied_fresh_legacy_open=old_fresh_denied,
            gate_denied_fresh_candidate_open=candidate_fresh_denied,
            preopened_legacy_fd_survived_dac_gate=wrote_preopen,
            owned_preopened_fd_holder_exited=owned_exited,
            legacy_denied_after_handoff=old_denied,
            candidate_wrote_after_handoff=candidate_wrote,
            legacy_program_with_candidate_credential_wrote=(
                legacy_code_candidate_credential
            ),
            sqlite_version_stayed_v2=(
                inspect_db(root / ".projectctl" / "state.sqlite") ==
                (APPLICATION_ID, 2)
            ),
        )
        decision = review(observations)
        return {
            "stage": "M6.0-M0p",
            "decision": decision.decision,
            "authorizes_migration": False,
            "guest_virt": _virtualization(),
            "guest_fs": _filesystem(),
            "observations": {
                item.name: getattr(observations, item.name)
                for item in fields(LabObservations)
            },
            "interpretation": (
                "Old UID denied after handoff; giving new UID to the same "
                "synthetic writer still permits writes. No executable, "
                "systemd or all-writer start authority was tested."
            ),
        }
    finally:
        if owned_fd is not None:
            if owned_fd.poll() is None:
                owned_fd.kill()  # only our exact spawned disposable child
            owned_fd.communicate(timeout=5)
        if pidfd is not None:
            os.close(pidfd)
        # No caller-controlled pathname; unique root created by mkdtemp.
        shutil.rmtree(root)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--inspect", action="store_true")
    modes.add_argument("--run", action="store_true")
    parser.add_argument("--acknowledge")
    opts = parser.parse_args(argv)
    if opts.inspect:
        print(json.dumps({
            "stage": "M6.0-M0p",
            "decision": "OWNER_REVIEW_REQUIRED",
            "authorizes_migration": False,
            "guest_virt": _virtualization(),
            "guest_fs": _filesystem(),
            "role": "D13-KVM-EXT4-DUAL-UID-CUTOVER-ROOT-GATE-v2 subset",
            "note": "Read-only environment hint, not attestation or permission",
        }, sort_keys=True))
        return 0
    try:
        _preflight(opts.acknowledge)
        result = _trial()
    except Exception as exc:
        # Never turn a failed/unknown safety check into positive authority.
        result = {
            "stage": "M6.0-M0p",
            "decision": "NO_GO_LAB_REFUSED",
            "reason": str(exc) if isinstance(exc, GuestLabRefused)
                      else type(exc).__name__,
            "authorizes_migration": False,
        }
    print(json.dumps(result, sort_keys=True))
    return 0 if result["decision"] == (
        "NO_GO_UNTRUSTED_CANDIDATE_EXECUTION_IDENTITY"
    ) else 1


if __name__ == "__main__":
    raise SystemExit(main())
