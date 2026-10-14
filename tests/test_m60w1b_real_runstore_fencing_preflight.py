"""M6.0 W1b — characterize deployed v2 RunStore's fencing gaps.

These are LEGACY-CHARACTERIZATION tests, *not* desired security behavior.
They use only a freshly initialized, disposable v2 ProjectCTL database.
When real generation/token fencing is approved, replace these assertions
with tests proving the old operations are rejected. No production source
or SQLite schema is modified by this change.
"""
from __future__ import annotations

import inspect
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from projectctl.core.enums import (
    ModelProfile,
    ReasoningLevel,
    RunStatus,
)
from projectctl.core.errors import RunStoreError
from projectctl.schemas.run import RunManifest, WorkerDescriptor
from projectctl.storage.runs import RunStore
from projectctl.storage.sqlite import (
    APPLICATION_ID,
    PROJECT_STATE_DB_VERSION,
    initialize_project_state_db,
    inspect_db,
)

NOW = datetime(2026, 10, 14, 11, tzinfo=timezone.utc)


def _run_store(tmp_path: Path) -> RunStore:
    root = tmp_path / "disposable"
    db = root / ".projectctl" / "state.sqlite"
    initialize_project_state_db(db)
    assert inspect_db(db) == (APPLICATION_ID, 2)
    worker = WorkerDescriptor(
        provider="codex",
        model_profile=ModelProfile.BALANCED,
        reasoning=ReasoningLevel.MEDIUM,
    )
    manifest = RunManifest(
        run_id="run-w1b",
        task_id="task-w1b",
        execution_plan_digest="v2-contract-fixture",
        status=RunStatus.PLANNED,
        base_commit="abcdef1",
        branch_name="projectctl/run/run-w1b",
        worktree_id="run-w1b",
        worker=worker,
    )
    store = RunStore(root)
    store.create(manifest, worktree_path=tmp_path / "no-real-worktree", now=NOW)
    return store


def _lease_columns(store: RunStore) -> set[str]:
    conn = sqlite3.connect(store.db_path)
    try:
        return {row[1] for row in conn.execute("PRAGMA table_info(runs)")}
    finally:
        conn.close()


def test_deployed_v2_has_no_lease_generation_or_token_contract(tmp_path):
    """Existing v2 DB may not be silently treated as fenced."""
    store = _run_store(tmp_path)
    assert PROJECT_STATE_DB_VERSION == 2
    assert inspect_db(store.db_path) == (APPLICATION_ID, 2)
    assert {"lease_owner", "lease_expires_at", "heartbeat_at"} <= _lease_columns(store)
    assert "lease_generation" not in _lease_columns(store)
    assert "lease_token" not in _lease_columns(store)
    with sqlite3.connect(store.db_path) as conn:
        tables = {
            row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
    assert "trace_seals" not in tables


def test_legacy_v2_same_owner_reacquisition_carries_no_epoch(tmp_path):
    """Document v2 name-based reacquire, NOT proof of a fresh credential."""
    store = _run_store(tmp_path)
    first = store.acquire_lease(
        "run-w1b", owner="same-host-pid", ttl_seconds=60, now=NOW,
    )
    second = store.acquire_lease(
        "run-w1b", owner="same-host-pid",
        ttl_seconds=60, now=NOW + timedelta(seconds=10),
    )
    assert second.lease_owner == first.lease_owner
    assert second.lease_expires_at > first.lease_expires_at
    assert not hasattr(second, "lease_generation")
    assert not hasattr(second, "lease_token")


def test_legacy_v2_expired_owner_heartbeat_can_revive_old_name(tmp_path):
    """Known v2 gap: heartbeat currently does not check stored expiry."""
    store = _run_store(tmp_path)
    store.acquire_lease(
        "run-w1b", owner="first", ttl_seconds=60, now=NOW,
    )
    revived = store.heartbeat(
        "run-w1b", owner="first", ttl_seconds=60,
        now=NOW + timedelta(seconds=61),
    )
    assert revived.lease_owner == "first"
    assert revived.lease_expires_at == NOW + timedelta(seconds=121)


def test_legacy_v2_transition_is_not_fenced_by_current_lease(tmp_path):
    """Known v2 gap: transition has no fenced credential argument."""
    store = _run_store(tmp_path)
    store.acquire_lease("run-w1b", owner="first", ttl_seconds=60, now=NOW)
    next_owner = store.acquire_lease(
        "run-w1b", owner="second", ttl_seconds=60,
        now=NOW + timedelta(seconds=61),
    )
    assert next_owner.lease_owner == "second"
    # Deliberately call the legacy method without any credential; it
    # currently checks status only, not which verifier/owner calls it.
    changed = store.transition(
        "run-w1b", expected={RunStatus.PLANNED},
        status=RunStatus.PREPARING, now=NOW + timedelta(seconds=62),
    )
    assert changed.status == RunStatus.PREPARING
    assert changed.lease_owner == "second"
    assert "lease_token" not in inspect.signature(store.transition).parameters


def test_legacy_v2_append_event_is_not_atomic_with_failed_transition(tmp_path):
    """Separate committed event survives rejected transition."""
    store = _run_store(tmp_path)
    store.append_event(
        "run-w1b", "verification.passed",
        {"fixture_only": True}, now=NOW,
    )
    try:
        store.transition(
            "run-w1b", expected={RunStatus.VERIFYING},
            status=RunStatus.PREPARING, now=NOW,
        )
    except RunStoreError:
        pass
    else:
        raise AssertionError("fixture expected refused status transition")
    assert store.get("run-w1b").status == RunStatus.PLANNED
    assert [e.event_type for e in store.events("run-w1b")] == [
        "run.created",
        "verification.passed",
    ]


def test_legacy_v2_heartbeat_and_release_take_owner_not_token(tmp_path):
    store = _run_store(tmp_path)
    for method in (store.acquire_lease, store.heartbeat, store.release_lease):
        parameters = inspect.signature(method).parameters
        assert "owner" in parameters
        assert "lease_token" not in parameters
        assert "lease_generation" not in parameters
    assert PROJECT_STATE_DB_VERSION == 2
