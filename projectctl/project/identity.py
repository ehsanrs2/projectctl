from __future__ import annotations

import sqlite3
from pathlib import Path

from projectctl.core.errors import RepositoryContractError


def project_instance_id(project_root: Path) -> str:
    db = project_root / ".projectctl" / "state.sqlite"
    if not db.exists():
        raise RepositoryContractError(f"Missing ProjectCTL state database: {db}")
    conn = sqlite3.connect(db)
    try:
        row = conn.execute(
            "SELECT value FROM project_metadata WHERE key='project_instance_id'"
        ).fetchone()
    finally:
        conn.close()
    if row is None or not row[0]:
        raise RepositoryContractError("Project instance id is missing from state.sqlite.")
    return str(row[0])
