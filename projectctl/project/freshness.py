from __future__ import annotations

from pathlib import Path

import yaml

from projectctl.application.status import collect_status
from projectctl.core.paths import resolve_inside_repo
from projectctl.project.loader import load_project_config


GENERATED_FILES = ("STATUS.md", "BUDGET.md", "TASKBOARD.md")


def _frontmatter(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        return {}
    try:
        _, payload, _ = text.split("---", 2)
        data = yaml.safe_load(payload)
        return data if isinstance(data, dict) else {}
    except (ValueError, yaml.YAMLError):
        return {}


def generated_freshness(project_root: Path) -> tuple[list[str], list[str], str]:
    config = load_project_config(project_root)
    generated = resolve_inside_repo(project_root, config.paths.generated, must_exist=False)
    missing: list[str] = []
    stale: list[str] = []
    bundle = collect_status(project_root, record_telemetry=False)
    expected = bundle.source_digest
    for name in GENERATED_FILES:
        path = generated / name
        if not path.exists():
            missing.append(name)
            continue
        meta = _frontmatter(path)
        if meta.get("source_digest") != expected:
            stale.append(name)
    return missing, stale, expected
