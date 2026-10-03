from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from projectctl.core.errors import WorktreeError
from projectctl.project.bootstrap import projectctl_home
from projectctl.project.identity import project_instance_id


_SAFE_ID = re.compile(r"^[A-Za-z0-9._-]+$")


@dataclass(frozen=True)
class WorktreeInfo:
    worktree_id: str
    path: Path
    branch_name: str
    base_commit: str


def _git(project_root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["git", "-C", str(project_root), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    if check and result.returncode != 0:
        message = (result.stderr or result.stdout or "unknown git error").strip()
        raise WorktreeError(f"git {' '.join(args)} failed: {message}")
    return result


def resolve_commit(project_root: Path, ref: str) -> str:
    result = _git(project_root, "rev-parse", "--verify", f"{ref}^{{commit}}")
    value = result.stdout.strip()
    if not value:
        raise WorktreeError(f"Git ref did not resolve to a commit: {ref}")
    return value


def current_branch(project_root: Path) -> str:
    result = _git(project_root, "symbolic-ref", "--quiet", "--short", "HEAD", check=False)
    if result.returncode != 0 or not result.stdout.strip():
        raise WorktreeError(
            "Current repository is in detached HEAD state; specify an integration target explicitly."
        )
    return result.stdout.strip()


class WorktreeManager:
    def __init__(self, project_root: Path, *, home: Path | None = None):
        self.project_root = project_root.resolve()
        self.home = (home or projectctl_home()).resolve()
        instance = project_instance_id(self.project_root)
        self.root = (self.home / "worktrees" / instance).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def path_for(self, worktree_id: str) -> Path:
        if not _SAFE_ID.fullmatch(worktree_id):
            raise WorktreeError(f"Unsafe worktree id: {worktree_id!r}")
        path = (self.root / worktree_id).resolve()
        if not path.is_relative_to(self.root):
            raise WorktreeError(f"Worktree path escapes ProjectCTL worktree root: {path}")
        return path

    def create(
        self,
        *,
        worktree_id: str,
        branch_name: str,
        base_commit: str,
    ) -> WorktreeInfo:
        path = self.path_for(worktree_id)
        resolved_base = resolve_commit(self.project_root, base_commit)
        if path.exists():
            raise WorktreeError(f"Worktree path already exists: {path}")

        branch_check = _git(
            self.project_root,
            "show-ref",
            "--verify",
            "--quiet",
            f"refs/heads/{branch_name}",
            check=False,
        )
        if branch_check.returncode == 0:
            raise WorktreeError(f"Run branch already exists: {branch_name}")

        try:
            _git(
                self.project_root,
                "worktree",
                "add",
                "-b",
                branch_name,
                str(path),
                resolved_base,
            )
            actual = resolve_commit(path, "HEAD")
            if actual != resolved_base:
                raise WorktreeError(
                    f"Created worktree HEAD {actual} does not match requested base {resolved_base}."
                )
        except Exception:
            _git(self.project_root, "worktree", "remove", "--force", str(path), check=False)
            if path.exists():
                shutil.rmtree(path, ignore_errors=True)
            _git(self.project_root, "branch", "-D", branch_name, check=False)
            raise

        return WorktreeInfo(
            worktree_id=worktree_id,
            path=path,
            branch_name=branch_name,
            base_commit=resolved_base,
        )

    def remove(self, *, worktree_id: str, branch_name: str, force: bool = False) -> None:
        path = self.path_for(worktree_id)
        args = ["worktree", "remove"]
        if force:
            args.append("--force")
        args.append(str(path))
        result = _git(self.project_root, *args, check=False)
        if result.returncode != 0 and path.exists():
            message = (result.stderr or result.stdout or "unknown git error").strip()
            raise WorktreeError(f"Could not remove worktree {path}: {message}")
        _git(self.project_root, "worktree", "prune", check=False)
        # Branch deletion is intentionally separate from integration branches.
        if branch_name.startswith("projectctl/run/"):
            delete_args = ["branch", "-D" if force else "-d", branch_name]
            result = _git(self.project_root, *delete_args, check=False)
            if result.returncode != 0 and force:
                message = (result.stderr or result.stdout or "unknown git error").strip()
                raise WorktreeError(f"Could not delete run branch {branch_name}: {message}")
