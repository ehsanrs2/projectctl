from __future__ import annotations

import fnmatch
import hashlib
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from projectctl.core.digest import digest
from projectctl.core.enums import WorkerStrategyKind
from projectctl.core.errors import VerificationError
from projectctl.core.paths import validate_repo_path
from projectctl.schemas.verification import DiffPolicy

SYSTEM_PROTECTED_PATHS = (
    ".projectctl",
    ".projectctl/**",
    ".gitmodules",
    "evidence/**",
    "docs/generated/**",
    "AGENTS.md",
    "**/AGENTS.md",
    "AGENTS.override.md",
    "**/AGENTS.override.md",
    "docs/PROJECT_STATE.yaml",
    "docs/PROJECTCTL_BLUEPRINT.md",
    "specs/**",
    "docs/decisions/**",
    "projectctl.verification.yaml",
    "projectctl.scope.yaml",
    "projectctl.parallel.yaml",
)


@dataclass(frozen=True)
class WorkspaceInspection:
    changed_paths: list[str]
    state_digest: str
    diff_digest: str
    violations: list[str]


def _git_bytes(root: Path, *args: str, check: bool = True) -> bytes:
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        check=False,
    )
    if check and result.returncode != 0:
        message = (result.stderr or result.stdout or b"git error").decode(
            "utf-8", errors="replace"
        ).strip()
        raise VerificationError(f"git {' '.join(args)} failed: {message}")
    return result.stdout


def _nul_paths(data: bytes) -> set[str]:
    result: set[str] = set()
    for raw in data.split(b"\0"):
        if not raw:
            continue
        value = os.fsdecode(raw)
        if any(0xD800 <= ord(ch) <= 0xDFFF for ch in value):
            raise VerificationError("Git path is not valid UTF-8 and cannot be audited safely.")
        try:
            result.add(validate_repo_path(value))
        except ValueError as exc:
            raise VerificationError(f"Unsafe changed path {value!r}: {exc}") from exc
    return result


def changed_paths(worktree: Path) -> list[str]:
    paths = set()
    paths |= _nul_paths(
        _git_bytes(worktree, "diff", "--no-renames", "--name-only", "-z", "HEAD", "--")
    )
    paths |= _nul_paths(
        _git_bytes(
            worktree,
            "diff",
            "--cached",
            "--no-renames",
            "--name-only",
            "-z",
            "HEAD",
            "--",
        )
    )
    paths |= _nul_paths(
        _git_bytes(worktree, "ls-files", "--others", "--exclude-standard", "-z", "--")
    )
    return sorted(paths)


def _matches(path: str, patterns: tuple[str, ...] | list[str]) -> bool:
    return any(fnmatch.fnmatchcase(path, pattern) for pattern in patterns)


def _record_for_path(worktree: Path, relative: str) -> tuple[dict, list[str]]:
    path = worktree / relative
    violations: list[str] = []
    if not path.exists() and not path.is_symlink():
        return {"path": relative, "kind": "deleted"}, violations

    try:
        stat = path.lstat()
    except OSError as exc:
        raise VerificationError(f"Could not inspect changed path {relative}: {exc}") from exc

    if path.is_symlink():
        target = os.readlink(path)
        try:
            resolved = path.resolve(strict=False)
            if not resolved.is_relative_to(worktree.resolve()):
                violations.append(f"symlink escapes worktree: {relative} -> {target}")
        except OSError:
            violations.append(f"unresolvable symlink: {relative} -> {target}")
        return {
            "path": relative,
            "kind": "symlink",
            "target": target,
            "mode": stat.st_mode & 0o7777,
        }, violations

    if path.is_dir():
        violations.append(f"directory/gitlink change is unsupported: {relative}")
        return {
            "path": relative,
            "kind": "directory",
            "mode": stat.st_mode & 0o7777,
        }, violations

    if not path.is_file():
        violations.append(f"special-file change is unsupported: {relative}")
        return {
            "path": relative,
            "kind": "special",
            "mode": stat.st_mode & 0o7777,
        }, violations

    content = path.read_bytes()
    return {
        "path": relative,
        "kind": "file",
        "mode": stat.st_mode & 0o7777,
        "size": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
    }, violations


def inspect_workspace(
    worktree: Path,
    *,
    policy: DiffPolicy,
    strategy: WorkerStrategyKind,
) -> WorkspaceInspection:
    paths = changed_paths(worktree)
    violations: list[str] = []

    if len(paths) > policy.max_changed_paths:
        violations.append(
            f"changed path count {len(paths)} exceeds limit {policy.max_changed_paths}"
        )

    if strategy == WorkerStrategyKind.REVIEW:
        if paths:
            violations.append("review strategy must not modify the worktree")
    elif policy.require_changes and not paths:
        violations.append("worker produced no tracked or untracked changes")

    protected_patterns = tuple(SYSTEM_PROTECTED_PATHS) + tuple(policy.protected_paths)
    records: list[dict] = []
    for relative in paths:
        if _matches(relative, protected_patterns):
            violations.append(f"protected path modified: {relative}")
        record, path_violations = _record_for_path(worktree, relative)
        if record["kind"] == "symlink" and not policy.allow_symlink_changes:
            violations.append(f"symlink changes are not allowed: {relative}")
        records.append(record)
        violations.extend(path_violations)

    payload = {"paths": records}
    state_digest = digest(payload)
    return WorkspaceInspection(
        changed_paths=paths,
        state_digest=state_digest,
        diff_digest=digest({"diff": records}),
        violations=sorted(set(violations)),
    )


def committed_diff_digest(worktree: Path, base_commit: str, candidate_commit: str) -> str:
    patch = _git_bytes(
        worktree,
        "diff",
        "--binary",
        "--no-ext-diff",
        "--full-index",
        base_commit,
        candidate_commit,
        "--",
    )
    return "sha256:" + hashlib.sha256(patch).hexdigest()
