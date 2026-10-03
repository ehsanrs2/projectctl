import sqlite3
from pathlib import Path

import pytest

from projectctl.core.errors import DatabaseVersionError
from projectctl.storage.sqlite import (
    APPLICATION_ID,
    PROJECT_STATE_DB_VERSION,
    initialize_project_state_db,
    inspect_db,
    migrate_project_state_db,
)


def create_v1(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        conn.execute(f"PRAGMA application_id = {APPLICATION_ID}")
        conn.execute("PRAGMA user_version = 1")
        conn.execute(
            "CREATE TABLE schema_migrations("
            "version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL, projectctl_version TEXT NOT NULL)"
        )
        conn.execute("CREATE TABLE project_metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        conn.execute(
            "CREATE TABLE task_import_bindings("
            "source_type TEXT NOT NULL, source_path TEXT NOT NULL, source_task_id TEXT NOT NULL, "
            "task_store_provider TEXT NOT NULL, external_task_id TEXT NOT NULL, source_digest TEXT NOT NULL, "
            "created_at TEXT NOT NULL, updated_at TEXT NOT NULL, "
            "PRIMARY KEY(source_type, source_path, source_task_id))"
        )
        conn.execute(
            "INSERT INTO project_metadata(key, value) VALUES ('project_instance_id', 'instance-1')"
        )
        conn.commit()
    finally:
        conn.close()


def test_existing_v1_requires_explicit_migration(tmp_path: Path):
    db = tmp_path / ".projectctl" / "state.sqlite"
    create_v1(db)
    with pytest.raises(DatabaseVersionError, match="explicit migration"):
        initialize_project_state_db(db)


def test_migrate_v1_to_v2_creates_consistent_backup_and_run_tables(tmp_path: Path):
    db = tmp_path / ".projectctl" / "state.sqlite"
    create_v1(db)

    result = migrate_project_state_db(db)
    assert result.applied is True
    assert result.from_version == 1
    assert result.to_version == PROJECT_STATE_DB_VERSION
    assert result.backup_path is not None and result.backup_path.exists()

    assert inspect_db(db) == (APPLICATION_ID, 2)
    assert inspect_db(result.backup_path) == (APPLICATION_ID, 1)

    conn = sqlite3.connect(db)
    try:
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        instance = conn.execute(
            "SELECT value FROM project_metadata WHERE key='project_instance_id'"
        ).fetchone()[0]
        migrations = {
            row[0] for row in conn.execute("SELECT version FROM schema_migrations")
        }
    finally:
        conn.close()

    assert {"runs", "run_events"} <= tables
    assert instance == "instance-1"
    assert {1, 2} <= migrations


def test_migrate_current_database_is_noop(tmp_path: Path):
    db = tmp_path / ".projectctl" / "state.sqlite"
    initialize_project_state_db(db)
    result = migrate_project_state_db(db)
    assert result.applied is False
    assert result.backup_path is None
