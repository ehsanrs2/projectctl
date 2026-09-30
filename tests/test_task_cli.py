import json
import subprocess
from pathlib import Path

from typer.testing import CliRunner

from projectctl.cli.app import app

runner = CliRunner()


def make_repo(tmp_path: Path, monkeypatch) -> Path:
    repo = tmp_path / "demo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    monkeypatch.setenv("PROJECTCTL_HOME", str(tmp_path / "home"))
    result = runner.invoke(app, ["init", str(repo)])
    assert result.exit_code == 0, result.output
    return repo


def test_import_tasks_dry_run_does_not_require_beads_binary(tmp_path: Path, monkeypatch):
    repo = make_repo(tmp_path, monkeypatch)
    feature = repo / "specs" / "001"
    feature.mkdir(parents=True)
    source = feature / "tasks.md"
    source.write_text("## Phase 1: Setup\n- [ ] T001 Create file in src/a.py\n", encoding="utf-8")

    # Empty PATH proves preview is local and does not invoke Beads.
    monkeypatch.setenv("PATH", "")
    result = runner.invoke(
        app,
        ["import-tasks", str(source), "--project", str(repo), "--dry-run", "--json"],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["source_type"] == "speckit_tasks"
    assert payload["items"][0]["action"] == "create"
