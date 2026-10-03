import json
import os
import subprocess
from pathlib import Path

from typer.testing import CliRunner

from projectctl.cli.app import app
from projectctl.project.loader import load_project_config
from projectctl.storage.sqlite import (APPLICATION_ID, GLOBAL_STATE_DB_VERSION, PROJECT_STATE_DB_VERSION, TELEMETRY_DB_VERSION, inspect_db)

runner = CliRunner()


def make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "demo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    return repo


def test_init_is_idempotent(tmp_path: Path, monkeypatch):
    repo = make_repo(tmp_path)
    home = tmp_path / "home"
    monkeypatch.setenv("PROJECTCTL_HOME", str(home))

    first = runner.invoke(app, ["init", str(repo), "--json"])
    assert first.exit_code == 0, first.output
    second = runner.invoke(app, ["init", str(repo), "--json"])
    assert second.exit_code == 0, second.output

    cfg = load_project_config(repo)
    assert cfg.project.id == "demo"
    assert (repo / "docs/PROJECT.md").exists()
    assert (repo / "docs/PROJECT_STATE.yaml").exists()

    expected = {
        repo / ".projectctl/state.sqlite": PROJECT_STATE_DB_VERSION,
        repo / ".projectctl/telemetry.sqlite": TELEMETRY_DB_VERSION,
        home / "state.sqlite": GLOBAL_STATE_DB_VERSION,
    }
    for db, expected_version in expected.items():
        app_id, version = inspect_db(db)
        assert app_id == APPLICATION_ID
        assert version == expected_version


def test_init_preserves_human_project_file(tmp_path: Path, monkeypatch):
    repo = make_repo(tmp_path)
    (repo / "docs").mkdir()
    original = "# My Project\n"
    (repo / "docs/PROJECT.md").write_text(original)
    monkeypatch.setenv("PROJECTCTL_HOME", str(tmp_path / "home"))
    result = runner.invoke(app, ["init", str(repo)])
    assert result.exit_code == 0
    assert (repo / "docs/PROJECT.md").read_text() == original


def test_doctor_json_is_machine_readable(tmp_path: Path, monkeypatch):
    repo = make_repo(tmp_path)
    monkeypatch.setenv("PROJECTCTL_HOME", str(tmp_path / "home"))
    assert runner.invoke(app, ["init", str(repo)]).exit_code == 0
    result = runner.invoke(app, ["doctor", "--project", str(repo), "--json"])
    # Beads may not exist in the test environment; JSON must still be valid.
    payload = json.loads(result.output)
    assert "checks" in payload
    assert any(c["check_id"] == "repository" for c in payload["checks"])


def test_init_rejects_invalid_existing_config(tmp_path: Path, monkeypatch):
    repo = make_repo(tmp_path)
    ctl = repo / ".projectctl"
    ctl.mkdir()
    (ctl / "config.yaml").write_text("schema_kind: wrong\nschema_version: 1\nproject:\n  id: demo\n")
    monkeypatch.setenv("PROJECTCTL_HOME", str(tmp_path / "home"))
    result = runner.invoke(app, ["init", str(repo)])
    assert result.exit_code != 0


def test_global_database_has_global_tables(tmp_path: Path, monkeypatch):
    repo = make_repo(tmp_path)
    home = tmp_path / "home"
    monkeypatch.setenv("PROJECTCTL_HOME", str(home))
    assert runner.invoke(app, ["init", str(repo)]).exit_code == 0
    import sqlite3
    conn = sqlite3.connect(home / "state.sqlite")
    try:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        conn.close()
    assert {"accounts", "quota_observations", "project_registry", "provider_status"}.issubset(tables)
