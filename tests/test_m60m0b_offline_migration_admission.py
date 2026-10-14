"""M6.0 M0b — demonstrate why project-v2 maintenance admission is NOT proven.

These characterization tests operate only on newly initialized disposable
ProjectCTL v2 databases under pytest tmp_path. They intentionally show
that unmodified legacy RunStore callers can bypass a proposed maintenance
lock and can publish external files during a SQLite transaction.

A passing test is NEGATIVE evidence: it does not authorize live migration.
"""
from __future__ import annotations

import multiprocessing
import os
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

import pytest

from projectctl.core.enums import ModelProfile, ReasoningLevel, RunStatus
from projectctl.project.locking import execution_authority_gate
from projectctl.schemas.run import RunManifest, WorkerDescriptor
from projectctl.storage.runs import RunStore
from projectctl.storage.sqlite import (
    APPLICATION_ID,
    PROJECT_STATE_DB_VERSION,
    initialize_project_state_db,
    inspect_db,
)

pytestmark = pytest.mark.skipif(
    os.name != "posix",
    reason="M0b spawned POSIX process/lock admission characterization",
)

_RUN = "run-m0b"
_NOW = datetime(2026, 10, 14, 13, tzinfo=timezone.utc)


def _fixture(tmp_path: Path) -> tuple[Path, RunStore]:
    root = tmp_path / "disposable"
    db = root / ".projectctl" / "state.sqlite"
    initialize_project_state_db(db)
    store = RunStore(root)
    manifest = RunManifest(
        run_id=_RUN,
        task_id="task-m0b",
        execution_plan_digest="m0b-fixture-only",
        status=RunStatus.PLANNED,
        base_commit="abcdef1",
        branch_name="projectctl/run/run-m0b",
        worktree_id="run-m0b",
        worker=WorkerDescriptor(
            provider="codex",
            model_profile=ModelProfile.BALANCED,
            reasoning=ReasoningLevel.MEDIUM,
        ),
    )
    store.create(manifest, worktree_path=tmp_path / "not-a-real-worktree", now=_NOW)
    assert inspect_db(db) == (APPLICATION_ID, 2)
    return root, store


def _legacy_process(project_root: str, pipe) -> None:
    try:
        # Construct a v2-capable process BEFORE the purported maintenance gate.
        store = RunStore(Path(project_root))
        pipe.send(("ready", None))
        command = pipe.recv()
        if command == "event":
            store.append_event(_RUN, "m0b.fixture", {"disposable": True}, now=_NOW)
        elif command == "lease":
            store.acquire_lease(
                _RUN, owner="legacy-process", ttl_seconds=300, now=_NOW
            )
        elif command == "file":
            leaf = Path(project_root) / ".projectctl" / "dummy-evidence.json"
            stage = leaf.with_suffix(".tmp")
            stage.write_text('{"disposable":true}', encoding="utf-8")
            os.replace(stage, leaf)
        else:
            raise AssertionError("invalid_test_command")
        pipe.send(("done", command))
    except BaseException as error:
        pipe.send(("error", type(error).__name__))
    finally:
        pipe.close()


def _spawn_legacy(root: Path):
    ctx = multiprocessing.get_context("spawn")
    parent, child = ctx.Pipe()
    proc = ctx.Process(target=_legacy_process, args=(str(root), child))
    proc.start()
    child.close()
    return parent, proc


def _receive(pipe):
    if not pipe.poll(12):
        raise AssertionError("legacy_child_response_timeout")
    return pipe.recv()


def _cleanup(pipe, proc):
    proc.join(timeout=10)
    if proc.is_alive():
        proc.terminate()
        proc.join(timeout=5)
    pipe.close()
    assert not proc.is_alive()


def test_execution_authority_gate_does_not_retrofit_legacy_event_writer(tmp_path):
    root, store = _fixture(tmp_path)
    pipe, proc = _spawn_legacy(root)
    try:
        assert _receive(pipe) == ("ready", None)
        with execution_authority_gate(root):
            pipe.send("event")
            # This is the currently observed unsafe-to-migrate legacy
            # behavior: direct RunStore write bypasses the project gate.
            assert _receive(pipe) == ("done", "event")
        assert [x.event_type for x in store.events(_RUN)][-1] == "m0b.fixture"
        assert inspect_db(store.db_path) == (APPLICATION_ID, 2)
    finally:
        _cleanup(pipe, proc)


def test_null_lease_owner_does_not_prove_absence_of_active_legacy_process(tmp_path):
    root, store = _fixture(tmp_path)
    pipe, proc = _spawn_legacy(root)
    try:
        assert _receive(pipe) == ("ready", None)
        with execution_authority_gate(root):
            with closing(sqlite3.connect(store.db_path)) as conn:
                assert conn.execute(
                    "SELECT lease_owner FROM runs WHERE run_id=?", (_RUN,),
                ).fetchone()[0] is None
            # Child was alive and holding a RunStore reference *before*
            # admission. The NULL lease check cannot exclude its next write.
            pipe.send("lease")
            assert _receive(pipe) == ("done", "lease")
        assert store.get(_RUN).lease_owner == "legacy-process"
        assert PROJECT_STATE_DB_VERSION == 2
    finally:
        _cleanup(pipe, proc)


def test_new_advisory_maintenance_mutex_cannot_fence_uncooperative_v2_client(
    tmp_path,
):
    import fcntl

    root, store = _fixture(tmp_path)
    lock = root / ".projectctl" / "locks" / "m0b-maintenance.lock"
    lock.parent.mkdir(exist_ok=True)
    pipe, proc = _spawn_legacy(root)
    try:
        assert _receive(pipe) == ("ready", None)
        fd = os.open(lock, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            pipe.send("event")
            assert _receive(pipe) == ("done", "event")
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)
        assert [x.event_type for x in store.events(_RUN)][-1] == "m0b.fixture"
    finally:
        _cleanup(pipe, proc)


def test_begin_immediate_cannot_quiesce_independent_json_evidence_writer(tmp_path):
    root, store = _fixture(tmp_path)
    pipe, proc = _spawn_legacy(root)
    db = store.db_path
    leaf = root / ".projectctl" / "dummy-evidence.json"
    try:
        assert _receive(pipe) == ("ready", None)
        with closing(sqlite3.connect(db, isolation_level=None)) as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                pipe.send("file")
                assert _receive(pipe) == ("done", "file")
                assert leaf.read_text(encoding="utf-8") == '{"disposable":true}'
                assert conn.in_transaction
            finally:
                conn.rollback()
        assert inspect_db(db) == (APPLICATION_ID, 2)
    finally:
        _cleanup(pipe, proc)
