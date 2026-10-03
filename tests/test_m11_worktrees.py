import sqlite3

import pytest
import subprocess
from pathlib import Path

from projectctl.core.errors import WorktreeError
from projectctl.git.worktrees import WorktreeManager, resolve_commit
from projectctl.storage.sqlite import initialize_project_state_db


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "config", "user.email", "test@example.com")
    git(repo, "config", "user.name", "Test")
    (repo / "app.py").write_text("print('base')\n", encoding="utf-8")
    git(repo, "add", "app.py")
    git(repo, "commit", "-q", "-m", "base")

    ctl = repo / ".projectctl"
    ctl.mkdir()
    initialize_project_state_db(ctl / "state.sqlite")
    conn = sqlite3.connect(ctl / "state.sqlite")
    try:
        conn.execute(
            "INSERT INTO project_metadata(key, value) VALUES (?, ?)",
            ("project_instance_id", "instance-1"),
        )
        conn.commit()
    finally:
        conn.close()
    return repo


def test_worktree_is_outside_repository_and_pinned_to_base(tmp_path: Path):
    repo = make_repo(tmp_path)
    home = tmp_path / "home"
    base = resolve_commit(repo, "HEAD")
    manager = WorktreeManager(repo, home=home)

    info = manager.create(
        worktree_id="run-1",
        branch_name="projectctl/run/run-1",
        base_commit=base,
    )
    assert info.path.is_relative_to(home / "worktrees" / "instance-1")
    assert not info.path.is_relative_to(repo)
    assert resolve_commit(info.path, "HEAD") == base

    (info.path / "app.py").write_text("print('candidate')\n", encoding="utf-8")
    assert (repo / "app.py").read_text(encoding="utf-8") == "print('base')\n"

    manager.remove(
        worktree_id="run-1",
        branch_name="projectctl/run/run-1",
        force=True,
    )
    assert not info.path.exists()
    assert subprocess.run(
        ["git", "-C", str(repo), "show-ref", "--verify", "--quiet", "refs/heads/projectctl/run/run-1"],
        check=False,
    ).returncode != 0



def test_worktree_storage_rejects_projectctl_home_inside_repo(tmp_path: Path):
    repo = make_repo(tmp_path)
    with pytest.raises(WorktreeError, match="outside and independent"):
        WorktreeManager(repo, home=repo / ".projectctl-home")
