import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from typer.testing import CliRunner

from projectctl.cli.entry import app
from projectctl.core.enums import (
    ConfidenceLevel,
    QuotaSource,
    ResourceClass,
    RiskLevel,
    TaskStatus,
    TaskType,
)
from projectctl.project.freshness import generated_freshness
from projectctl.project.state import load_project_state
from projectctl.scheduler.service import SchedulerService
from projectctl.schemas.config import ProjectConfig, ProjectIdentity
from projectctl.schemas.project_state import MilestoneState, ProjectState
from projectctl.schemas.quota import QuotaSnapshot, QuotaWindow
from projectctl.schemas.task import NormalizedTask, TaskSnapshot, TaskSource

runner = CliRunner()
NOW = datetime(2026, 10, 3, 6, 0, tzinfo=timezone.utc)


def make_repo(tmp_path: Path, monkeypatch) -> Path:
    repo = tmp_path / "demo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    monkeypatch.setenv("PROJECTCTL_HOME", str(tmp_path / "home"))
    result = runner.invoke(app, ["init", str(repo)])
    assert result.exit_code == 0, result.output
    return repo


def task(task_id: str, milestone: str | None) -> NormalizedTask:
    return NormalizedTask(
        id=task_id,
        title=task_id,
        source=TaskSource(provider="test", external_id=task_id, observed_at=NOW),
        type=TaskType.FEATURE,
        status=TaskStatus.READY,
        priority=5,
        milestone=milestone,
        risk=RiskLevel.LOW,
        resource_class=ResourceClass.SMALL,
    )


def quota() -> QuotaSnapshot:
    return QuotaSnapshot(
        provider="manual",
        account="openai-default",
        observed_at=NOW,
        five_hour=QuotaWindow(
            remaining_ratio=.9,
            source=QuotaSource.MANUAL,
            confidence=ConfidenceLevel.MEDIUM,
        ),
        weekly=QuotaWindow(
            remaining_ratio=.9,
            source=QuotaSource.MANUAL,
            confidence=ConfidenceLevel.MEDIUM,
        ),
    )


def test_greenfield_init_creates_structured_project_state(tmp_path: Path, monkeypatch):
    repo = make_repo(tmp_path, monkeypatch)
    path = repo / "docs" / "PROJECT_STATE.yaml"
    assert path.exists()
    state = load_project_state(repo, allow_missing=False)
    assert state.project_id == "demo"


def test_state_set_updates_goal_milestone_and_aliases(tmp_path: Path, monkeypatch):
    repo = make_repo(tmp_path, monkeypatch)
    result = runner.invoke(app, [
        "state", "set", "--project", str(repo),
        "--goal", "Ship M0.5",
        "--milestone", "M0.5",
        "--milestone-title", "Project State",
        "--alias", "state-awareness",
        "--json",
    ])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["current_goal"] == "Ship M0.5"
    assert payload["active_milestone"]["id"] == "M0.5"
    assert payload["active_milestone"]["aliases"] == ["state-awareness"]


def test_scheduler_uses_explicit_active_milestone():
    config = ProjectConfig(project=ProjectIdentity(id="demo"))
    snapshot = TaskSnapshot(
        provider="test",
        captured_at=NOW,
        source_revision="r1",
        tasks=[
            task("a-non-milestone", "M0.4"),
            task("z-active-milestone", "m0.5"),
        ],
    )
    state = ProjectState(
        project_id="demo",
        active_milestone=MilestoneState(id="M0.5", title="Project State"),
    )
    decision = SchedulerService().decide(
        config=config,
        tasks=snapshot,
        quota=quota(),
        project_state=state,
        now=NOW,
    )
    assert decision.schema_version == 2
    assert decision.active_milestone_id == "M0.5"
    assert decision.selected_task_id == "z-active-milestone"
    selected = next(c for c in decision.candidates if c.task_id == "z-active-milestone")
    assert selected.score.milestone_relevance == 8.0


def test_project_state_digest_changes_when_active_milestone_changes():
    config = ProjectConfig(project=ProjectIdentity(id="demo"))
    snapshot = TaskSnapshot(provider="test", captured_at=NOW, source_revision="r1", tasks=[task("a", "M0.5")])
    first = SchedulerService().decide(
        config=config,
        tasks=snapshot,
        quota=quota(),
        project_state=ProjectState(project_id="demo", active_milestone=MilestoneState(id="M0.5")),
        now=NOW,
    )
    second = SchedulerService().decide(
        config=config,
        tasks=snapshot,
        quota=quota(),
        project_state=ProjectState(project_id="demo", active_milestone=MilestoneState(id="M0.6")),
        now=NOW,
    )
    assert first.project_state_digest != second.project_state_digest


def test_status_and_refresh_share_one_source_digest(tmp_path: Path, monkeypatch):
    repo = make_repo(tmp_path, monkeypatch)
    assert runner.invoke(app, [
        "state", "set", "--project", str(repo),
        "--goal", "M0.5 goal", "--milestone", "M0.5",
    ]).exit_code == 0
    assert runner.invoke(app, [
        "quota", "set", "--project", str(repo),
        "--five-hour", "90%", "--weekly", "90%",
    ]).exit_code == 0

    snapshot = TaskSnapshot(
        provider="test",
        captured_at=NOW,
        source_revision="r1",
        tasks=[task("TASK-1", "M0.5")],
    )
    monkeypatch.setattr("projectctl.application.status.capture_task_snapshot", lambda root, state="all": snapshot)

    status_result = runner.invoke(app, ["status", "--project", str(repo), "--json"])
    assert status_result.exit_code == 0, status_result.output
    status_payload = json.loads(status_result.output)
    assert status_payload["next_task_id"] == "TASK-1"
    assert status_payload["active_milestone"]["id"] == "M0.5"

    refresh_result = runner.invoke(app, ["refresh", "--project", str(repo), "--json"])
    assert refresh_result.exit_code == 0, refresh_result.output
    refresh_payload = json.loads(refresh_result.output)
    assert set(refresh_payload["written"]) == {
        "docs/generated/STATUS.md",
        "docs/generated/BUDGET.md",
        "docs/generated/TASKBOARD.md",
    }
    missing, stale, expected = generated_freshness(repo)
    assert missing == []
    assert stale == []
    assert expected == refresh_payload["source_digest"]

    assert runner.invoke(app, [
        "state", "set", "--project", str(repo), "--goal", "Changed goal"
    ]).exit_code == 0
    missing, stale, _ = generated_freshness(repo)
    assert missing == []
    assert sorted(stale) == ["BUDGET.md", "STATUS.md", "TASKBOARD.md"]
