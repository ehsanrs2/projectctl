import json
import socket
import time
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from projectctl.application import integration as integration_app
from projectctl.application import task_lifecycle
from projectctl.core.enums import RunStatus, RunTerminalReason
from projectctl.core.errors import ProjectLockError, RunLeaseError
from projectctl.integrations.beads.completion import BeadsTaskCompletionWriter
from projectctl.project.locking import project_lock
from projectctl.runtime import LeaseHeartbeat


class FakeHeartbeatStore:
    def __init__(self, *, fail_after: int | None = None):
        self.calls = 0
        self.fail_after = fail_after

    def heartbeat(self, run_id, *, owner, ttl_seconds):
        self.calls += 1
        if self.fail_after is not None and self.calls >= self.fail_after:
            raise RunLeaseError("simulated lease loss")


def test_lease_heartbeat_renews_long_operation():
    store = FakeHeartbeatStore()
    with LeaseHeartbeat(
        store,
        "run-1",
        owner="owner",
        ttl_seconds=0.5,
        interval_seconds=0.05,
    ):
        time.sleep(0.13)
    assert store.calls >= 3


def test_lease_heartbeat_loss_is_fail_closed():
    store = FakeHeartbeatStore(fail_after=2)
    with pytest.raises(RunLeaseError, match="heartbeat failed"):
        with LeaseHeartbeat(
            store,
            "run-1",
            owner="owner",
            ttl_seconds=0.5,
            interval_seconds=0.05,
        ):
            time.sleep(0.12)


def test_project_lock_reclaims_dead_same_host_lock(tmp_path: Path):
    root = tmp_path / "repo"
    lock_dir = root / ".projectctl" / "locks"
    lock_dir.mkdir(parents=True)
    path = lock_dir / "integration.lock"
    path.write_text(
        json.dumps(
            {
                "pid": 99999999,
                "hostname": socket.gethostname(),
                "token": "stale",
                "acquired_at": "2026-10-03T00:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )

    with project_lock(root, "integration"):
        current = json.loads(path.read_text(encoding="utf-8"))
        assert current["token"] != "stale"
        assert current["pid"] > 0

    assert not path.exists()


def test_project_lock_does_not_break_live_owner(tmp_path: Path):
    root = tmp_path / "repo"
    with project_lock(root, "integration"):
        with pytest.raises(ProjectLockError, match="already locked"):
            with project_lock(root, "integration"):
                pass


def test_project_lock_does_not_reclaim_ambiguous_lock(tmp_path: Path):
    root = tmp_path / "repo"
    lock_dir = root / ".projectctl" / "locks"
    lock_dir.mkdir(parents=True)
    path = lock_dir / "integration.lock"
    path.write_text("not-json", encoding="utf-8")

    with pytest.raises(ProjectLockError, match="already locked"):
        with project_lock(root, "integration"):
            pass

    assert path.read_text(encoding="utf-8") == "not-json"


class FakeRunStore:
    def __init__(self, status: RunStatus):
        self.record = SimpleNamespace(
            run_id="run-1",
            task_id="task-1",
            status=status,
            terminal_reason=(
                RunTerminalReason.WORKER_ERROR
                if status == RunStatus.FAILED
                else RunTerminalReason.POLICY_BLOCKED
            ),
        )
        self.events = []

    def get(self, run_id):
        return self.record

    def append_event(self, run_id, event_type, payload):
        self.events.append((event_type, payload))

    def transition(self, run_id, *, expected, status, terminal_reason):
        assert self.record.status in expected
        self.record = SimpleNamespace(
            run_id=run_id,
            task_id="task-1",
            status=status,
            terminal_reason=terminal_reason,
        )
        return self.record


def test_failed_run_releases_canonical_task(monkeypatch, tmp_path: Path):
    store = FakeRunStore(RunStatus.FAILED)
    released = []
    monkeypatch.setattr(
        task_lifecycle,
        "release_task_for_retry",
        lambda root, store, run_id, actor: released.append((run_id, actor)),
    )

    result = task_lifecycle.reconcile_terminal_task(
        tmp_path,
        store=store,
        run_id="run-1",
        actor="actor-1",
    )

    assert result.status == RunStatus.FAILED
    assert released == [("run-1", "actor-1")]
    assert store.events[-1][0] == "task.reconciled"


def test_blocked_run_unassigns_and_blocks_task(monkeypatch, tmp_path: Path):
    store = FakeRunStore(RunStatus.BLOCKED_POLICY)
    blocked = []
    monkeypatch.setattr(
        task_lifecycle,
        "block_task_for_decision",
        lambda root, task_id, reason: blocked.append((task_id, reason)),
    )
    monkeypatch.setattr(
        task_lifecycle,
        "task_delivery_policy",
        lambda root: SimpleNamespace(release_claim_after_decision_block=False),
    )

    result = task_lifecycle.reconcile_terminal_task(
        tmp_path,
        store=store,
        run_id="run-1",
        actor="actor-1",
    )

    assert result.status == RunStatus.BLOCKED_POLICY
    assert blocked == [("task-1", RunTerminalReason.POLICY_BLOCKED.value)]


def test_task_reconciliation_failure_escalates_recovery_unsafe(monkeypatch, tmp_path: Path):
    store = FakeRunStore(RunStatus.FAILED)

    def fail_release(*args, **kwargs):
        raise RuntimeError("task store unavailable")

    monkeypatch.setattr(task_lifecycle, "release_task_for_retry", fail_release)

    result = task_lifecycle.reconcile_terminal_task(
        tmp_path,
        store=store,
        run_id="run-1",
        actor="actor-1",
    )

    assert result.status == RunStatus.NEEDS_DECISION
    assert result.terminal_reason == RunTerminalReason.RECOVERY_UNSAFE
    assert any(event == "task.reconcile_failed" for event, _ in store.events)


class FakeBeadsClient:
    def __init__(self):
        self.calls = []

    def show(self, task_id):
        return {"id": task_id, "status": "in_progress", "assignee": "worker"}

    def assign_issue(self, task_id, assignee):
        self.calls.append(("assign", task_id, assignee))

    def update_status(self, task_id, status):
        self.calls.append(("status", task_id, status))
        return {"id": task_id, "status": status}


def test_beads_needs_decision_unassigns_before_block(tmp_path: Path):
    client = FakeBeadsClient()
    writer = BeadsTaskCompletionWriter(tmp_path, client=client)

    writer.mark_needs_decision("task-1", reason="policy")

    assert client.calls == [
        ("assign", "task-1", ""),
        ("status", "task-1", "blocked"),
    ]


def test_integration_is_serialized_by_project_lock(monkeypatch, tmp_path: Path):
    calls = []

    @contextmanager
    def fake_lock(root, name):
        calls.append(("enter", root, name))
        yield
        calls.append(("exit", root, name))

    sentinel = object()
    monkeypatch.setattr(integration_app, "project_lock", fake_lock)
    monkeypatch.setattr(
        integration_app,
        "_integrate_run_locked",
        lambda root, run_id: sentinel,
    )

    result = integration_app.integrate_run(tmp_path, "run-1")

    assert result is sentinel
    assert calls[0][2] == "integration"
    assert calls[-1][0] == "exit"
