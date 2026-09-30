import sqlite3
from pathlib import Path

from projectctl.core.errors import DatabaseVersionError

APPLICATION_ID = 0x50544354  # "PTCT"
DATABASE_VERSION = 1


def connect_db(path: Path, *, telemetry: bool = False) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.execute("PRAGMA trusted_schema = OFF")
    conn.execute(f"PRAGMA synchronous = {'NORMAL' if telemetry else 'FULL'}")
    return conn


def _validate_header(conn: sqlite3.Connection, path: Path) -> None:
    app_id = conn.execute("PRAGMA application_id").fetchone()[0]
    user_version = conn.execute("PRAGMA user_version").fetchone()[0]
    if app_id not in (0, APPLICATION_ID):
        raise DatabaseVersionError(f"Unexpected SQLite application_id in {path}: {app_id}")
    if user_version > DATABASE_VERSION:
        raise DatabaseVersionError(
            f"Database {path} is newer than this ProjectCTL version: {user_version}"
        )
    conn.execute(f"PRAGMA application_id = {APPLICATION_ID}")
    conn.execute(f"PRAGMA user_version = {DATABASE_VERSION}")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            applied_at TEXT NOT NULL,
            projectctl_version TEXT NOT NULL
        )
        """
    )


def initialize_project_state_db(path: Path) -> None:
    conn = connect_db(path, telemetry=False)
    try:
        _validate_header(conn, path)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS project_metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS task_import_bindings (
                source_type TEXT NOT NULL,
                source_path TEXT NOT NULL,
                source_task_id TEXT NOT NULL,
                task_store_provider TEXT NOT NULL,
                external_task_id TEXT NOT NULL,
                source_digest TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY(source_type, source_path, source_task_id)
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


def initialize_telemetry_db(path: Path) -> None:
    conn = connect_db(path, telemetry=True)
    try:
        _validate_header(conn, path)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                event_type TEXT NOT NULL,
                payload_json TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS health_checks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                report_json TEXT NOT NULL
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


def initialize_global_state_db(path: Path) -> None:
    conn = connect_db(path, telemetry=False)
    try:
        _validate_header(conn, path)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS accounts (
                account_id TEXT PRIMARY KEY,
                provider TEXT NOT NULL,
                config_json TEXT NOT NULL DEFAULT '{}'
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS quota_observations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id TEXT NOT NULL,
                observed_at TEXT NOT NULL,
                snapshot_json TEXT NOT NULL,
                FOREIGN KEY(account_id) REFERENCES accounts(account_id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS project_registry (
                project_instance_id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                project_root TEXT NOT NULL,
                registered_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS provider_status (
                provider TEXT PRIMARY KEY,
                observed_at TEXT NOT NULL,
                status_json TEXT NOT NULL
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


def inspect_db(path: Path) -> tuple[int, int]:
    if not path.exists():
        raise DatabaseVersionError(f"Missing SQLite database: {path}")
    conn = sqlite3.connect(path)
    try:
        app_id = conn.execute("PRAGMA application_id").fetchone()[0]
        user_version = conn.execute("PRAGMA user_version").fetchone()[0]
    finally:
        conn.close()
    return app_id, user_version
