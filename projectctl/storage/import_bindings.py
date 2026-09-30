from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from projectctl.core.time import utc_now


@dataclass(frozen=True)
class TaskImportBinding:
    source_type: str
    source_path: str
    source_task_id: str
    task_store_provider: str
    external_task_id: str
    source_digest: str


def _db(project_root: Path) -> Path:
    return project_root / ".projectctl" / "state.sqlite"


def get_binding(project_root: Path, source_type: str, source_path: str, source_task_id: str) -> TaskImportBinding | None:
    conn = sqlite3.connect(_db(project_root))
    try:
        row = conn.execute(
            """
            SELECT source_type, source_path, source_task_id, task_store_provider,
                   external_task_id, source_digest
            FROM task_import_bindings
            WHERE source_type=? AND source_path=? AND source_task_id=?
            """,
            (source_type, source_path, source_task_id),
        ).fetchone()
    finally:
        conn.close()
    return TaskImportBinding(*row) if row else None


def upsert_binding(
    project_root: Path,
    *,
    source_type: str,
    source_path: str,
    source_task_id: str,
    provider: str,
    external_task_id: str,
    source_digest: str,
) -> None:
    now = utc_now().isoformat()
    conn = sqlite3.connect(_db(project_root))
    try:
        conn.execute(
            """
            INSERT INTO task_import_bindings(
                source_type, source_path, source_task_id, task_store_provider,
                external_task_id, source_digest, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(source_type, source_path, source_task_id) DO UPDATE SET
                task_store_provider=excluded.task_store_provider,
                external_task_id=excluded.external_task_id,
                source_digest=excluded.source_digest,
                updated_at=excluded.updated_at
            """,
            (
                source_type,
                source_path,
                source_task_id,
                provider,
                external_task_id,
                source_digest,
                now,
                now,
            ),
        )
        conn.commit()
    finally:
        conn.close()
