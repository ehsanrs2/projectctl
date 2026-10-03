import json
import sqlite3
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from typer.testing import CliRunner

from projectctl.cli.entry import app
from projectctl.core.enums import ResourceClass, RiskLevel, TaskStatus, TaskType
from projectctl.schemas.task import NormalizedTask, TaskSnapshot, TaskSource

runner = CliRunner()
NOW = datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc)


def make_repo(tmp_path: Path, monkeypatch) -> Path:
    repo = tmp_path / "demo"; repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    monkeypatch.setenv("PROJECTCTL_HOME", str(tmp_path / "home"))
    result = runner.invoke(app, ["init", str(repo)])
    assert result.exit_code == 0, result.output
    return repo


def test_quota_set_and_show(tmp_path: Path, monkeypatch):
    repo = make_repo(tmp_path, monkeypatch)
    result = runner.invoke(app, ["quota", "set", "--project", str(repo), "--five-hour", "60%", "--weekly", "0.40", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["snapshot"]["five_hour"]["remaining_ratio"] == .6
    assert payload["snapshot"]["weekly"]["remaining_ratio"] == .4

    shown = runner.invoke(app, ["quota", "--project", str(repo), "--json"])
    assert shown.exit_code == 0, shown.output
    assert json.loads(shown.output)["snapshot"]["account"] == "openai-default"


def test_next_and_explain_next_use_scheduler_decision(tmp_path: Path, monkeypatch):
    repo = make_repo(tmp_path, monkeypatch)
    setq = runner.invoke(app, ["quota", "set", "--project", str(repo), "--five-hour", "90%", "--weekly", "90%"])
    assert setq.exit_code == 0, setq.output
    task = NormalizedTask(
        id="TASK-1", title="Implement scheduler",
        source=TaskSource(provider="test", external_id="TASK-1", observed_at=NOW),
        type=TaskType.FEATURE, status=TaskStatus.READY, priority=8,
        risk=RiskLevel.LOW, resource_class=ResourceClass.MEDIUM,
    )
    snapshot = TaskSnapshot(provider="test", captured_at=NOW, source_revision="r1", tasks=[task])
    monkeypatch.setattr("projectctl.application.scheduling.capture_task_snapshot", lambda root, state="all": snapshot)

    nxt = runner.invoke(app, ["next", "--project", str(repo), "--json"])
    assert nxt.exit_code == 0, nxt.output
    payload = json.loads(nxt.output)
    assert payload["selected_task_id"] == "TASK-1"
    assert payload["candidates"][0]["model"]["profile"] == "balanced"

    conn = sqlite3.connect(repo / ".projectctl" / "telemetry.sqlite")
    try:
        event_types = [row[0] for row in conn.execute("SELECT event_type FROM events ORDER BY id")]
    finally:
        conn.close()
    assert "scheduler.decision" in event_types
    assert "model.recommendation" in event_types

    explained = runner.invoke(app, ["explain-next", "--project", str(repo)])
    assert explained.exit_code == 0, explained.output
    assert "TASK-1" in explained.output
    assert "Selected: TASK-1" in explained.output
