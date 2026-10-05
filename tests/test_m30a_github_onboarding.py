import json
import os
import stat
import subprocess
from pathlib import Path

import yaml
import pytest
from typer.testing import CliRunner

from projectctl.cli.app import app
from projectctl.core.errors import DigestMismatchError, RepositoryContractError
from projectctl.project.adoption import apply_adoption, plan_adoption
from projectctl.project.inspection import inspect_repository
from projectctl.project.loader import load_project_config

runner = CliRunner()

FAKE_GH = r'''#!/usr/bin/env python3
import json, sys
args = sys.argv[1:]

def included(payload, *, etag='"test-v1"'):
    print("HTTP/2.0 200 OK")
    print("etag: " + etag)
    print()
    print(json.dumps(payload))

if args == ["--version"]:
    print("gh version 2.99.0")
    raise SystemExit(0)
if args[:5] == ["api", "--hostname", "github.com", "--method", "GET"]:
    endpoint = args[-1]
    if endpoint == "repos/acme/widget":
        included({"full_name": "acme/widget"}, etag='"repo-v1"')
        raise SystemExit(0)
    if endpoint.endswith("/dependencies/blocked_by?per_page=100"):
        included([], etag='"blocked-empty"')
        raise SystemExit(0)
    if endpoint.endswith("/sub_issues?per_page=100"):
        included([], etag='"sub-empty"')
        raise SystemExit(0)
    if endpoint.startswith("repos/acme/widget/issues?"):
        included([
            {
                "number": 11,
                "title": "Implement widget",
                "state": "open",
                "created_at": "2026-10-01T10:00:00Z",
                "updated_at": "2026-10-02T10:00:00Z",
                "labels": [{"name": "type:feature"}, {"name": "resource:small"}],
                "milestone": {"title": "M3.0a"}
            }
        ], etag='"issues-v1"')
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
    assert config.schema_version == 5
    assert config.task_store.team is None
    assert config.task_store.cache_max_age_seconds == 30
    assert config.code_transport.mode == "git_remote"
    assert config.code_transport.remote_name == "origin"
    assert config.code_transport.remote_identity == "github.com/acme/widget"


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


def test_doctor_reports_github_claim_transport_without_claiming(tmp_path: Path, monkeypatch):
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

    class FakeLease:
        def __init__(self, root, *, remote_name="origin"):
            self.root = root
            self.remote_name = remote_name

        def remote_url(self):
            return "git@github.com:acme/widget.git"

        def probe_readable(self):
            return "a" * 40

    monkeypatch.setattr("projectctl.doctor.checks.RemoteRefLease", FakeLease)

    report = runner.invoke(app, ["doctor", "--project", str(repo), "--json"])
    assert report.exit_code == 0, report.output
    payload = json.loads(report.output)
    task_store = next(item for item in payload["checks"] if item["check_id"] == "task_store")
    assert task_store["status"] == "warn"
    assert "adapter-complete" in task_store["summary"]
    assert any("publication" in detail for detail in task_store["details"])
    assert "remote write policy is verified only during real claim/publication" in task_store["summary"]


def test_scheduler_can_select_normalized_github_issue(tmp_path: Path, monkeypatch):
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

    provider = runner.invoke(
        app,
        ["quota", "provider", "--project", str(repo), "--set", "manual"],
    )
    assert provider.exit_code == 0, provider.output
    quota = runner.invoke(
        app,
        [
            "quota",
            "set",
            "--project",
            str(repo),
            "--five-hour",
            "90%",
            "--weekly",
            "90%",
        ],
    )
    assert quota.exit_code == 0, quota.output

    decision = runner.invoke(
        app,
        ["next", "--project", str(repo), "--json"],
    )
    assert decision.exit_code == 0, decision.output
    payload = json.loads(decision.output)
    assert payload["selected_task_id"] == "gh-11"


def test_adoption_rejects_invalid_or_irrelevant_repository_override(tmp_path: Path):
    repo = make_repo(tmp_path)
    inspection = inspect_repository(repo)

    with pytest.raises(RepositoryContractError, match="owner/repository"):
        plan_adoption(
            inspection,
            task_store_provider="github",
            task_store_repository="https://github.com/acme/widget",
        )

    with pytest.raises(RepositoryContractError, match="only supported"):
        plan_adoption(
            inspection,
            task_store_provider="beads",
            task_store_repository="acme/widget",
        )


def test_origin_change_invalidates_github_adoption_plan(tmp_path: Path, monkeypatch):
    repo = make_repo(tmp_path)
    monkeypatch.setenv("PROJECTCTL_HOME", str(tmp_path / "home"))
    inspection = inspect_repository(repo)
    plan = plan_adoption(inspection, task_store_provider="github")

    subprocess.run(
        ["git", "-C", str(repo), "remote", "set-url", "origin", "git@github.com:acme/other.git"],
        check=True,
    )

    with pytest.raises(DigestMismatchError):
        apply_adoption(plan)
