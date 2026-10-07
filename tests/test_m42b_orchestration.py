from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from projectctl.application import turns
from projectctl.core.enums import QuotaMode, ResourceClass, RunStatus, TaskStatus
from projectctl.core.errors import ConfigurationError
from projectctl.application import portfolio as portfolio_app
from projectctl.application import turns as turns_app
from projectctl.parallel import runtime
from projectctl.schemas.orchestration import ProjectTurnEnvelope
from projectctl.schemas.task import NormalizedTask, TaskSource

NOW = datetime(2026, 10, 7, 10, 30, tzinfo=timezone.utc)


def task(task_id: str) -> NormalizedTask:
    return NormalizedTask(
        id=task_id,
        title=task_id,
        source=TaskSource(provider="test", external_id=task_id),
        status=TaskStatus.READY,
        resource_class=ResourceClass.SMALL,
    )


def run(
    run_id: str,
    task_id: str,
    status: RunStatus,
    *,
    checkpoint_ref: str | None = None,
    lease_owner: str | None = None,
    lease_expires_at=None,
    seconds: int = 0,
):
    return SimpleNamespace(
        run_id=run_id,
        task_id=task_id,
        status=status,
        checkpoint_ref=checkpoint_ref,
        lease_owner=lease_owner,
        lease_expires_at=lease_expires_at,
        created_at=NOW + timedelta(seconds=seconds),
    )


class AlwaysEligibleQuota:
    def __init__(self, policy):
        pass

    def eligible_for_resource(self, resource_class, state):
        return True


def status(task_id="task-b"):
    return SimpleNamespace(
        decision=SimpleNamespace(
            selected_task_id=task_id,
            project_state_digest="project-state",
            task_snapshot_digest="tasks",
            quota_snapshot_digest="quota",
        ),
        quota_state=SimpleNamespace(
            stale=False,
            mode=QuotaMode.NORMAL,
        ),
        tasks=SimpleNamespace(tasks=[task(task_id), task("task-a")]),
    )


def setup_turns(monkeypatch, active, *, max_active=2, selected="task-b"):
    monkeypatch.setattr(
        turns,
        "load_project_config",
        lambda root: SimpleNamespace(
            project=SimpleNamespace(id="repo"),
            quota=SimpleNamespace(account="acct"),
            orchestration=SimpleNamespace(max_active_runs=max_active),
        ),
    )
    monkeypatch.setattr(turns, "project_instance_id", lambda root: "instance")
    monkeypatch.setattr(turns, "_active_records", lambda root: list(active))
    monkeypatch.setattr(
        turns,
        "build_parallel_integration_queue",
        lambda *args, **kwargs: SimpleNamespace(entries=[]),
    )
    monkeypatch.setattr(
        turns,
        "collect_status",
        lambda *args, **kwargs: status(selected),
    )
    monkeypatch.setattr(turns, "QuotaManager", AlwaysEligibleQuota)


def test_turn_arbiter_accepts_multiple_active_runs_and_selects_continuation(
    tmp_path: Path,
    monkeypatch,
):
    active = [
        run(
            "run-verify",
            "task-a",
            RunStatus.VERIFYING,
            seconds=0,
        ),
        run(
            "run-start",
            "task-b",
            RunStatus.CLAIMED,
            seconds=1,
        ),
    ]
    setup_turns(monkeypatch, active, max_active=3, selected="task-b")

    envelope = turns.collect_project_turn_envelope(tmp_path, now=NOW)

    assert envelope.eligible is True
    assert envelope.action == "start_run"
    assert envelope.run_id == "run-start"
    assert envelope.active_run_count == 2
    assert envelope.non_worker_run_ids == ["run-verify"]


def test_non_worker_active_run_allows_independent_parallel_admission(
    tmp_path: Path,
    monkeypatch,
):
    active = [
        run(
            "run-verify",
            "task-a",
            RunStatus.VERIFYING,
        )
    ]
    setup_turns(monkeypatch, active, max_active=2, selected="task-b")

    binding = SimpleNamespace(
        run_id="run-verify",
        admitted_plan=SimpleNamespace(task_id="task-a"),
    )
    monkeypatch.setattr(
        turns,
        "load_parallel_run_binding",
        lambda *args, **kwargs: binding,
    )
    monkeypatch.setattr(
        turns,
        "build_parallel_plan",
        lambda *args, **kwargs: SimpleNamespace(task_id="task-b"),
    )
    monkeypatch.setattr(
        turns,
        "assess_parallel_safety",
        lambda *args, **kwargs: SimpleNamespace(
            independent=True,
            conflicts=[],
        ),
    )

    envelope = turns.collect_project_turn_envelope(tmp_path, now=NOW)

    assert envelope.eligible is True
    assert envelope.action == "admit_task"
    assert envelope.parallel_admission is True
    assert envelope.active_run_ids == ["run-verify"]


def test_parallel_active_set_capacity_is_authoritative(
    tmp_path: Path,
    monkeypatch,
):
    active = [
        run("run-a", "task-a", RunStatus.VERIFYING, seconds=0),
        run("run-b", "task-b", RunStatus.READY_TO_INTEGRATE, seconds=1),
    ]
    setup_turns(monkeypatch, active, max_active=2, selected="task-c")

    envelope = turns.collect_project_turn_envelope(tmp_path, now=NOW)

    assert envelope.eligible is False
    assert envelope.action is None
    assert "active_set_capacity_reached" in envelope.exclusion_reasons


def test_worker_relevant_live_lease_blocks_another_worker_turn(
    tmp_path: Path,
    monkeypatch,
):
    active = [
        run(
            "run-live",
            "task-a",
            RunStatus.CLAIMED,
            lease_owner="owner",
            lease_expires_at=NOW + timedelta(minutes=1),
        ),
        run(
            "run-other",
            "task-b",
            RunStatus.CLAIMED,
            seconds=1,
        ),
    ]
    setup_turns(monkeypatch, active, max_active=3, selected="task-c")

    envelope = turns.collect_project_turn_envelope(tmp_path, now=NOW)

    assert envelope.eligible is False
    assert "active_set_recovery_required" in envelope.exclusion_reasons
    assert any("run-live:active_run_leased" in item for item in envelope.details)


def test_execute_parallel_admission_is_bound_to_turn_snapshot(
    tmp_path: Path,
    monkeypatch,
):
    envelope = ProjectTurnEnvelope(
        envelope_id="turn-1",
        observed_at=NOW,
        project_instance_id="instance",
        project_id="repo",
        project_root=str(tmp_path),
        account_id="acct",
        eligible=True,
        action="admit_task",
        task_id="task-b",
        resource_class=ResourceClass.SMALL,
        project_state_digest="state",
        task_snapshot_digest="tasks",
        quota_snapshot_digest="quota",
        quota_mode=QuotaMode.NORMAL,
        quota_stale=False,
        active_run_ids=["run-a"],
        active_run_count=1,
        max_active_runs=2,
        parallel_admission=True,
    )
    monkeypatch.setattr(
        turns,
        "collect_project_turn_envelope",
        lambda *args, **kwargs: envelope,
    )
    observed = {}

    def prepare(root, **kwargs):
        observed.update(kwargs)
        return SimpleNamespace(record=SimpleNamespace(run_id="run-new"))

    monkeypatch.setattr(turns, "prepare_parallel_run", prepare)
    monkeypatch.setattr(
        turns,
        "start_prepared_run",
        lambda root, run_id: SimpleNamespace(
            record=SimpleNamespace(
                run_id=run_id,
                status=RunStatus.VERIFYING,
            )
        ),
    )

    result = turns.execute_project_turn(tmp_path, envelope)

    assert result.prepared_new_run is True
    assert result.run_id == "run-new"
    assert observed["max_parallel_runs"] == 2
    assert observed["expected_task_id"] == "task-b"
    assert observed["expected_task_snapshot_digest"] == "tasks"
    assert observed["expected_project_state_digest"] == "state"


def test_parallel_batch_capacity_comes_from_project_config(
    tmp_path: Path,
    monkeypatch,
):
    monkeypatch.setattr(
        runtime,
        "load_project_config",
        lambda root: SimpleNamespace(
            orchestration=SimpleNamespace(max_active_runs=3)
        ),
    )

    with pytest.raises(
        ConfigurationError,
        match="must equal configured orchestration.max_active_runs=3",
    ):
        runtime.run_parallel_batch(tmp_path, max_parallel_runs=2)


def test_m42b_public_schema_surface():
    from projectctl.schema_export import PUBLIC_SCHEMAS

    expected = {
        "project-config.v8.schema.json",
        "project-config.v9.schema.json",
        "project-turn-envelope.v1.schema.json",
        "project-turn-result.v1.schema.json",
        "project-maintenance-result.v1.schema.json",
        "orchestration-status.v1.schema.json",
        "portfolio-decision.v1.schema.json",
        "portfolio-decision.v2.schema.json",
        "portfolio-turn-result.v1.schema.json",
        "portfolio-turn-result.v2.schema.json",
    }
    assert expected <= set(PUBLIC_SCHEMAS)



def test_first_slot_is_parallel_bound_when_project_capacity_exceeds_one(
    tmp_path: Path,
    monkeypatch,
):
    setup_turns(monkeypatch, [], max_active=2, selected="task-b")
    monkeypatch.setattr(
        turns,
        "build_parallel_plan",
        lambda *args, **kwargs: SimpleNamespace(task_id="task-b"),
    )

    envelope = turns.collect_project_turn_envelope(tmp_path, now=NOW)

    assert envelope.eligible is True
    assert envelope.action == "admit_task"
    assert envelope.parallel_admission is True
    assert envelope.active_run_count == 0



def test_parallel_batch_requests_global_fair_turns(
    tmp_path: Path,
    monkeypatch,
):
    monkeypatch.setattr(
        runtime,
        "load_project_config",
        lambda root: SimpleNamespace(
            orchestration=SimpleNamespace(max_active_runs=2)
        ),
    )
    monkeypatch.setattr(runtime, "_active_records", lambda root: [])
    calls = []

    def fair_turn(root, **kwargs):
        calls.append(str(root))
        if len(calls) == 1:
            return (
                SimpleNamespace(
                    account_busy=False,
                    selected_project_instance_id="instance",
                    selected_project_id="repo",
                ),
                SimpleNamespace(
                    run_id="run-new",
                    run_status=RunStatus.VERIFYING,
                    action="admit_task",
                    project_turn=SimpleNamespace(prepared_new_run=True),
                ),
            )
        return (
            SimpleNamespace(
                account_busy=False,
                selected_project_instance_id="other-instance",
                selected_project_id="other",
            ),
            None,
        )

    monkeypatch.setattr(
        portfolio_app,
        "request_fair_project_turn",
        fair_turn,
    )
    monkeypatch.setattr(
        turns_app,
        "advance_non_worker_phases",
        lambda root: SimpleNamespace(steps=[]),
    )
    monkeypatch.setattr(
        runtime,
        "RunStore",
        lambda root: SimpleNamespace(
            get=lambda run_id: SimpleNamespace(status=RunStatus.PASSED)
        ),
    )

    result = runtime.run_parallel_batch(tmp_path)

    assert len(calls) == 2
    assert result.prepared_run_ids == ["run-new"]
    assert result.completed_run_ids == ["run-new"]
    assert any(
        item.startswith("portfolio_yield:selected_other_project")
        for item in result.details
    )
