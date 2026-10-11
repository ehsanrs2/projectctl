import json
import socket
import threading
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
from projectctl.project import locking as locking_module
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
        "execution_ownership_policy",
        lambda root: SimpleNamespace(strategy="task_native"),
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


def test_stale_lock_reclamation_is_serialized_across_contenders(
    tmp_path: Path,
    monkeypatch,
):
    root = tmp_path / "repo"
    lock_dir = root / ".projectctl" / "locks"
    lock_dir.mkdir(parents=True)
    path = lock_dir / "execution-authority.lock"
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

    first_reclaimer_check = threading.Event()
    second_reclaimer_waiting = threading.Event()
    release_reclaimer_check = threading.Event()
    operation_entered = threading.Event()
    release_operation = threading.Event()
    blocked = threading.Event()
    outcomes = []
    first_check = {"value": True}
    first_check_lock = threading.Lock()
    guard_calls = {"count": 0}
    original_guard = locking_module._stale_reclamation_guard
    original_can_reclaim = locking_module._can_reclaim

    @contextmanager
    def tracked_reclamation_guard(lock_directory: Path):
        with first_check_lock:
            guard_calls["count"] += 1
            current_call = guard_calls["count"]
        if current_call == 2:
            second_reclaimer_waiting.set()
        with original_guard(lock_directory):
            yield

    monkeypatch.setattr(
        locking_module,
        "_stale_reclamation_guard",
        tracked_reclamation_guard,
    )

    def delayed_can_reclaim(lock_path: Path, *, hostname: str) -> bool:
        with first_check_lock:
            pause = first_check["value"]
            first_check["value"] = False
        if pause:
            first_reclaimer_check.set()
            if not release_reclaimer_check.wait(timeout=5):
                raise AssertionError("Timed out waiting to release stale-lock reclaimer.")
        return original_can_reclaim(lock_path, hostname=hostname)

    monkeypatch.setattr(locking_module, "_can_reclaim", delayed_can_reclaim)

    def contender():
        try:
            with project_lock(root, "execution-authority"):
                operation_entered.set()
                if not release_operation.wait(timeout=5):
                    raise AssertionError("Timed out waiting to release lock owner.")
                outcomes.append("acquired")
        except ProjectLockError:
            outcomes.append("blocked")
            blocked.set()
        except BaseException as exc:
            outcomes.append(exc)

    first = threading.Thread(target=contender)
    first.start()
    assert first_reclaimer_check.wait(timeout=5)

    second = threading.Thread(target=contender)
    second.start()
    assert second_reclaimer_waiting.wait(timeout=5)
    release_reclaimer_check.set()

    assert operation_entered.wait(timeout=5)
    assert blocked.wait(timeout=5)
    release_operation.set()
    first.join(timeout=5)
    second.join(timeout=5)

    assert not first.is_alive()
    assert not second.is_alive()
    assert outcomes.count("acquired") == 1
    assert outcomes.count("blocked") == 1
    assert not any(isinstance(item, BaseException) for item in outcomes)
