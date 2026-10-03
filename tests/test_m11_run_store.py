from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from projectctl.core.enums import (
    ModelProfile,
    ReasoningLevel,
    RunStatus,
    RunTerminalReason,
)
from projectctl.core.errors import RunLeaseError, RunStoreError
from projectctl.schemas.run import RunManifest, WorkerDescriptor
from projectctl.storage.runs import RunStore
from projectctl.storage.sqlite import initialize_project_state_db

NOW = datetime(2026, 10, 3, 6, 0, tzinfo=timezone.utc)
WORKER = WorkerDescriptor(
    provider="codex",
    model_profile=ModelProfile.BALANCED,
    reasoning=ReasoningLevel.MEDIUM,
)


def make_store(tmp_path: Path) -> RunStore:
    root = tmp_path / "repo"
    (root / ".projectctl").mkdir(parents=True)
    initialize_project_state_db(root / ".projectctl" / "state.sqlite")
    return RunStore(root)


def manifest(run_id: str, task_id: str) -> RunManifest:
    return RunManifest(
        run_id=run_id,
        task_id=task_id,
        execution_plan_digest=f"digest-{run_id}",
        status=RunStatus.PLANNED,
        base_commit="abcdef1",
        branch_name=f"projectctl/run/{run_id}",
        worktree_id=run_id,
        worker=WORKER,
    )


def test_run_store_enforces_one_active_run_per_task(tmp_path: Path):
    store = make_store(tmp_path)
    wt1 = tmp_path / "w1"
    wt2 = tmp_path / "w2"
    store.create(manifest("run-1", "task-1"), worktree_path=wt1, now=NOW)

    with pytest.raises(RunStoreError, match="active run"):
        store.create(manifest("run-2", "task-1"), worktree_path=wt2, now=NOW)

    store.transition(
        "run-1",
        expected={RunStatus.PLANNED},
        status=RunStatus.FAILED,
        terminal_reason=RunTerminalReason.INFRASTRUCTURE_ERROR,
        now=NOW,
    )
    second = store.create(manifest("run-2", "task-1"), worktree_path=wt2, now=NOW)
    assert second.status == RunStatus.PLANNED


def test_run_lease_is_exclusive_until_expiry(tmp_path: Path):
    store = make_store(tmp_path)
    store.create(manifest("run-1", "task-1"), worktree_path=tmp_path / "w", now=NOW)

    store.acquire_lease("run-1", owner="a", ttl_seconds=60, now=NOW)
    with pytest.raises(RunLeaseError):
        store.acquire_lease("run-1", owner="b", ttl_seconds=60, now=NOW + timedelta(seconds=10))

    record = store.acquire_lease(
        "run-1",
        owner="b",
        ttl_seconds=60,
        now=NOW + timedelta(seconds=61),
    )
    assert record.lease_owner == "b"


def test_transition_revalidates_run_manifest_contract(tmp_path: Path):
    store = make_store(tmp_path)
    store.create(manifest("run-1", "task-1"), worktree_path=tmp_path / "w", now=NOW)

    with pytest.raises(Exception):
        store.transition(
            "run-1",
            expected={RunStatus.PLANNED},
            status=RunStatus.FAILED,
            terminal_reason=None,
            now=NOW,
        )
    assert store.get("run-1").status == RunStatus.PLANNED


def test_run_events_record_creation_and_transition(tmp_path: Path):
    store = make_store(tmp_path)
    store.create(manifest("run-1", "task-1"), worktree_path=tmp_path / "w", now=NOW)
    store.transition(
        "run-1",
        expected={RunStatus.PLANNED},
        status=RunStatus.PREPARING,
        now=NOW,
    )
    assert [event.event_type for event in store.events("run-1")] == [
        "run.created",
        "run.transition",
    ]
