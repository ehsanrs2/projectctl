import os
import subprocess
from pathlib import Path

from projectctl.core.enums import WorkerStrategyKind
from projectctl.schemas.verification import DiffPolicy
from projectctl.verification.diff import inspect_workspace


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
    (repo / "app.py").write_text("value = 1\n", encoding="utf-8")
    (repo / "AGENTS.md").write_text("rules\n", encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "base")
    return repo


def test_diff_policy_detects_normal_change(tmp_path: Path):
    repo = make_repo(tmp_path)
    (repo / "app.py").write_text("value = 2\n", encoding="utf-8")
    inspection = inspect_workspace(
        repo,
        policy=DiffPolicy(),
        strategy=WorkerStrategyKind.DIRECT,
    )
    assert inspection.changed_paths == ["app.py"]
    assert inspection.violations == []


def test_diff_policy_blocks_human_authority_file(tmp_path: Path):
    repo = make_repo(tmp_path)
    (repo / "AGENTS.md").write_text("changed rules\n", encoding="utf-8")
    inspection = inspect_workspace(
        repo,
        policy=DiffPolicy(),
        strategy=WorkerStrategyKind.DIRECT,
    )
    assert any("protected path modified: AGENTS.md" in v for v in inspection.violations)


def test_review_strategy_requires_clean_worktree(tmp_path: Path):
    repo = make_repo(tmp_path)
    clean = inspect_workspace(
        repo,
        policy=DiffPolicy(),
        strategy=WorkerStrategyKind.REVIEW,
    )
    assert clean.violations == []

    (repo / "app.py").write_text("value = 3\n", encoding="utf-8")
    dirty = inspect_workspace(
        repo,
        policy=DiffPolicy(),
        strategy=WorkerStrategyKind.REVIEW,
    )
    assert "review strategy must not modify the worktree" in dirty.violations


def test_symlink_changes_fail_closed(tmp_path: Path):
    if not hasattr(os, "symlink"):
        return
    repo = make_repo(tmp_path)
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    os.symlink(outside, repo / "escape")
    inspection = inspect_workspace(
        repo,
        policy=DiffPolicy(),
        strategy=WorkerStrategyKind.DIRECT,
    )
    assert any("symlink changes are not allowed" in v for v in inspection.violations)
    assert any("symlink escapes worktree" in v for v in inspection.violations)



def test_rename_cannot_hide_protected_source_path(tmp_path: Path):
    repo = make_repo(tmp_path)
    git(repo, "mv", "AGENTS.md", "moved-rules.md")
    inspection = inspect_workspace(
        repo,
        policy=DiffPolicy(),
        strategy=WorkerStrategyKind.DIRECT,
    )
    assert "AGENTS.md" in inspection.changed_paths
    assert "moved-rules.md" in inspection.changed_paths
    assert any("protected path modified: AGENTS.md" in v for v in inspection.violations)
