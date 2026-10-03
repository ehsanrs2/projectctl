import os
import re
import subprocess
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from projectctl import __version__
from projectctl.core.digest import digest
from projectctl.core.errors import RepositoryContractError
from projectctl.core.time import utc_now
from projectctl.project.root import git_root
from projectctl.project.loader import load_project_config
from projectctl.project.state import PROJECT_STATE_PATH, initial_project_state
from projectctl.schemas.config import ProjectConfig, ProjectIdentity
from projectctl.storage.sqlite import initialize_global_state_db, initialize_project_state_db, initialize_telemetry_db


@dataclass
class InitResult:
    project_root: Path
    created: list[str] = field(default_factory=list)
    preserved: list[str] = field(default_factory=list)


def projectctl_home() -> Path:
    override = os.environ.get("PROJECTCTL_HOME")
    return Path(override).expanduser().resolve() if override else (Path.home() / ".projectctl").resolve()


def _slug(value: str) -> str:
    value = value.lower().strip()
    value = re.sub(r"[^a-z0-9._-]+", "-", value)
    value = value.strip("-._")
    return value or "project"


def _write_if_missing(path: Path, content: str, result: InitResult) -> None:
    if path.exists():
        result.preserved.append(str(path.relative_to(result.project_root)))
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    result.created.append(str(path.relative_to(result.project_root)))


def _global_init(home: Path) -> None:
    home.mkdir(parents=True, exist_ok=True)
    (home / "accounts").mkdir(exist_ok=True)
    (home / "skills").mkdir(exist_ok=True)
    (home / "projects").mkdir(exist_ok=True)
    initialize_global_state_db(home / "state.sqlite")
    global_config = home / "config.yaml"
    if not global_config.exists():
        global_config.write_text(
            "schema_kind: projectctl.global_config\nschema_version: 1\n",
            encoding="utf-8",
        )


def initialize_project(target: Path) -> InitResult:
    target = target.resolve()
    root = git_root(target)
    result = InitResult(project_root=root)

    ctl = root / ".projectctl"
    ctl.mkdir(exist_ok=True)
    for name in ["runs", "cache", "locks"]:
        (ctl / name).mkdir(exist_ok=True)
    for directory in [
        "docs/decisions", "docs/research", "docs/findings", "docs/failures",
        "docs/exec-plans", "docs/generated", "specs", "evidence", ".agents/skills",
    ]:
        (root / directory).mkdir(parents=True, exist_ok=True)

    config_path = ctl / "config.yaml"
    if config_path.exists():
        # Existing configuration is human/project state: preserve it only if it is valid.
        load_project_config(root)
        result.preserved.append(".projectctl/config.yaml")
    else:
        config = ProjectConfig(project=ProjectIdentity(id=_slug(root.name), name=root.name))
        data = config.model_dump(mode="json")
        config_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
        result.created.append(".projectctl/config.yaml")

    config = load_project_config(root)

    state_text = yaml.safe_dump(
        initial_project_state(config.project.id).model_dump(mode="json"),
        sort_keys=False,
        allow_unicode=True,
    )
    _write_if_missing(root / PROJECT_STATE_PATH, state_text, result)

    _write_if_missing(root / "docs/PROJECT.md", "# Project\n\n## Objective\n\nDescribe the project objective.\n", result)
    _write_if_missing(root / "docs/ROADMAP.md", "# Roadmap\n\n## Current Milestone\n\nM0\n", result)
    _write_if_missing(root / "docs/CONSTRAINTS.md", "# Constraints\n\nDocument project constraints here.\n", result)
    _write_if_missing(
        root / "AGENTS.md",
        "# Project workflow\n\nProject intent lives in `docs/` and `specs/`.\n\n"
        "Beads is the canonical task tracker when configured.\n"
        "Generated files under `docs/generated/` must not be edited manually.\n"
        "ProjectCTL owns `.projectctl/` operational state.\n"
        "Do not create parallel task tracking systems.\n",
        result,
    )

    initialize_project_state_db(ctl / "state.sqlite")
    initialize_telemetry_db(ctl / "telemetry.sqlite")

    # Persist a stable clone/installation identity independent from the logical project ID.
    import sqlite3
    conn = sqlite3.connect(ctl / "state.sqlite")
    try:
        existing = conn.execute("SELECT value FROM project_metadata WHERE key='project_instance_id'").fetchone()
        if existing is None:
            conn.execute(
                "INSERT INTO project_metadata(key, value) VALUES (?, ?)",
                ("project_instance_id", str(uuid.uuid4())),
            )
        conn.execute(
            "INSERT OR REPLACE INTO project_metadata(key, value) VALUES (?, ?)",
            ("projectctl_version", __version__),
        )
        conn.commit()
    finally:
        conn.close()

    _global_init(projectctl_home())

    # Register this local clone globally.
    import sqlite3 as _sqlite3
    from projectctl.core.time import utc_now as _utc_now
    global_conn = _sqlite3.connect(projectctl_home() / "state.sqlite")
    try:
        instance_id = conn_value = None
        local_conn = _sqlite3.connect(ctl / "state.sqlite")
        try:
            row = local_conn.execute("SELECT value FROM project_metadata WHERE key='project_instance_id'").fetchone()
            instance_id = row[0]
        finally:
            local_conn.close()
        now = _utc_now().isoformat()
        global_conn.execute(
            """
            INSERT INTO project_registry(project_instance_id, project_id, project_root, registered_at, last_seen_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(project_instance_id) DO UPDATE SET
              project_id=excluded.project_id,
              project_root=excluded.project_root,
              last_seen_at=excluded.last_seen_at
            """,
            (instance_id, config.project.id, str(root), now, now),
        )
        global_conn.commit()
    finally:
        global_conn.close()

    return result
