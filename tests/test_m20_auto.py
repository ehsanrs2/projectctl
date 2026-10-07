from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from typer.testing import CliRunner

from projectctl.application import auto as auto_app
from projectctl.cli.entry import app
from projectctl.core.enums import AutoStopReason, QuotaMode, RunStatus
from projectctl.schemas.auto import AutoRunPolicy

runner = CliRunner()
FUTURE = datetime(2099, 1, 1, tzinfo=timezone.utc)


@contextmanager
def no_lock(root, name):
    yield


class FakeStore:
    active = []
    records = {}

    def __init__(self, root):
        self.root = root

    def list(self, limit=1000):
        return list(self.active)

    def get(self, run_id):
        return self.records[run_id]


def record(
    run_id="run-1",
    task_id="task-1",
    status=RunStatus.CLAIMED,
    *,
    terminal_reason=None,
    lease_owner=None,
    lease_expires_at=None,
    checkpoint_ref=None,
):
    return SimpleNamespace(
        run_id=run_id,
        task_id=task_id,
        status=status,
        terminal_reason=terminal_reason,
        lease_owner=lease_owner,
        lease_expires_at=lease_expires_at,
        checkpoint_ref=checkpoint_ref,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


def status_bundle(
    *,
    selected="task-1",
    project_state_digest="state-1",
    quota_mode=QuotaMode.NORMAL,
    stale=False,
    total=1,
    done=0,
):
    return SimpleNamespace(
        decision=SimpleNamespace(
            selected_task_id=selected,
            project_state_digest=project_state_digest,
        ),
        quota_state=SimpleNamespace(
            mode=quota_mode,
            stale=stale,
        ),
        status=SimpleNamespace(
            task_counts=SimpleNamespace(
                total=total,
                done=done,
            )
        ),
    )


def maintenance(*steps):
    return SimpleNamespace(steps=list(steps))


def portfolio_decision(
    *,
    selected_instance="instance-local",
    busy=False,
):
    return SimpleNamespace(
        account_busy=busy,
        active_project_instance_id=(
            "instance-busy" if busy else None
        ),
        active_run_id=("run-busy" if busy else None),
        selected_project_instance_id=(
            None if busy else selected_instance
        ),
        selected_project_id=(
            None if busy else "project-local"
        ),
    )


def turn_result(run_id, action="admit_task", status=RunStatus.VERIFYING):
    return SimpleNamespace(
        run_id=run_id,
        run_status=status,
        project_turn=SimpleNamespace(
            envelope=SimpleNamespace(
                action=action,
                run_status=(
                    RunStatus.CLAIMED
                    if action == "start_run"
                    else RunStatus.RUNNING
                    if action == "resume_run"
                    else None
                ),
            )
        ),
    )


def setup_common(monkeypatch):
    FakeStore.active = []
    FakeStore.records = {}
    monkeypatch.setattr(auto_app, "RunStore", FakeStore)
    monkeypatch.setattr(auto_app, "project_lock", no_lock)
    monkeypatch.setattr(
        auto_app,
        "advance_non_worker_phases",
        lambda root: maintenance(),
    )


def test_auto_stops_on_stale_quota_before_portfolio_turn(
    tmp_path: Path, monkeypatch
):
    setup_common(monkeypatch)
    monkeypatch.setattr(
        auto_app,
        "collect_status",
        lambda root: status_bundle(stale=True),
    )
    called = []
    monkeypatch.setattr(
        auto_app,
        "request_fair_project_turn",
        lambda *a, **k: called.append(True),
    )

    report = auto_app.run_auto(tmp_path, AutoRunPolicy(max_tasks=3))

    assert report.stop_reason == AutoStopReason.QUOTA_STALE
    assert report.attempted_tasks == 0
    assert called == []


def test_auto_executes_one_bounded_task_through_portfolio(
    tmp_path: Path, monkeypatch
):
    setup_common(monkeypatch)
    monkeypatch.setattr(
        auto_app,
        "collect_status",
        lambda root: status_bundle(),
    )

    def fair_turn(*args, **kwargs):
        final = record(status=RunStatus.PASSED)
        FakeStore.records["run-1"] = final
        FakeStore.active = []
        return portfolio_decision(), turn_result(
            "run-1",
            action="admit_task",
            status=RunStatus.VERIFYING,
        )

    monkeypatch.setattr(
        auto_app,
        "request_fair_project_turn",
        fair_turn,
    )

    report = auto_app.run_auto(tmp_path, AutoRunPolicy(max_tasks=1))

    assert report.stop_reason == AutoStopReason.MAX_TASKS_REACHED
    assert report.attempted_tasks == 1
    assert report.completed_tasks == 1
    assert report.steps[-1].final_status == RunStatus.PASSED
    assert report.steps[-1].action == "admit_task"


def test_auto_stops_on_material_project_state_change(
    tmp_path: Path, monkeypatch
):
    setup_common(monkeypatch)
    snapshots = iter(
        [
            status_bundle(project_state_digest="state-before"),
            status_bundle(project_state_digest="state-after"),
        ]
    )
    monkeypatch.setattr(
        auto_app,
        "collect_status",
        lambda root: next(snapshots),
    )

    def fair_turn(*args, **kwargs):
        FakeStore.records["run-1"] = record(status=RunStatus.PASSED)
        return portfolio_decision(), turn_result("run-1")

    monkeypatch.setattr(
        auto_app,
        "request_fair_project_turn",
        fair_turn,
    )

    report = auto_app.run_auto(tmp_path, AutoRunPolicy(max_tasks=2))

    assert report.stop_reason == AutoStopReason.MATERIAL_PROJECT_STATE_CHANGE
    assert report.completed_tasks == 1


def test_auto_stops_while_external_review_is_pending(
    tmp_path: Path, monkeypatch
):
    setup_common(monkeypatch)
    pending = record(
        run_id="run-review",
        status=RunStatus.AWAITING_REVIEW,
    )
    FakeStore.active = [pending]
    FakeStore.records[pending.run_id] = pending
    monkeypatch.setattr(
        auto_app,
        "collect_status",
        lambda root: status_bundle(),
    )

    report = auto_app.run_auto(tmp_path, AutoRunPolicy(max_tasks=3))

    assert report.stop_reason == AutoStopReason.REVIEW_PENDING
    assert report.attempted_tasks == 1
    assert report.completed_tasks == 0


def test_auto_stops_on_human_decision_after_fair_turn(
    tmp_path: Path, monkeypatch
):
    setup_common(monkeypatch)
    monkeypatch.setattr(
        auto_app,
        "collect_status",
        lambda root: status_bundle(),
    )

    def fair_turn(*args, **kwargs):
        FakeStore.records["run-1"] = record(
            status=RunStatus.NEEDS_DECISION
        )
        return portfolio_decision(), turn_result("run-1")

    monkeypatch.setattr(
        auto_app,
        "request_fair_project_turn",
        fair_turn,
    )

    report = auto_app.run_auto(tmp_path, AutoRunPolicy(max_tasks=3))

    assert report.stop_reason == AutoStopReason.HUMAN_DECISION_REQUIRED
    assert report.attempted_tasks == 1
    assert report.completed_tasks == 0


def test_auto_does_not_compete_with_live_active_run(
    tmp_path: Path, monkeypatch
):
    setup_common(monkeypatch)
    live = record(
        run_id="run-live",
        task_id="task-live",
        status=RunStatus.RUNNING,
        lease_owner="worker-a",
        lease_expires_at=FUTURE,
        checkpoint_ref="checkpoint",
    )
    FakeStore.active = [live]
    FakeStore.records[live.run_id] = live

    report = auto_app.run_auto(tmp_path, AutoRunPolicy(max_tasks=2))

    assert report.stop_reason == AutoStopReason.ACTIVE_RUN_PRESENT
    assert report.attempted_tasks == 0


def test_auto_uses_fair_dispatcher_for_parallel_active_set(
    tmp_path: Path, monkeypatch
):
    setup_common(monkeypatch)
    first = record(run_id="run-1", task_id="task-1", status=RunStatus.CLAIMED)
    second = record(run_id="run-2", task_id="task-2", status=RunStatus.VERIFYING)
    FakeStore.active = [first, second]
    FakeStore.records = {"run-1": first, "run-2": second}

    monkeypatch.setattr(
        auto_app,
        "collect_status",
        lambda root: status_bundle(selected=None, total=2, done=1),
    )

    def maintain(root):
        current = FakeStore.records.get("run-2")
        if current is not None and current.status == RunStatus.VERIFYING:
            passed = record(
                run_id="run-2",
                task_id="task-2",
                status=RunStatus.PASSED,
            )
            FakeStore.records["run-2"] = passed
            FakeStore.active = [
                item for item in FakeStore.active if item.run_id != "run-2"
            ]
            return maintenance(
                SimpleNamespace(
                    run_id="run-2",
                    action="verify",
                    started_status=RunStatus.VERIFYING,
                    final_status=RunStatus.PASSED,
                    detail=None,
                )
            )
        return maintenance()

    monkeypatch.setattr(auto_app, "advance_non_worker_phases", maintain)

    def fair_turn(*args, **kwargs):
        passed = record(
            run_id="run-1",
            task_id="task-1",
            status=RunStatus.PASSED,
        )
        FakeStore.records["run-1"] = passed
        FakeStore.active = [
            item for item in FakeStore.active if item.run_id != "run-1"
        ]
        return portfolio_decision(), turn_result(
            "run-1",
            action="start_run",
            status=RunStatus.VERIFYING,
        )

    monkeypatch.setattr(auto_app, "request_fair_project_turn", fair_turn)

    report = auto_app.run_auto(tmp_path, AutoRunPolicy(max_tasks=1))

    assert report.stop_reason == AutoStopReason.MAX_TASKS_REACHED
    assert report.completed_tasks == 1
    assert report.attempted_tasks == 1
    assert report.steps[-1].action == "start_run"


def test_auto_yields_when_portfolio_selects_another_project(
    tmp_path: Path, monkeypatch
):
    setup_common(monkeypatch)
    monkeypatch.setattr(
        auto_app,
        "collect_status",
        lambda root: status_bundle(),
    )
    monkeypatch.setattr(
        auto_app,
        "request_fair_project_turn",
        lambda *a, **k: (
            portfolio_decision(selected_instance="instance-other"),
            None,
        ),
    )

    report = auto_app.run_auto(tmp_path, AutoRunPolicy(max_tasks=2))

    assert report.stop_reason == AutoStopReason.PORTFOLIO_YIELD
    assert report.attempted_tasks == 1
    assert report.steps[-1].action == "portfolio_yield"


def test_resumed_run_uses_fair_dispatcher(
    tmp_path: Path, monkeypatch
):
    setup_common(monkeypatch)
    claimed = record(
        run_id="run-resume",
        task_id="task-resume",
        status=RunStatus.CLAIMED,
    )
    FakeStore.active = [claimed]
    FakeStore.records[claimed.run_id] = claimed
    monkeypatch.setattr(
        auto_app,
        "_execution_plan_state_digest",
        lambda root, run_id: "state-before",
    )
    monkeypatch.setattr(
        auto_app,
        "collect_status",
        lambda root: status_bundle(
            selected=None,
            project_state_digest="state-before",
        ),
    )

    def fair_turn(*args, **kwargs):
        FakeStore.records["run-resume"] = record(
            run_id="run-resume",
            task_id="task-resume",
            status=RunStatus.PASSED,
        )
        FakeStore.active = []
        return portfolio_decision(), turn_result(
            "run-resume",
            action="start_run",
        )

    monkeypatch.setattr(
        auto_app,
        "request_fair_project_turn",
        fair_turn,
    )

    report = auto_app.run_auto(tmp_path, AutoRunPolicy(max_tasks=1))

    assert report.completed_tasks == 1
    assert report.steps[-1].action == "start_run"


def test_run_auto_cli_is_registered():
    result = runner.invoke(app, ["run", "auto", "--help"])
    assert result.exit_code == 0, result.output



def test_auto_counts_non_worker_resume_that_finishes_passed(
    tmp_path: Path,
    monkeypatch,
):
    setup_common(monkeypatch)
    verifying = record(
        run_id="run-verify",
        task_id="task-verify",
        status=RunStatus.VERIFYING,
    )
    FakeStore.active = [verifying]
    FakeStore.records[verifying.run_id] = verifying
    monkeypatch.setattr(
        auto_app,
        "_execution_plan_state_digest",
        lambda root, run_id: "state-before",
    )

    def maintain(root):
        passed = record(
            run_id="run-verify",
            task_id="task-verify",
            status=RunStatus.PASSED,
        )
        FakeStore.records["run-verify"] = passed
        FakeStore.active = []
        return maintenance(
            SimpleNamespace(
                run_id="run-verify",
                action="verify",
                started_status=RunStatus.VERIFYING,
                final_status=RunStatus.PASSED,
                detail=None,
            )
        )

    monkeypatch.setattr(auto_app, "advance_non_worker_phases", maintain)
    monkeypatch.setattr(
        auto_app,
        "collect_status",
        lambda root: status_bundle(
            selected=None,
            project_state_digest="state-before",
            total=1,
            done=1,
        ),
    )

    report = auto_app.run_auto(tmp_path, AutoRunPolicy(max_tasks=1))

    assert report.attempted_tasks == 1
    assert report.completed_tasks == 1
    assert report.steps[-1].action == "resume_non_worker"
    assert report.steps[-1].final_status == RunStatus.PASSED
