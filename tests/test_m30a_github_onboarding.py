import json
import os
import stat
import subprocess
from pathlib import Path

import yaml
from typer.testing import CliRunner

from projectctl.cli.app import app
from projectctl.project.adoption import plan_adoption
from projectctl.project.inspection import inspect_repository
from projectctl.project.loader import load_project_config

runner = CliRunner()

FAKE_GH = r'''#!/usr/bin/env python3
import json, sys
args = sys.argv[1:]
if args == ["--version"]:
    print("gh version 2.99.0")
    raise SystemExit(0)
if args[:3] == ["api", "--method", "GET"]:
    endpoint = args[-1]
    if endpoint == "repos/acme/widget":
        print(json.dumps({"full_name": "acme/widget"}))
        raise SystemExit(0)
    if endpoint.startswith("repos/acme/widget/issues?"):
        print(json.dumps([[
            {
                "number": 11,
                "title": "Implement widget",
                "state": "open",
                "created_at": "2026-10-01T10:00:00Z",
                "updated_at": "2026-10-02T10:00:00Z",
                "labels": [{"name": "type:feature"}, {"name": "resource:small"}],
                "milestone": {"title": "M3.0a"}
            }
        ]]))
        raise SystemExit(0)
print("unsupported: " + " ".join(args), file=sys.stderr)
raise SystemExit(2)
'''


def make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@example.com"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "Test"], check=True)
    (repo / "pyproject.toml").write_text("[project]\nname='demo'\nversion='0.1'\n")
    (repo / "README.md").write_text("# Demo\n")
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "baseline"], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "remote", "add", "origin", "git@github.com:acme/widget.git"],
        check=True,
    )
    return repo


def fake_gh(tmp_path: Path) -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    gh = bin_dir / "gh"
    gh.write_text(FAKE_GH)
    gh.chmod(gh.stat().st_mode | stat.S_IEXEC)
    return bin_dir


def test_inspection_and_adoption_pin_github_repository(tmp_path: Path, monkeypatch):
    repo = make_repo(tmp_path)
    monkeypatch.setenv("PROJECTCTL_HOME", str(tmp_path / "home"))

    inspection = inspect_repository(repo)
    assert inspection.github_repository == "acme/widget"
    assert inspection.detected_task_systems == ["github"]

    plan = plan_adoption(inspection, task_store_provider="github")
    assert plan.task_store_repository == "acme/widget"
    assert "task_store_repository" not in plan.unresolved_decisions

    result = runner.invoke(
        app,
        [
            "init",
            str(repo),
            "--non-interactive",
            "--yes",
            "--task-store",
            "github",
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    config = load_project_config(repo)
    assert config.task_store.provider == "github"
    assert config.task_store.repository == "acme/widget"


def test_github_provider_without_repository_identity_requires_decision(tmp_path: Path):
    repo = make_repo(tmp_path)
    subprocess.run(["git", "-C", str(repo), "remote", "remove", "origin"], check=True)
    inspection = inspect_repository(repo)
    plan = plan_adoption(inspection, task_store_provider="github")
    assert plan.task_store_repository is None
    assert "task_store_repository" in plan.unresolved_decisions


def test_tasks_cli_reads_github_but_speckit_import_refuses_parallel_store(
    tmp_path: Path, monkeypatch
):
    repo = make_repo(tmp_path)
    monkeypatch.setenv("PROJECTCTL_HOME", str(tmp_path / "home"))
    result = runner.invoke(
        app,
        [
            "init",
            str(repo),
            "--non-interactive",
            "--yes",
            "--task-store",
            "github",
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output

    bin_dir = fake_gh(tmp_path)
    monkeypatch.setenv("PATH", str(bin_dir) + os.pathsep + os.environ.get("PATH", ""))

    tasks = runner.invoke(app, ["tasks", "--project", str(repo), "--json"])
    assert tasks.exit_code == 0, tasks.output
    payload = json.loads(tasks.output)
    assert payload["provider"] == "github"
    assert [task["id"] for task in payload["tasks"]] == ["gh-11"]

    source = repo / "specs" / "demo" / "tasks.md"
    source.parent.mkdir(parents=True)
    source.write_text("- [ ] T001 Do work\n")
    imported = runner.invoke(
        app,
        ["import-tasks", str(source), "--project", str(repo), "--dry-run"],
    )
    assert imported.exit_code == 12
    assert "refusing to create a parallel tracker" in imported.output


def test_doctor_reports_github_reader_as_read_only_warning(tmp_path: Path, monkeypatch):
    repo = make_repo(tmp_path)
    monkeypatch.setenv("PROJECTCTL_HOME", str(tmp_path / "home"))
    assert runner.invoke(
        app,
        [
            "init",
            str(repo),
            "--non-interactive",
            "--yes",
            "--task-store",
            "github",
            "--json",
        ],
    ).exit_code == 0

    bin_dir = fake_gh(tmp_path)
    monkeypatch.setenv("PATH", str(bin_dir) + os.pathsep + os.environ.get("PATH", ""))
    report = runner.invoke(app, ["doctor", "--project", str(repo), "--json"])
    payload = json.loads(report.output)
    task_store = next(item for item in payload["checks"] if item["check_id"] == "task_store")
    assert task_store["status"] == "warn"
    assert "read-only" in task_store["summary"]
