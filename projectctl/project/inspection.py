from __future__ import annotations

import os
import subprocess
from pathlib import Path

from projectctl.core.digest import digest
from projectctl.core.errors import UnsafePathError
from projectctl.core.paths import resolve_inside_repo
from projectctl.project.loader import load_project_config
from projectctl.project.root import git_root
from projectctl.schemas.onboarding import DetectedAsset, KnowledgeBinding, ProjectInspection

PRUNE_DIRS = {
    ".git", ".projectctl", ".venv", "venv", "node_modules", "dist", "build",
    "target", ".mypy_cache", ".pytest_cache", "__pycache__",
}

BUILD_MANIFESTS = {
    "pyproject.toml", "setup.py", "setup.cfg", "requirements.txt", "package.json",
    "Cargo.toml", "go.mod", "pom.xml", "build.gradle", "build.gradle.kts",
}


def _git_value(root: Path, *args: str) -> str | None:
    proc = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        return None
    value = proc.stdout.strip()
    return value or None


def _status_text(root: Path) -> str:
    proc = subprocess.run(
        ["git", "-C", str(root), "status", "--porcelain=v1", "--untracked-files=normal"],
        capture_output=True, text=True, check=False,
    )
    return proc.stdout if proc.returncode == 0 else ""


def _dirty(root: Path) -> bool:
    return bool(_status_text(root).strip())


def _walk_agent_files(root: Path) -> list[Path]:
    found: list[Path] = []
    for current, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in PRUNE_DIRS]
        current_path = Path(current)
        for name in files:
            if name in {"AGENTS.md", "AGENTS.override.md"}:
                found.append(current_path / name)
    return sorted(found)


def _rel(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def _asset_if_exists(root: Path, rel: str, kind: str, role: str | None = None) -> DetectedAsset | None:
    p = root / rel
    if not p.exists() and not p.is_symlink():
        return None
    resolve_inside_repo(root, rel, must_exist=p.exists())
    return DetectedAsset(path=rel, kind=kind, role=role)


def _suggest_knowledge_bindings(root: Path) -> list[KnowledgeBinding]:
    candidates: dict[str, list[str]] = {
        "project_overview": ["README.md", "docs/PROJECT.md"],
        "roadmap": ["docs/roadmap.md", "docs/ROADMAP.md", "ROADMAP.md"],
        "constraints": ["CONTRIBUTING.md", "docs/CONSTRAINTS.md", "docs/security.md"],
        "architecture": ["docs/architecture.md", "docs/ARCHITECTURE.md", "architecture"],
        "decisions": ["docs/decisions", "docs/adr", "adr"],
    }
    result: list[KnowledgeBinding] = []
    for role, paths in candidates.items():
        sources: list[str] = []
        for rel in paths:
            path = root / rel
            if not path.exists() and not path.is_symlink():
                continue
            try:
                resolve_inside_repo(root, rel, must_exist=path.exists())
            except UnsafePathError:
                continue
            sources.append(rel)
        if sources:
            result.append(KnowledgeBinding(role=role, sources=sources))
    return result


def _fingerprint_payload(root: Path, assets: list[DetectedAsset], head: str | None, dirty: bool, status_text: str) -> dict:
    file_entries: list[dict[str, str | None]] = []
    for asset in assets:
        path = root / asset.path
        if path.is_file():
            try:
                content_hash = digest(path.read_bytes().hex())
            except OSError:
                content_hash = None
        else:
            content_hash = None
        file_entries.append({"path": asset.path, "kind": asset.kind, "hash": content_hash})
    dirty_entries = []
    for line in status_text.splitlines():
        raw_path = line[3:] if len(line) >= 4 else line
        # Rename records may contain "old -> new"; the destination is what matters for current state.
        rel = raw_path.split(" -> ")[-1].strip()
        path = root / rel
        stat = None
        try:
            st = path.stat()
            stat = {"size": st.st_size, "mtime_ns": st.st_mtime_ns}
        except OSError:
            pass
        dirty_entries.append({"status": line[:2], "path": rel, "stat": stat})
    return {"head": head, "dirty": dirty, "git_status": dirty_entries, "assets": file_entries}


def inspect_repository(target: Path) -> ProjectInspection:
    root = git_root(target.resolve())
    head = _git_value(root, "rev-parse", "HEAD")
    status_text = _status_text(root)
    dirty = bool(status_text.strip())

    conflicts: list[str] = []
    ctl = root / ".projectctl"
    if ctl.exists() or ctl.is_symlink():
        try:
            resolve_inside_repo(root, ".projectctl", must_exist=ctl.exists())
            load_project_config(root)
            classification = "managed_valid"
            confidence = "high"
            score = 100
            notes: list[str] = []
        except Exception as exc:  # inspection must report broken managed installs instead of crashing
            classification = "managed_invalid"
            confidence = "high"
            score = 100
            conflicts.append("invalid_or_unsafe_projectctl_state")
            notes = [f"Existing ProjectCTL state is invalid: {exc}"]
    else:
        classification = "new"
        confidence = "medium"
        score = 0
        notes = []

    assets: list[DetectedAsset] = []

    for p in _walk_agent_files(root):
        rel = _rel(root, p)
        try:
            resolve_inside_repo(root, rel, must_exist=True)
        except UnsafePathError:
            conflicts.append(f"unsafe_path:{rel}")
            continue
        scope = p.parent.relative_to(root).as_posix() or "."
        assets.append(DetectedAsset(path=rel, kind="agent_instruction", role="agent_instructions", scope=None if scope == "." else scope))
        score += 3

    fixed_assets = [
        ("README.md", "knowledge", "project_overview"),
        ("CONTRIBUTING.md", "knowledge", "constraints"),
        ("docs/roadmap.md", "knowledge", "roadmap"),
        ("docs/ROADMAP.md", "knowledge", "roadmap"),
        ("docs/architecture.md", "knowledge", "architecture"),
        ("docs/ARCHITECTURE.md", "knowledge", "architecture"),
        ("docs/decisions", "knowledge", "decisions"),
        ("docs/adr", "knowledge", "decisions"),
        (".agents/skills", "agent_asset", "skills"),
        (".specify", "spec_system", "spec_kit"),
        ("specs", "spec_system", "specs"),
        (".beads", "task_system", "beads"),
        (".github/workflows", "automation", "ci"),
        (".github/ISSUE_TEMPLATE", "task_system", "github_issues_candidate"),
        (".gitlab-ci.yml", "automation", "ci"),
        ("Jenkinsfile", "automation", "ci"),
        (".mcp.json", "agent_asset", "mcp"),
    ]
    seen = {a.path for a in assets}
    for rel, kind, role in fixed_assets:
        try:
            asset = _asset_if_exists(root, rel, kind, role)
        except UnsafePathError:
            conflicts.append(f"unsafe_path:{rel}")
            continue
        if asset and asset.path not in seen:
            assets.append(asset)
            seen.add(asset.path)
            if kind == "task_system":
                score += 3
            elif kind in {"automation", "spec_system", "agent_asset"}:
                score += 2
            elif kind == "knowledge" and role != "project_overview":
                score += 1

    for name in BUILD_MANIFESTS:
        path = root / name
        if path.is_file() or path.is_symlink():
            try:
                resolve_inside_repo(root, name, must_exist=path.exists())
            except UnsafePathError:
                conflicts.append(f"unsafe_path:{name}")
                continue
            if name not in seen:
                assets.append(DetectedAsset(path=name, kind="build_manifest", role="build"))
                seen.add(name)
            score += 3

    for src in ["src", "app", "backend", "frontend", "lib"]:
        path = root / src
        if path.is_dir() or path.is_symlink():
            try:
                resolve_inside_repo(root, src, must_exist=path.exists())
            except UnsafePathError:
                conflicts.append(f"unsafe_path:{src}")
                continue
            if src not in seen:
                assets.append(DetectedAsset(path=src, kind="source_tree", role="source"))
                seen.add(src)
            score += 2

    if not ctl.exists() and not ctl.is_symlink():
        strong_existing = any(a.kind in {"agent_instruction", "task_system", "build_manifest", "source_tree"} for a in assets)
        if strong_existing or score >= 3:
            classification = "existing_unmanaged"
            confidence = "high" if score >= 6 else "medium"
        else:
            classification = "new"
            confidence = "high" if score == 0 else "medium"

    if conflicts and classification == "new":
        classification = "existing_unmanaged"
        confidence = "high"

    task_systems: list[str] = []
    if any(a.role == "beads" for a in assets):
        task_systems.append("beads")
    if any(a.role == "github_issues_candidate" for a in assets):
        task_systems.append("github")

    unresolved: list[str] = []
    if classification == "existing_unmanaged" and not task_systems:
        unresolved.append("task_store")
    if len(task_systems) > 1:
        unresolved.append("task_store_authority")

    assets = sorted(assets, key=lambda a: (a.kind, a.path))
    fingerprint = digest(_fingerprint_payload(root, assets, head, dirty, status_text))

    return ProjectInspection(
        project_root=str(root),
        classification=classification,
        confidence=confidence,
        evidence_score=score,
        baseline_commit=head,
        dirty=dirty,
        repository_fingerprint=fingerprint,
        assets=assets,
        suggested_bindings=_suggest_knowledge_bindings(root),
        detected_task_systems=task_systems,
        unresolved_decisions=unresolved,
        conflicts=sorted(set(conflicts)),
        notes=notes,
    )
