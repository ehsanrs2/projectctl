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

    def __init__(self, root):
        self.root = root

    def list(self, limit=1000):
        return list(self.active)


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


def setup_common(monkeypatch):
    FakeStore.active = []
    monkeypatch.setattr(auto_app, "RunStore", FakeStore)
    monkeypatch.setattr(auto_app, "project_lock", no_lock)


def test_auto_stops_on_stale_quota_before_prepare(tmp_path: Path, monkeypatch):
    setup_common(monkeypatch)
    monkeypatch.setattr(
        auto_app,
        "collect_status",
        lambda root: status_bundle(stale=True),
    )

    called = []
    monkeypatch.setattr(
        auto_app,
        "prepare_next_run",
        lambda *a, **k: called.append(True),
    )

    report = auto_app.run_auto(tmp_path, AutoRunPolicy(max_tasks=3))

    assert report.stop_reason == AutoStopReason.QUOTA_STALE
    assert report.attempted_tasks == 0
    assert called == []


def test_auto_executes_one_bounded_task(tmp_path: Path, monkeypatch):
    setup_common(monkeypatch)
    monkeypatch.setattr(
        auto_app,
        "collect_status",
        lambda root: status_bundle(),
    )
    monkeypatch.setattr(
        auto_app,
        "prepare_next_run",
        lambda *a, **k: SimpleNamespace(
            record=SimpleNamespace(run_id="run-1")
        ),
    )
    monkeypatch.setattr(
        auto_app,
        "_advance_run",
        lambda root, run_id: SimpleNamespace(
            run_id=run_id,
            task_id="task-1",
            status=RunStatus.PASSED,
            terminal_reason=None,
        ),
    )

    report = auto_app.run_auto(tmp_path, AutoRunPolicy(max_tasks=1))

    assert report.stop_reason == AutoStopReason.MAX_TASKS_REACHED
    assert report.attempted_tasks == 1
    assert report.completed_tasks == 1
    assert report.steps[-1].final_status == RunStatus.PASSED


def test_auto_stops_on_material_project_state_change(tmp_path: Path, monkeypatch):
    setup_common(monkeypatch)
    snapshots = iter(
        [
            status_bundle(project_state_digest="state-before"),
            status_bundle(project_state_digest="state-after"),
        ]
    )
    monkeypatch.setattr(auto_app, "collect_status", lambda root: next(snapshots))
    monkeypatch.setattr(
        auto_app,
        "prepare_next_run",
        lambda *a, **k: SimpleNamespace(
            record=SimpleNamespace(run_id="run-1")
        ),
    )
    monkeypatch.setattr(
        auto_app,
        "_advance_run",
        lambda root, run_id: SimpleNamespace(
            run_id=run_id,
            task_id="task-1",
            status=RunStatus.PASSED,
            terminal_reason=None,
        ),
    )

    report = auto_app.run_auto(tmp_path, AutoRunPolicy(max_tasks=2))

    assert report.stop_reason == AutoStopReason.MATERIAL_PROJECT_STATE_CHANGE
    assert report.completed_tasks == 1


def test_auto_stops_while_external_review_is_pending(tmp_path: Path, monkeypatch):
    setup_common(monkeypatch)
    monkeypatch.setattr(auto_app, "collect_status", lambda root: status_bundle())
    monkeypatch.setattr(
        auto_app,
        "prepare_next_run",
        lambda *a, **k: SimpleNamespace(
            record=SimpleNamespace(run_id="run-review")
        ),
    )
    monkeypatch.setattr(
        auto_app,
        "_advance_run",
        lambda root, run_id: SimpleNamespace(
            run_id=run_id,
            task_id="task-1",
            status=RunStatus.AWAITING_REVIEW,
            terminal_reason=None,
        ),
    )

    report = auto_app.run_auto(tmp_path, AutoRunPolicy(max_tasks=3))

    assert report.stop_reason == AutoStopReason.REVIEW_PENDING
    assert report.attempted_tasks == 1
    assert report.completed_tasks == 0
    assert report.steps[-1].final_status == RunStatus.AWAITING_REVIEW


def test_auto_stops_on_human_decision(tmp_path: Path, monkeypatch):
    setup_common(monkeypatch)
    monkeypatch.setattr(auto_app, "collect_status", lambda root: status_bundle())
    monkeypatch.setattr(
        auto_app,
        "prepare_next_run",
        lambda *a, **k: SimpleNamespace(
            record=SimpleNamespace(run_id="run-1")
        ),
    )
    monkeypatch.setattr(
        auto_app,
        "_advance_run",
        lambda root, run_id: SimpleNamespace(
            run_id=run_id,
            task_id="task-1",
            status=RunStatus.NEEDS_DECISION,
            terminal_reason=None,
        ),
    )

    report = auto_app.run_auto(tmp_path, AutoRunPolicy(max_tasks=3))

    assert report.stop_reason == AutoStopReason.HUMAN_DECISION_REQUIRED
    assert report.attempted_tasks == 1
    assert report.completed_tasks == 0


def test_auto_does_not_compete_with_live_active_run(tmp_path: Path, monkeypatch):
    setup_common(monkeypatch)
    FakeStore.active = [
        SimpleNamespace(
            run_id="run-live",
            task_id="task-live",
            status=RunStatus.RUNNING,
            lease_owner="worker-a",
            lease_expires_at=FUTURE,
        )
    ]

    report = auto_app.run_auto(tmp_path, AutoRunPolicy(max_tasks=2))

    assert report.stop_reason == AutoStopReason.ACTIVE_RUN_PRESENT
    assert report.attempted_tasks == 0


def test_auto_fails_closed_on_multiple_active_runs(tmp_path: Path, monkeypatch):
    setup_common(monkeypatch)
    FakeStore.active = [
        SimpleNamespace(
            run_id="run-1",
            task_id="task-1",
            status=RunStatus.CLAIMED,
            lease_owner=None,
            lease_expires_at=None,
        ),
        SimpleNamespace(
            run_id="run-2",
            task_id="task-2",
            status=RunStatus.VERIFYING,
            lease_owner=None,
            lease_expires_at=None,
        ),
    ]

    report = auto_app.run_auto(tmp_path, AutoRunPolicy(max_tasks=2))

    assert report.stop_reason == AutoStopReason.MULTIPLE_ACTIVE_RUNS


def test_run_auto_cli_is_registered():
    result = runner.invoke(app, ["run", "auto", "--help"])
    assert result.exit_code == 0, result.output



def test_resumed_run_honors_material_project_state_boundary(tmp_path: Path, monkeypatch):
    setup_common(monkeypatch)
    FakeStore.active = [
        SimpleNamespace(
            run_id="run-resume",
            task_id="task-resume",
            status=RunStatus.VERIFYING,
            lease_owner=None,
            lease_expires_at=None,
        )
    ]
    monkeypatch.setattr(
        auto_app,
        "_advance_run",
        lambda root, run_id: SimpleNamespace(
            run_id=run_id,
            task_id="task-resume",
            status=RunStatus.PASSED,
            terminal_reason=None,
        ),
    )
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
            project_state_digest="state-after",
            total=1,
            done=1,
        ),
    )

    report = auto_app.run_auto(tmp_path, AutoRunPolicy(max_tasks=2))

    assert report.stop_reason == AutoStopReason.MATERIAL_PROJECT_STATE_CHANGE
    assert report.completed_tasks == 1
    assert report.steps[-1].project_state_digest_before == "state-before"
    assert report.steps[-1].project_state_digest_after == "state-after"
