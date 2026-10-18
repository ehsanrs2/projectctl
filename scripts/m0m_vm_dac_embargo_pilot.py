"""M6.0 M0m: explicitly invoked, disposable KVM-guest Linux DAC lab.

Only creates and re-owns a *fresh* private ProjectCTL v2 fixture inside
guest-local /var/tmp. Never accepts a user-supplied source path, touches an
installed service, kills non-child PIDs, invokes migration or grants GO.

In --run mode root is required ONLY inside an owner-reviewed KVM/QEMU guest.
The actor UID is the nonroot sudo invoker; this is NOT a global start embargo.
"""
from __future__ import annotations

import argparse
import errno
import json
import os
import pwd
import select
import shutil
import stat
import subprocess
import sys
import tempfile
from dataclasses import dataclass, fields
from datetime import datetime, timezone
from pathlib import Path

from projectctl.core.enums import ModelProfile, ReasoningLevel, RunStatus
from projectctl.schemas.run import RunManifest, WorkerDescriptor
from projectctl.storage.runs import RunStore
from projectctl.storage.sqlite import (
    APPLICATION_ID, PROJECT_STATE_DB_VERSION, initialize_project_state_db,
    inspect_db,
)

_ACK = "DISPOSABLE_KVM_GUEST_ROOT_DAC_LAB"
_ROOT_PARENT = Path("/var/tmp")
_RUN = "run-m0m"
_NOW = datetime(2026, 10, 18, tzinfo=timezone.utc)
_REPO = str(Path(__file__).resolve().parents[1])
_ACTOR = r"""
import errno
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

root, operation = Path(sys.argv[1]), sys.argv[2]
base = root / ".projectctl"
try:
    if operation == "db":
        from projectctl.storage.runs import RunStore
        RunStore(root).append_event(
            "run-m0m", "m0m.fixture",
            {"disposable": True},
            now=datetime(2026, 10, 18, tzinfo=timezone.utc),
        )
    elif operation == "json":
        stage = base / "m0m-dummy.stage"
        stage.write_text('{"dummy":true}', encoding="utf-8")
        os.replace(stage, base / "m0m-dummy.json")
    elif operation == "probe":
        fd = os.open(
            base / "preopened-dummy.json", os.O_WRONLY | os.O_NOFOLLOW,
        )
        os.close(fd)
    elif operation == "fd":
        fd = os.open(
            base / "preopened-dummy.json",
            os.O_WRONLY | os.O_APPEND | os.O_NOFOLLOW,
        )
        print(json.dumps({"phase": "ready"}), flush=True)
        if sys.stdin.readline().strip() != "GO":
            raise RuntimeError("invalid_owned_child_handshake")
        try:
            count = os.write(fd, b"FD_STILL_WRITES")
            os.fsync(fd)
        finally:
            os.close(fd)
        print(json.dumps({"phase": "wrote", "count": count}), flush=True)
        sys.exit(0)
    else:
        raise RuntimeError("invalid_owned_fixture_operation")
except (OSError, sqlite3.Error) as exc:
    print(json.dumps({
        "status": "denied_or_error",
        "type": type(exc).__name__,
        "errno": getattr(exc, "errno", None),
        "sqlite_code": getattr(exc, "sqlite_errorcode", None),
    }), flush=True)
else:
    print(json.dumps({"status": "wrote"}), flush=True)
"""


class LabRefused(RuntimeError):
    """An unsafe or unverified VM-only lab prerequisite."""


@dataclass(frozen=True)
class Observations:
    baseline_db_wrote: bool | None = None
    baseline_json_wrote: bool | None = None
    direct_new_open_denied_by_dac: bool | None = None
    fresh_legacy_db_writer_denied: bool | None = None
    fresh_json_publisher_denied: bool | None = None
    db_event_count_unchanged_after_gate: bool | None = None
    json_unchanged_after_gate: bool | None = None
    preopened_fd_wrote_after_gate: bool | None = None


def decide(observations: Observations) -> str:
    """NO-GO *even when* a bounded DAC denial and FD bypass are observed."""
    if type(observations) is not Observations:
        return "NO_GO_UNVERIFIED_LAB_OBSERVATIONS"
    for field in fields(observations):
        value = getattr(observations, field.name)
        if value is not True:
            return "NO_GO_UNVERIFIED_" + field.name.upper()
    return "NO_GO_PREOPENED_FD_REMAINS_WRITABLE"


def _virt() -> str:
    try:
        proc = subprocess.run(
            ["systemd-detect-virt", "--vm"], capture_output=True,
            text=True, timeout=5, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"
    return proc.stdout.strip() if proc.returncode == 0 else "unknown"


def _filesystem() -> str:
    try:
        proc = subprocess.run(
            ["findmnt", "-T", str(_ROOT_PARENT), "-no", "FSTYPE"],
            capture_output=True, text=True, timeout=5, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"
    return proc.stdout.strip() if proc.returncode == 0 else "unknown"


def _preflight(acknowledge: str | None) -> tuple[int, int]:
    if sys.platform != "linux" or _virt() not in {"kvm", "qemu"}:
        raise LabRefused("NOT_A_REVIEWED_KVM_QEMU_LINUX_GUEST")
    if _filesystem() != "ext4":
        raise LabRefused("VAR_TMP_NOT_GUEST_LOCAL_EXT4")
    if acknowledge != _ACK:
        raise LabRefused("EXPLICIT_DISPOSABLE_VM_ACK_REQUIRED")
    if os.geteuid() != 0 or os.getuid() != 0:
        raise LabRefused("ROOT_ONLY_INSIDE_DISPOSABLE_VM")
    suid, sgid = os.environ.get("SUDO_UID"), os.environ.get("SUDO_GID")
    if suid is None or sgid is None or not suid.isdecimal() or not sgid.isdecimal():
        raise LabRefused("SUDO_NONROOT_ACTOR_REQUIRED")
    uid, gid = int(suid), int(sgid)
    if not 0 < uid < 2**31 or not 0 < gid < 2**31:
        raise LabRefused("INVALID_NONROOT_ACTOR")
    try:
        user = pwd.getpwuid(uid)
    except KeyError as exc:
        raise LabRefused("SUDO_ACTOR_IDENTITY_MISSING") from exc
    if user.pw_gid != gid or user.pw_name != os.environ.get("SUDO_USER"):
        raise LabRefused("SUDO_ACTOR_IDENTITY_MISMATCH")
    parent_stat = os.lstat(_ROOT_PARENT)
    if not stat.S_ISDIR(parent_stat.st_mode) or parent_stat.st_uid != 0:
        raise LabRefused("UNTRUSTED_VAR_TMP_PARENT")
    if parent_stat.st_mode & stat.S_IWOTH and not parent_stat.st_mode & stat.S_ISVTX:
        raise LabRefused("VAR_TMP_WORLD_WRITABLE_WITHOUT_STICKY_BIT")
    return uid, gid


def _scoped_tree_ownership(project_state: Path, uid: int, gid: int) -> None:
    """Mutate only fixed freshly-created fixture tree; refuse links or mount crossings."""
    ancestor = project_state.parent
    if not ancestor.name.startswith("projectctl-m0m-"):
        raise LabRefused("NOT_PRIVATE_M0M_FIXTURE")
    anchor = os.lstat(ancestor)
    if not stat.S_ISDIR(anchor.st_mode) or anchor.st_uid != 0:
        raise LabRefused("UNTRUSTED_LAB_FIXTURE_ROOT")
    if os.path.ismount(project_state):
        raise LabRefused("MOUNT_IN_FIXTURE")
    root_stat = os.lstat(project_state)
    if not stat.S_ISDIR(root_stat.st_mode) or root_stat.st_dev != anchor.st_dev:
        raise LabRefused("FIXTURE_DEVICE_DRIFT")
    items = sorted(project_state.rglob("*"), key=lambda p: len(p.parts), reverse=True)
    for item in [*items, project_state]:
        st = os.lstat(item)
        if st.st_dev != anchor.st_dev or not (
            stat.S_ISREG(st.st_mode) or stat.S_ISDIR(st.st_mode)
        ):
            raise LabRefused("UNSAFE_LAB_ENTRY_OR_MOUNT")
        if stat.S_ISREG(st.st_mode) and st.st_nlink != 1:
            raise LabRefused("LAB_FILE_HAS_EXTERNAL_HARDLINK")
    for item in [*items, project_state]:
        is_dir = stat.S_ISDIR(os.lstat(item).st_mode)
        os.chown(item, uid, gid, follow_symlinks=False)
        os.chmod(item, 0o700 if is_dir else 0o600, follow_symlinks=False)


def _drop(uid: int, gid: int) -> None:
    os.setgroups([])
    os.setgid(gid)
    os.setuid(uid)


def _env(uid: int) -> dict[str, str]:
    return {
        "HOME": pwd.getpwuid(uid).pw_dir,
        "PATH": "/usr/bin:/bin",
        "PYTHONPATH": _REPO,
        "PYTHONDONTWRITEBYTECODE": "1",
    }


def _command(root: Path, operation: str) -> list[str]:
    return [sys.executable, "-B", "-c", _ACTOR, str(root), operation]


def _execute(root: Path, operation: str, uid: int, gid: int) -> dict:
    proc = subprocess.run(
        _command(root, operation), preexec_fn=lambda: _drop(uid, gid),
        env=_env(uid), cwd="/", capture_output=True, text=True, timeout=15,
        check=False,
    )
    if proc.returncode != 0:
        raise LabRefused("OWNED_LAB_ACTOR_EXITED_NONZERO")
    try:
        return json.loads(proc.stdout.strip())
    except (json.JSONDecodeError, TypeError) as exc:
        raise LabRefused("MALFORMED_LAB_ACTOR_RESULT") from exc


def _fixture(root: Path) -> RunStore:
    db = root / ".projectctl" / "state.sqlite"
    initialize_project_state_db(db)
    store = RunStore(root)
    store.create(
        RunManifest(
            run_id=_RUN,
            task_id="task-m0m",
            execution_plan_digest="m0m-disposable-guest-only",
            status=RunStatus.PLANNED,
            base_commit="abcdef1",
            branch_name="projectctl/run/run-m0m",
            worktree_id="run-m0m",
            worker=WorkerDescriptor(
                provider="codex",
                model_profile=ModelProfile.BALANCED,
                reasoning=ReasoningLevel.MEDIUM,
            ),
        ),
        worktree_path=root / "not-a-real-worktree",
        now=_NOW,
    )
    (root / ".projectctl" / "preopened-dummy.json").write_bytes(b"")
    if inspect_db(db) != (APPLICATION_ID, 2):
        raise LabRefused("INVALID_DISPOSABLE_V2_FIXTURE")
    return store


def _trial(uid: int, gid: int) -> dict:
    # The caller cannot pass its own project/data path. /var/tmp is ext4
    # and the guest-private root remains root-owned (0711) throughout.
    directory = Path(tempfile.mkdtemp(prefix="projectctl-m0m-", dir=_ROOT_PARENT))
    pending = None
    try:
        os.chmod(directory, 0o711)
        state = directory / ".projectctl"
        store = _fixture(directory)
        _scoped_tree_ownership(state, uid, gid)

        before_db = _execute(directory, "db", uid, gid)
        before_json = _execute(directory, "json", uid, gid)
        if before_db.get("status") != "wrote" or before_json.get("status") != "wrote":
            raise LabRefused("DISPOSABLE_BASELINE_WRITE_FAILED")

        events_before = len(store.events(_RUN))
        json_leaf = state / "m0m-dummy.json"
        bytes_before = json_leaf.read_bytes()

        # This single pre-opened test-owned FD demonstrates that DAC is
        # a *new-open* barrier only, not proof of revocation or quiescence.
        pending = subprocess.Popen(
            _command(directory, "fd"),
            preexec_fn=lambda: _drop(uid, gid), env=_env(uid),
            cwd="/", text=True, stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        if pending.stdout is None or pending.stdin is None:
            raise LabRefused("OWNED_FD_ACTOR_PIPE_MISSING")
        readable, _, _ = select.select([pending.stdout], [], [], 8)
        if not readable:
            raise LabRefused("PREOPENED_ACTOR_NOT_READY")
        try:
            ready = json.loads(pending.stdout.readline())
        except json.JSONDecodeError as exc:
            raise LabRefused("MALFORMED_FD_READY") from exc
        if ready != {"phase": "ready"}:
            raise LabRefused("INVALID_FD_READY")

        # Apply root-owned, 0700/0600 DAC to *only* this temporary state.
        _scoped_tree_ownership(state, 0, 0)
        if os.stat(state).st_uid != 0 or stat.S_IMODE(state.stat().st_mode) != 0o700:
            raise LabRefused("DAC_BARRIER_NOT_APPLIED")

        direct_probe = _execute(directory, "probe", uid, gid)
        new_db = _execute(directory, "db", uid, gid)
        new_json = _execute(directory, "json", uid, gid)
        events_after = len(store.events(_RUN))
        json_after = json_leaf.read_bytes()

        pending.stdin.write("GO\n")
        pending.stdin.flush()
        output, _ = pending.communicate(timeout=10)
        lines = [line for line in output.splitlines() if line.strip()]
        try:
            fd_result = json.loads(lines[-1]) if len(lines) == 1 else {}
        except json.JSONDecodeError:
            fd_result = {}
        fd_wrote = (
            pending.returncode == 0 and fd_result == {
                "phase": "wrote", "count": len(b"FD_STILL_WRITES")
            } and (state / "preopened-dummy.json").read_bytes()
            == b"FD_STILL_WRITES"
        )
        pending = None

        observed = Observations(
            baseline_db_wrote=before_db.get("status") == "wrote",
            baseline_json_wrote=before_json.get("status") == "wrote",
            direct_new_open_denied_by_dac=(
                direct_probe.get("status") == "denied_or_error"
                and direct_probe.get("errno") in (errno.EACCES, errno.EPERM)
            ),
            fresh_legacy_db_writer_denied=(
                new_db.get("status") == "denied_or_error"
                and new_db.get("type") in ("OperationalError", "PermissionError")
            ),
            fresh_json_publisher_denied=(
                new_json.get("status") == "denied_or_error"
                and new_json.get("errno") in (errno.EACCES, errno.EPERM)
            ),
            db_event_count_unchanged_after_gate=events_after == events_before,
            json_unchanged_after_gate=json_after == bytes_before,
            preopened_fd_wrote_after_gate=fd_wrote,
        )
        return {
            "stage": "M6.0-M0m",
            "decision": decide(observed),
            "authorizes_migration": False,
            "observations": {
                f.name: getattr(observed, f.name) for f in fields(Observations)
            },
            "guest_virt": _virt(),
            "guest_fs": _filesystem(),
            "note": "Fixture-only DAC denies new opens; pre-opened FD survives",
        }
    finally:
        if pending is not None:
            if pending.poll() is None:
                pending.kill()  # ONLY the fixture child started above
            pending.communicate(timeout=5)
        shutil.rmtree(directory)  # fresh random script-owned /var/tmp fixture


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument("--inspect", action="store_true")
    actions.add_argument("--run", action="store_true")
    parser.add_argument("--acknowledge", default=None)
    opts = parser.parse_args(argv)
    if opts.inspect:
        print(json.dumps({
            "stage": "M6.0-M0m",
            "decision": "OWNER_MUST_REVIEW_DISPOSABLE_GUEST",
            "authorizes_migration": False,
            "guest_virt": _virt(),
            "var_tmp_fstype": _filesystem(),
            "effective_uid": os.geteuid(),
            "requires": "KVM/QEMU guest ext4 /var/tmp, sudo nonroot actor, explicit ack",
        }, sort_keys=True))
        return 0
    try:
        uid, gid = _preflight(opts.acknowledge)
        result = _trial(uid, gid)
    except (LabRefused, OSError, subprocess.TimeoutExpired) as exc:
        result = {
            "stage": "M6.0-M0m",
            "decision": "NO_GO_LAB_REFUSED",
            "reason": type(exc).__name__ if not isinstance(exc, LabRefused) else str(exc),
            "authorizes_migration": False,
        }
    print(json.dumps(result, sort_keys=True))
    return 0 if result["decision"] == "NO_GO_PREOPENED_FD_REMAINS_WRITABLE" else 1


if __name__ == "__main__":
    raise SystemExit(main())
