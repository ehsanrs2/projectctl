"""M0l: positive proof of remaining *bypasses*, never production admission.

All filesystem changes and child writers affect newly initialized disposable
v2 fixtures below pytest tmp_path. No host PIDs are inspected/signaled;
no service/supervisor state, cgroups, AppArmor or mounts are changed.
"""
from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from dataclasses import fields, replace
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
from scripts.m0l_all_writer_embargo_contract import (
    BypassObservations, WriterScopeClaims, review,
)

_RUN = "run-m0l"
_NOW = datetime(2026, 10, 17, tzinfo=timezone.utc)

# Standalone unmodified v2 RunStore entrypoint; no proposed M0l gate import.
_INDEPENDENT_WRITER = r"""
from datetime import datetime, timezone
from pathlib import Path
import os
import sys
from projectctl.storage.runs import RunStore
root = Path(sys.argv[1])
store = RunStore(root)
store.append_event(
    "run-m0l", "m0l.independent", {"disposable": True},
    now=datetime(2026, 10, 17, tzinfo=timezone.utc)
)
stage = root / ".projectctl" / "m0l-late-evidence.stage"
stage.write_text('{"late":true}', encoding="utf-8")
os.replace(stage, root / ".projectctl" / "m0l-late-evidence.json")
"""


def _fixture(tmp_path: Path) -> tuple[Path, RunStore]:
    root = tmp_path / "m0l-owned-disposable"
    initialize_project_state_db(root / ".projectctl" / "state.sqlite")
    store = RunStore(root)
    store.create(
        RunManifest(
            run_id=_RUN,
            task_id="task-m0l",
            execution_plan_digest="m0l-disposable-only",
            status=RunStatus.PLANNED,
            base_commit="abcdef1",
            branch_name="projectctl/run/run-m0l",
            worktree_id="run-m0l",
            worker=WorkerDescriptor(
                provider="codex",
                model_profile=ModelProfile.BALANCED,
                reasoning=ReasoningLevel.MEDIUM,
            ),
        ),
        worktree_path=tmp_path / "not-a-worktree",
        now=_NOW,
    )
    assert inspect_db(store.db_path) == (APPLICATION_ID, 2)
    return root, store


def _all_claimed() -> WriterScopeClaims:
    return WriterScopeClaims(**{
        field.name: True for field in fields(WriterScopeClaims)
    })


def _all_reported_negative() -> BypassObservations:
    return BypassObservations(**{
        field.name: False for field in fields(BypassObservations)
    })


def test_all_claimed_external_gates_still_only_lab_review():
    # Even an ideal string of unauthenticated claims never produces GO.
    outcome = review(_all_claimed(), _all_reported_negative())
    assert outcome.decision == "LAB_REVIEW_ONLY"
    assert outcome.authorizes_migration is False
    assert PROJECT_STATE_DB_VERSION == 2


@pytest.mark.parametrize("field_name", [
    field.name for field in fields(WriterScopeClaims)
])
def test_every_unproven_scope_gate_fails_closed(field_name):
    claims = replace(_all_claimed(), **{field_name: False})
    assert review(claims, _all_reported_negative()).decision == (
        "NO_GO_" + field_name.upper()
    )
    # Nonboolean "yes" and integer 1 can never spoof literal True.
    claims = replace(_all_claimed(), **{field_name: "yes"})
    assert review(claims, _all_reported_negative()).decision == (
        "NO_GO_" + field_name.upper()
    )
    claims = replace(_all_claimed(), **{field_name: 1})
    assert review(claims, _all_reported_negative()).decision == (
        "NO_GO_" + field_name.upper()
    )


@pytest.mark.parametrize("field_name", [
    field.name for field in fields(BypassObservations)
])
def test_any_observed_bypass_is_explicit_no_go(field_name):
    observations = replace(
        _all_reported_negative(), **{field_name: True},
    )
    outcome = review(_all_claimed(), observations)
    assert outcome.decision == "NO_GO_OBSERVED_" + field_name.upper()
    assert outcome.authorizes_migration is False


@pytest.mark.parametrize("field_name", [
    field.name for field in fields(BypassObservations)
])
def test_unverified_or_malformed_bypass_observations_fail_closed(field_name):
    for unverified in (None, "false", 0):
        observations = replace(
            _all_reported_negative(), **{field_name: unverified},
        )
        assert review(_all_claimed(), observations).decision == (
            "NO_GO_UNVERIFIED_" + field_name.upper()
        )


def test_default_unobserved_authority_is_no_go():
    assert review(WriterScopeClaims(), BypassObservations()).decision == (
        "NO_GO_UNVERIFIED_LATE_WRITER_WROTE"
    )
    assert review({}, BypassObservations()).authorizes_migration is False
    assert review(WriterScopeClaims(), {}).authorizes_migration is False


def test_new_uncooperative_v2_process_starts_after_static_census_and_writes(
    tmp_path,
):
    root, store = _fixture(tmp_path)
    events_before = len(store.events(_RUN))
    # "No fixture writer at snapshot" is a bounded observation; the file
    # marker below has NO power over an independent legacy interpreter.
    marker = root / ".projectctl" / "m0l-sampled-stop.json"
    marker.write_text('{"sampled_writers":0}', encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "-B", "-c", _INDEPENDENT_WRITER, str(root)],
        check=False, capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 0, result.stderr[-1000:]
    assert len(store.events(_RUN)) == events_before + 1
    assert store.events(_RUN)[-1].event_type == "m0l.independent"
    assert (root / ".projectctl" / "m0l-late-evidence.json").read_text(
        encoding="utf-8"
    ) == '{"late":true}'
    assert review(
        _all_claimed(),
        replace(
            _all_reported_negative(),
            late_writer_wrote=True,
            json_outside_db_lock_wrote=True,
        ),
    ).decision == "NO_GO_OBSERVED_LATE_WRITER_WROTE"
    assert inspect_db(store.db_path) == (APPLICATION_ID, 2)


@pytest.mark.skipif(
    sys.platform != "linux", reason="Linux file descriptor lifecycle pilot",
)
def test_preopened_writable_fd_survives_post_open_chmod(tmp_path):
    root, store = _fixture(tmp_path)
    leaf = root / ".projectctl" / "m0l-preopened-evidence.json"
    leaf.write_bytes(b"")
    os.chmod(leaf, 0o600)
    fd = os.open(leaf, os.O_WRONLY | os.O_NOFOLLOW)
    try:
        # This simulates a TOO-LATE mode-only embargo on a fixture file.
        # Mode bits do not revoke a file description already opened O_WRONLY.
        os.chmod(leaf, 0o400)
        assert not (leaf.stat().st_mode & 0o222)
        assert os.write(fd, b'{"fd":"still-writable"}') == 23
        os.fsync(fd)
    finally:
        os.close(fd)
        os.chmod(leaf, 0o600)
    assert leaf.read_bytes() == b'{"fd":"still-writable"}'
    assert review(
        _all_claimed(),
        replace(_all_reported_negative(), preopened_fd_wrote=True),
    ).decision == "NO_GO_OBSERVED_PREOPENED_FD_WROTE"
    assert inspect_db(store.db_path) == (APPLICATION_ID, 2)


@pytest.mark.skipif(
    sys.platform != "linux", reason="Linux inode hardlink/symlink pilot",
)
def test_unenumerated_hardlink_and_symlink_names_reach_same_json_inode(tmp_path):
    root, store = _fixture(tmp_path)
    leaf = root / ".projectctl" / "m0l-evidence.json"
    hard = root / "other-json-hardlink"
    sym = root / "other-json-symlink"
    leaf.write_text('{"original":true}', encoding="utf-8")
    os.link(leaf, hard)
    sym.symlink_to(leaf)
    assert leaf.stat().st_ino == hard.stat().st_ino
    hard.write_text('{"hardlink":"wrote"}', encoding="utf-8")
    assert leaf.read_text(encoding="utf-8") == '{"hardlink":"wrote"}'
    sym.write_text('{"symlink":"wrote"}', encoding="utf-8")
    assert leaf.read_text(encoding="utf-8") == '{"symlink":"wrote"}'
    assert review(
        _all_claimed(),
        replace(_all_reported_negative(), inode_alias_wrote=True),
    ).decision == "NO_GO_OBSERVED_INODE_ALIAS_WROTE"
    assert inspect_db(store.db_path) == (APPLICATION_ID, 2)


def test_sqlite_wal_shm_and_json_are_distinct_disposable_authorities(tmp_path):
    root, store = _fixture(tmp_path)
    db = store.db_path
    wal = Path(str(db) + "-wal")
    shm = Path(str(db) + "-shm")
    json_leaf = db.parent / "m0l-evidence-independent.json"
    before = len(store.events(_RUN))
    with sqlite3.connect(db, isolation_level=None) as conn:
        assert conn.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "INSERT INTO run_events(run_id, created_at, event_type, payload_json) "
            "VALUES (?, ?, ?, ?)",
            (_RUN, _NOW.isoformat(), "m0l.wal.fixture", "{}"),
        )
        # The WAL and SHM are open/visible while a write transaction runs.
        assert db.is_file() and wal.is_file() and shm.is_file()
        json_leaf.write_text('{"outside_sqlite":true}', encoding="utf-8")
        conn.commit()
    assert json_leaf.read_text(encoding="utf-8") == (
        '{"outside_sqlite":true}'
    )
    assert len(store.events(_RUN)) == before + 1
    assert inspect_db(db) == (APPLICATION_ID, 2)
    assert review(
        _all_claimed(),
        replace(_all_reported_negative(), json_outside_db_lock_wrote=True),
    ).decision == "NO_GO_OBSERVED_JSON_OUTSIDE_DB_LOCK_WROTE"
