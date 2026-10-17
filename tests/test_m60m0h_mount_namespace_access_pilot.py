"""M6.0 M0h — child-only Linux mount-namespace read-only view pilot.

A read-only bind mount affects a mount *view*, NOT an inode globally.
Tests use only disposable v2 fixtures and an unprivileged user+mount
namespace created in an owned child. Kernel refusal is SKIP/NO-GO, not
a passed enforcement proof. No systemd/cgroup/host mount changes occur.
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path

import pytest

from projectctl.core.enums import ModelProfile, ReasoningLevel, RunStatus
from projectctl.schemas.run import RunManifest, WorkerDescriptor
from projectctl.storage.runs import RunStore
from projectctl.storage.sqlite import (
    APPLICATION_ID, PROJECT_STATE_DB_VERSION, initialize_project_state_db,
    inspect_db,
)

_RUN = "run-m0h"
_NOW = datetime(2026, 10, 17, tzinfo=timezone.utc)

# This script is run ONLY inside a newly-created unprivileged user+mount
# namespace in a separate interpreter. Never invoke it without that wrapper.
# All writable paths come from the disposable fixture under pytest tmp_path.
_NAMESPACE_CHILD = r"""
import ctypes
import errno
import json
import os
import sqlite3
import sys
from pathlib import Path
from datetime import datetime, timezone

source, view, operation = map(str, sys.argv[1:4])
libc = ctypes.CDLL(None, use_errno=True)
libc.mount.argtypes = [
    ctypes.c_char_p, ctypes.c_char_p, ctypes.c_char_p,
    ctypes.c_ulong, ctypes.c_void_p,
]
libc.mount.restype = ctypes.c_int
MS_RDONLY, MS_REMOUNT, MS_BIND, MS_REC, MS_PRIVATE = (
    1, 32, 4096, 16384, 1 << 18
)

def do_mount(src, target, flags):
    s = os.fsencode(src) if src is not None else None
    t = os.fsencode(target)
    if libc.mount(s, t, None, flags, None) != 0:
        raise OSError(ctypes.get_errno(), "namespace_mount_failed")

def result(**kwargs):
    print(json.dumps(kwargs, sort_keys=True), flush=True)

# No mount propagation back toward the host namespace.
try:
    do_mount(None, "/", MS_REC | MS_PRIVATE)
    do_mount(source, view, MS_BIND | MS_REC)
except OSError as exc:
    result(status="unsupported_mount_namespace", errno=exc.errno)
    sys.exit(0)

preopened = None
try:
    if operation == "preopened":
        preopened = os.open(
            os.path.join(view, ".projectctl", "preopened.json"),
            os.O_WRONLY | os.O_NOFOLLOW,
        )
    try:
        do_mount(None, view, MS_BIND | MS_REMOUNT | MS_RDONLY)
    except OSError as exc:
        if operation == "preopened" and exc.errno == errno.EBUSY:
            result(status="preopened_remount_refused", errno=exc.errno)
        else:
            result(status="unsupported_readonly_remount", errno=exc.errno)
        sys.exit(0)

    from projectctl.storage.runs import RunStore

    if operation == "preopened":
        try:
            os.write(preopened, b"preopened-still-writable")
        except OSError as exc:
            result(status="preopened_fd_denied", errno=exc.errno)
        else:
            result(status="preopened_fd_wrote")
        sys.exit(0)

    target = view if operation in ("view_db", "view_json") else source
    try:
        if operation in ("view_db", "alias_db"):
            RunStore(Path(target)).append_event(
                "run-m0h", "m0h.fixture", {"disposable": True},
                now=datetime(2026, 10, 17, tzinfo=timezone.utc),
            )
        elif operation in ("view_json", "alias_json"):
            base = Path(target) / ".projectctl"
            stage = base / "m0h-evidence.stage"
            stage.write_text('{"disposable":true}', encoding="utf-8")
            os.replace(stage, base / "m0h-evidence.json")
        else:
            raise AssertionError("unknown_operation")
    except (OSError, sqlite3.Error) as exc:
        error_code = getattr(exc, "sqlite_errorcode", None)
        if getattr(exc, "errno", None) == errno.EROFS or error_code == 8:
            result(status="kernel_denied", errno=getattr(exc, "errno", None),
                   sqlite_code=error_code)
        else:
            result(status="unexpected_error", type=type(exc).__name__,
                   errno=getattr(exc, "errno", None), sqlite_code=error_code)
    else:
        result(status="wrote")
finally:
    if preopened is not None:
        os.close(preopened)
"""


@dataclass(frozen=True)
class IsolationClaims:
    """Hypothetical operator claims, not authenticated attestations."""

    child_mount_view_is_read_only: bool = False
    source_and_all_aliases_inaccessible: bool = False
    preexisting_writable_handles_drained: bool = False
    all_legacy_writers_contained: bool = False
    independently_enforced_start_embargo: bool = False
    supervisor_and_cgroup_lifecycle_proven: bool = False
    host_and_namespace_identity_anchored: bool = False
    wal_json_backup_recovery_proven: bool = False


def _review(claims: IsolationClaims) -> str:
    """Never grant migration, even for an all-True test-only claim."""
    for gate in IsolationClaims.__dataclass_fields__:
        if not getattr(claims, gate):
            return "NO_GO_" + gate.upper()
    return "OPERATOR_REVIEW_ONLY"


def _fixture(tmp_path: Path) -> tuple[Path, Path, RunStore]:
    source = tmp_path / "source"
    view = tmp_path / "readonly-view"
    view.mkdir()
    initialize_project_state_db(source / ".projectctl" / "state.sqlite")
    store = RunStore(source)
    store.create(
        RunManifest(
            run_id=_RUN,
            task_id="task-m0h",
            execution_plan_digest="m0h-fixture-only",
            status=RunStatus.PLANNED,
            base_commit="abcdef1",
            branch_name="projectctl/run/run-m0h",
            worktree_id="run-m0h",
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
    return source, view, store


def _namespace_probe(source: Path, view: Path, operation: str):
    """No fallback if unprivileged mount namespaces are unavailable."""
    if sys.platform != "linux" or shutil.which("unshare") is None:
        pytest.skip("M0h Linux unshare utility unavailable; no kernel proof")
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    proc = subprocess.run(
        [
            "unshare", "--user", "--map-root-user", "--mount", "--fork", "--",
            sys.executable, "-B", "-c", _NAMESPACE_CHILD,
            str(source), str(view), operation,
        ],
        capture_output=True, text=True, timeout=20, env=env, check=False,
    )
    if proc.returncode:
        # Unsupported user namespace/capability/seccomp must not turn into
        # a falsely successful kernel enforcement test.
        if ("Operation not permitted" in proc.stderr
                or "Permission denied" in proc.stderr
                or "unshare failed" in proc.stderr):
            pytest.skip("M0h OS namespace unshare denied; NO-GO for this host")
        pytest.fail(
            "mount_namespace_child_failed: " + str(proc.returncode)
            + " " + proc.stderr[-300:]
        )
    lines = proc.stdout.strip().splitlines()
    assert len(lines) == 1, "unexpected_namespace_output"
    result = json.loads(lines[0])
    if result["status"].startswith("unsupported_"):
        pytest.skip("M0h kernel mount view unavailable: " + result["status"])
    return result


@pytest.mark.parametrize("mode", ["view_db", "view_json"])
def test_kernel_readonly_bind_view_blocks_new_legacy_writes(tmp_path, mode):
    source, view, store = _fixture(tmp_path)
    before = tuple(x.event_type for x in store.events(_RUN))
    outcome = _namespace_probe(source, view, mode)
    assert outcome["status"] == "kernel_denied", outcome
    assert tuple(x.event_type for x in store.events(_RUN)) == before
    assert not (source / ".projectctl" / "m0h-evidence.json").exists()
    assert not (source / ".projectctl" / "m0h-evidence.stage").exists()
    assert inspect_db(store.db_path) == (APPLICATION_ID, 2)


@pytest.mark.parametrize("mode", ["alias_db", "alias_json"])
def test_same_inode_writable_via_unrestricted_source_alias(tmp_path, mode):
    source, view, store = _fixture(tmp_path)
    before = len(store.events(_RUN))
    outcome = _namespace_probe(source, view, mode)
    assert outcome["status"] == "wrote", outcome
    if mode == "alias_db":
        assert len(store.events(_RUN)) == before + 1
        assert store.events(_RUN)[-1].event_type == "m0h.fixture"
    else:
        assert (source / ".projectctl" / "m0h-evidence.json").read_text(
            encoding="utf-8"
        ) == '{"disposable":true}'
    assert _review(IsolationClaims(child_mount_view_is_read_only=True)) == (
        "NO_GO_SOURCE_AND_ALL_ALIASES_INACCESSIBLE"
    )


def test_preopened_writable_fd_is_not_revoked_by_mount_view(tmp_path):
    source, view, store = _fixture(tmp_path)
    (source / ".projectctl" / "preopened.json").write_bytes(b"")
    outcome = _namespace_probe(source, view, "preopened")
    # Depending on kernel/mount behavior, remount can refuse while a
    # writer is open, or preopened writes may remain possible/denied.
    # NONE of these establishes an all-writer external maintenance gate.
    assert outcome["status"] in {
        "preopened_remount_refused", "preopened_fd_wrote",
        "preopened_fd_denied",
    }, outcome
    if outcome["status"] == "preopened_fd_wrote":
        assert (source / ".projectctl" / "preopened.json").read_bytes() == (
            b"preopened-still-writable"
        )
    assert inspect_db(store.db_path) == (APPLICATION_ID, 2)
    assert _review(IsolationClaims(child_mount_view_is_read_only=True)) == (
        "NO_GO_SOURCE_AND_ALL_ALIASES_INACCESSIBLE"
    )


def test_independent_legacy_writer_outside_mount_namespace_can_write(tmp_path):
    source, view, store = _fixture(tmp_path)
    before = len(store.events(_RUN))
    # This independent interpreter never enters any hypothetical
    # maintenance namespace; a per-child readonly view cannot stop it.
    program = (
        "from pathlib import Path;"
        "from datetime import datetime,timezone;"
        "from projectctl.storage.runs import RunStore;"
        "RunStore(Path(__import__('sys').argv[1])).append_event("
        "'run-m0h','m0h.fixture',{'disposable':True},"
        "now=datetime(2026,10,17,tzinfo=timezone.utc))"
    )
    subprocess.run(
        [sys.executable, "-B", "-c", program, str(source)],
        timeout=15, check=True,
    )
    assert len(store.events(_RUN)) == before + 1
    assert _review(IsolationClaims()) == (
        "NO_GO_CHILD_MOUNT_VIEW_IS_READ_ONLY"
    )
    assert inspect_db(store.db_path) == (APPLICATION_ID, 2)


def test_all_external_gates_mandatory_but_never_production_go():
    all_claimed = IsolationClaims(**{
        name: True for name in IsolationClaims.__dataclass_fields__
    })
    assert _review(all_claimed) == "OPERATOR_REVIEW_ONLY"
    for name in IsolationClaims.__dataclass_fields__:
        assert _review(replace(all_claimed, **{name: False})) == (
            "NO_GO_" + name.upper()
        )
    assert PROJECT_STATE_DB_VERSION == 2
