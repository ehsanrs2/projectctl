import subprocess
from pathlib import Path

import pytest
import yaml

from projectctl.application.execution import prepare_next_run
from projectctl.core.errors import ConfigurationError
from projectctl.project.bootstrap import initialize_project
from projectctl.project.loader import load_project_config


def test_github_reader_cannot_prepare_execution_run(tmp_path: Path, monkeypatch):
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

    with pytest.raises(ConfigurationError, match="read-only in M3.0a"):
        prepare_next_run(repo)

    runs_dir = repo / ".projectctl" / "runs"
    assert list(runs_dir.iterdir()) == []
