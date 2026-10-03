from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

import yaml

from projectctl.application.status import StatusBundle
from projectctl.core.paths import resolve_inside_repo
from projectctl.project.loader import load_project_config
from projectctl.project.locking import project_lock


def _frontmatter(bundle: StatusBundle, git_commit: str | None) -> str:
    meta = {
        "projectctl_generated": True,
        "schema_version": 1,
        "generated_at": bundle.status.generated_at.isoformat(),
        "source_digest": bundle.source_digest,
        "git_commit": git_commit,
    }
    return "---\n" + yaml.safe_dump(meta, sort_keys=False).rstrip() + "\n---\n\n"


def _git_head(root: Path) -> str | None:
    result = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        text=True,
        capture_output=True,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else None


def _status_markdown(bundle: StatusBundle, head: str | None) -> str:
    s = bundle.status
    milestone = "none"
    if s.active_milestone:
        milestone = s.active_milestone.id
        if s.active_milestone.title:
            milestone += f" — {s.active_milestone.title}"
    lines = [
        _frontmatter(bundle, head),
        "# Project Status\n",
        f"- **Project:** {s.project_id}",
        f"- **Current goal:** {s.current_goal or 'not set'}",
        f"- **Active milestone:** {milestone}",
        f"- **Quota mode:** {s.quota_mode.value}" + (" (stale)" if s.quota_stale else ""),
        f"- **Next task:** {s.next_task_id or 'none'}",
    ]
    if s.next_model_profile:
        lines.append(f"- **Recommended model profile:** {s.next_model_profile.value}")
    if s.next_reasoning:
        lines.append(f"- **Recommended reasoning:** {s.next_reasoning.value}")
    c = s.task_counts
    lines.extend([
        "",
        "## Tasks",
        "",
        f"- Total: {c.total}",
        f"- Ready: {c.ready}",
        f"- Blocked: {c.blocked}",
        f"- Running: {c.running}",
        f"- Done: {c.done}",
        f"- Failed: {c.failed}",
        f"- Needs decision: {c.needs_decision}",
        "",
    ])
    return "\n".join(lines)


def _budget_markdown(bundle: StatusBundle, head: str | None) -> str:
    q = bundle.quota
    state = bundle.quota_state

    def pct(value: float | None) -> str:
        return "unknown" if value is None else f"{value * 100:.1f}%"

    rows = []
    for key, label, effective in [
        ("five_hour", "Five-hour", state.five_hour_effective),
        ("weekly", "Weekly", state.weekly_effective),
    ]:
        window = getattr(q, key)
        rows.append(
            f"| {label} | {pct(window.remaining_ratio)} | {pct(effective)} | "
            f"{window.source.value} | {window.confidence.value} | "
            f"{window.reset_at.isoformat() if window.reset_at else 'unknown'} |"
        )
    return (
        _frontmatter(bundle, head)
        + "# Resource Budget\n\n"
        + f"**Mode:** {state.mode.value}" + (" (stale)" if state.stale else "") + "\n\n"
        + "| Window | Remaining | Effective after reserve | Source | Confidence | Reset |\n"
        + "| --- | ---: | ---: | --- | --- | --- |\n"
        + "\n".join(rows)
        + "\n"
    )


def _escape(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def _taskboard_markdown(bundle: StatusBundle, head: str | None) -> str:
    rows = []
    for task in sorted(bundle.tasks.tasks, key=lambda t: (t.status.value, -t.priority, t.id)):
        rows.append(
            f"| {_escape(task.id)} | {task.status.value} | {task.priority} | "
            f"{_escape(task.milestone or '')} | {_escape(task.title)} |"
        )
    body = "\n".join(rows) if rows else "| — | — | — | — | No tasks |"
    return (
        _frontmatter(bundle, head)
        + "# Task Board\n\n"
        + "| ID | Status | Priority | Milestone | Title |\n"
        + "| --- | --- | ---: | --- | --- |\n"
        + body
        + "\n"
    )


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=".projectctl-generated-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    finally:
        try:
            Path(tmp_name).unlink()
        except FileNotFoundError:
            pass


def refresh_generated(project_root: Path, bundle: StatusBundle) -> list[Path]:
    config = load_project_config(project_root)
    generated = resolve_inside_repo(project_root, config.paths.generated, must_exist=False)
    head = _git_head(project_root)
    outputs = {
        generated / "STATUS.md": _status_markdown(bundle, head),
        generated / "BUDGET.md": _budget_markdown(bundle, head),
        generated / "TASKBOARD.md": _taskboard_markdown(bundle, head),
    }
    with project_lock(project_root, "refresh"):
        for path, content in outputs.items():
            _atomic_write(path, content)
    return list(outputs)
