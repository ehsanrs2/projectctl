import subprocess
from pathlib import Path

import yaml

from projectctl.integrations.task_authority import require_task_authority_execution_ready
from projectctl.project.bootstrap import initialize_project
from projectctl.project.loader import load_project_config


def test_github_execution_gate_is_open_after_publication_lifecycle_support(tmp_path: Path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@example.com"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "Test"], check=True)
    monkeypatch.setenv("PROJECTCTL_HOME", str(tmp_path / "home"))
    initialize_project(repo)

    config_path = repo / ".projectctl" / "config.yaml"
    raw = yaml.safe_load(config_path.read_text())
    raw["task_store"] = {"provider": "github", "repository": "acme/widget"}
    config_path.write_text(yaml.safe_dump(raw, sort_keys=False))

    require_task_authority_execution_ready(repo)

    # Static adapter readiness must not require invoking GitHub CLI or creating
    # run state. Runtime/provider health is checked separately by doctor and
    # during the actual claim/publication operations.
    runs_dir = repo / ".projectctl" / "runs"
    assert list(runs_dir.iterdir()) == []
