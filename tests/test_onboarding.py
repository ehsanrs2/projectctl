import json
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from projectctl.cli.app import app
from projectctl.core.errors import DigestMismatchError
from projectctl.project.adoption import apply_adoption, plan_adoption
from projectctl.project.inspection import inspect_repository
from projectctl.project.loader import load_project_config

runner = CliRunner()


def make_repo(tmp_path: Path, *, commit: bool = False) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@example.com"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "Test"], check=True)
    if commit:
        (repo / ".gitkeep").write_text("")
        subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
        subprocess.run(["git", "-C", str(repo), "commit", "-qm", "baseline"], check=True)
    return repo


def commit_all(repo: Path, message: str = "baseline") -> None:
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", message], check=True)


def test_inspect_is_read_only_for_brownfield(tmp_path: Path):
    repo = make_repo(tmp_path)
    (repo / "pyproject.toml").write_text("[project]\nname='demo'\nversion='0.1'\n")
    (repo / "README.md").write_text("# Existing\n")
    (repo / "AGENTS.md").write_text("Existing instructions\n")
    before = sorted(p.relative_to(repo).as_posix() for p in repo.rglob("*") if ".git/" not in p.as_posix())

    inspection = inspect_repository(repo)

    after = sorted(p.relative_to(repo).as_posix() for p in repo.rglob("*") if ".git/" not in p.as_posix())
    assert inspection.classification == "existing_unmanaged"
    assert before == after
    assert not (repo / ".projectctl").exists()
    assert any(a.path == "AGENTS.md" for a in inspection.assets)


def test_init_brownfield_non_interactive_requires_approval(tmp_path: Path, monkeypatch):
    repo = make_repo(tmp_path)
    (repo / "pyproject.toml").write_text("[project]\nname='demo'\nversion='0.1'\n")
    (repo / "README.md").write_text("# Existing\n")
    commit_all(repo)
    monkeypatch.setenv("PROJECTCTL_HOME", str(tmp_path / "home"))

    result = runner.invoke(app, ["init", str(repo), "--non-interactive"])
    assert result.exit_code == 16
    payload = json.loads(result.output)
    assert payload["status"] == "interaction_required"
    assert not (repo / ".projectctl").exists()


def test_init_interactive_adopts_without_touching_agents(tmp_path: Path, monkeypatch):
    repo = make_repo(tmp_path)
    (repo / "pyproject.toml").write_text("[project]\nname='demo'\nversion='0.1'\n")
    (repo / "README.md").write_text("# Existing\n")
    original_agents = "# Existing agent rules\nNever rewrite me.\n"
    (repo / "AGENTS.md").write_text(original_agents)
    (repo / "docs").mkdir()
    (repo / "docs" / "roadmap.md").write_text("# Existing Roadmap\n")
    commit_all(repo)
    monkeypatch.setenv("PROJECTCTL_HOME", str(tmp_path / "home"))

    # Continue adoption, choose Beads, approve final application.
    result = runner.invoke(app, ["init", str(repo)], input="y\n1\ny\n")
    assert result.exit_code == 0, result.output
    assert (repo / "AGENTS.md").read_text() == original_agents
    assert not (repo / "docs" / "PROJECT.md").exists()
    assert (repo / ".projectctl" / "adoption.yaml").exists()
    config = load_project_config(repo)
    assert config.knowledge.project_overview.sources == ["README.md"]
    assert config.knowledge.roadmap.sources == ["docs/roadmap.md"]
    assert config.task_store.provider == "beads"


def test_adopt_dry_run_does_not_mutate(tmp_path: Path, monkeypatch):
    repo = make_repo(tmp_path)
    (repo / "package.json").write_text('{"name":"demo"}\n')
    (repo / "README.md").write_text("# Existing\n")
    commit_all(repo)
    monkeypatch.setenv("PROJECTCTL_HOME", str(tmp_path / "home"))

    result = runner.invoke(app, ["adopt", str(repo), "--dry-run", "--task-store", "beads", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["schema_kind"] == "projectctl.adoption_plan"
    assert not (repo / ".projectctl").exists()


def test_dirty_tree_blocks_noninteractive_apply_without_override(tmp_path: Path, monkeypatch):
    repo = make_repo(tmp_path)
    (repo / "pyproject.toml").write_text("[project]\nname='demo'\nversion='0.1'\n")
    (repo / "README.md").write_text("# Existing\n")
    commit_all(repo)
    (repo / "README.md").write_text("# Modified\n")
    monkeypatch.setenv("PROJECTCTL_HOME", str(tmp_path / "home"))

    result = runner.invoke(app, [
        "init", str(repo), "--non-interactive", "--yes", "--task-store", "beads"
    ])
    assert result.exit_code == 16
    assert not (repo / ".projectctl").exists()


def test_explicit_configure_later_is_allowed(tmp_path: Path, monkeypatch):
    repo = make_repo(tmp_path)
    (repo / "pyproject.toml").write_text("[project]\nname='demo'\nversion='0.1'\n")
    (repo / "README.md").write_text("# Existing\n")
    commit_all(repo)
    monkeypatch.setenv("PROJECTCTL_HOME", str(tmp_path / "home"))

    result = runner.invoke(app, [
        "init", str(repo), "--non-interactive", "--yes", "--task-store", "unresolved", "--json"
    ])
    assert result.exit_code == 0, result.output
    assert load_project_config(repo).task_store.provider == "unresolved"


def test_stale_adoption_plan_is_rejected(tmp_path: Path, monkeypatch):
    repo = make_repo(tmp_path)
    (repo / "pyproject.toml").write_text("[project]\nname='demo'\nversion='0.1'\n")
    (repo / "README.md").write_text("# Existing\n")
    commit_all(repo)
    monkeypatch.setenv("PROJECTCTL_HOME", str(tmp_path / "home"))

    inspection = inspect_repository(repo)
    plan = plan_adoption(inspection, task_store_provider="beads")
    (repo / "README.md").write_text("# Changed after plan\n")
    with pytest.raises(DigestMismatchError):
        apply_adoption(plan, allow_dirty=True)
    assert not (repo / ".projectctl").exists()


def test_managed_invalid_is_not_reinitialized(tmp_path: Path, monkeypatch):
    repo = make_repo(tmp_path)
    ctl = repo / ".projectctl"
    ctl.mkdir()
    (ctl / "config.yaml").write_text("not: a-valid-projectctl-config\n")
    monkeypatch.setenv("PROJECTCTL_HOME", str(tmp_path / "home"))

    result = runner.invoke(app, ["init", str(repo)])
    assert result.exit_code == 11
    assert "invalid" in result.output.lower()

def test_unsafe_symlink_is_reported_and_not_adopted(tmp_path: Path, monkeypatch):
    repo = make_repo(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "README.md").write_text("outside\n")
    (repo / "pyproject.toml").write_text("[project]\nname='demo'\nversion='0.1'\n")
    (repo / "README.md").symlink_to(outside / "README.md")
    commit_all(repo)
    monkeypatch.setenv("PROJECTCTL_HOME", str(tmp_path / "home"))

    inspection = inspect_repository(repo)
    assert any(c.startswith("unsafe_path:README.md") for c in inspection.conflicts)
    result = runner.invoke(app, ["adopt", str(repo), "--dry-run", "--task-store", "beads"])
    assert result.exit_code == 11
    assert not (repo / ".projectctl").exists()


def test_apply_rolls_back_local_artifacts_when_global_registration_fails(tmp_path: Path, monkeypatch):
    import projectctl.project.adoption as adoption_module

    repo = make_repo(tmp_path)
    (repo / "pyproject.toml").write_text("[project]\nname='demo'\nversion='0.1'\n")
    (repo / "README.md").write_text("# Existing\n")
    commit_all(repo)
    monkeypatch.setenv("PROJECTCTL_HOME", str(tmp_path / "home"))

    plan = plan_adoption(inspect_repository(repo), task_store_provider="beads")

    def fail_register(*args, **kwargs):
        raise RuntimeError("simulated global registry failure")

    monkeypatch.setattr(adoption_module, "_register_global", fail_register)
    with pytest.raises(RuntimeError, match="simulated"):
        apply_adoption(plan)

    assert not (repo / ".projectctl").exists()
    assert not (repo / "evidence").exists()
    assert not (repo / "docs" / "generated").exists()
