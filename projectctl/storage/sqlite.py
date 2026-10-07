from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from projectctl import __version__
from projectctl.core.errors import DatabaseVersionError

APPLICATION_ID = 0x50544354  # "PTCT"
PROJECT_STATE_DB_VERSION = 2
TELEMETRY_DB_VERSION = 1
GLOBAL_STATE_DB_VERSION = 2
DATABASE_VERSION = PROJECT_STATE_DB_VERSION


@dataclass(frozen=True)
class MigrationResult:
    path: Path
    from_version: int
    to_version: int
    backup_path: Path | None
    applied: bool


def connect_db(path: Path, *, telemetry: bool = False) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.execute("PRAGMA trusted_schema = OFF")
    conn.execute(f"PRAGMA synchronous = {'NORMAL' if telemetry else 'FULL'}")
    return conn


def _validate_application_id(conn: sqlite3.Connection, path: Path) -> int:
    app_id = conn.execute("PRAGMA application_id").fetchone()[0]
    if app_id not in (0, APPLICATION_ID):
        raise DatabaseVersionError(f"Unexpected SQLite application_id in {path}: {app_id}")
    return int(conn.execute("PRAGMA user_version").fetchone()[0])


def _create_migrations_table(conn: sqlite3.Connection) -> None:
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


def _record_migration(conn: sqlite3.Connection, version: int, name: str) -> None:
    conn.execute(
        """
        INSERT OR IGNORE INTO schema_migrations(version, name, applied_at, projectctl_version)
        VALUES (?, ?, ?, ?)
        """,
        (version, name, datetime.now(timezone.utc).isoformat(), __version__),
    )


def _create_project_v1(conn: sqlite3.Connection) -> None:
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


def _create_project_v2(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS runs (
            run_id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL,
            status TEXT NOT NULL,
            terminal_reason TEXT,
            execution_plan_digest TEXT NOT NULL,
            base_commit TEXT NOT NULL,
            candidate_commit TEXT,
            branch_name TEXT NOT NULL UNIQUE,
            worktree_id TEXT NOT NULL UNIQUE,
            worktree_path TEXT NOT NULL UNIQUE,
            worker_provider TEXT NOT NULL,
            worker_thread_id TEXT,
            lease_owner TEXT,
            lease_expires_at TEXT,
            heartbeat_at TEXT,
            created_at TEXT NOT NULL,
            started_at TEXT,
            completed_at TEXT,
            checkpoint_at TEXT,
            checkpoint_ref TEXT,
            manifest_json TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_runs_one_active_per_task
        ON runs(task_id)
        WHERE status IN (
            'planned', 'preparing', 'claimed', 'running',
            'verifying', 'ready_to_integrate', 'integrating'
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_runs_status_created
        ON runs(status, created_at)
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS run_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            event_type TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            FOREIGN KEY(run_id) REFERENCES runs(run_id) ON DELETE CASCADE
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_run_events_run
        ON run_events(run_id, id)
        """
    )


def _assert_expected_tables(conn: sqlite3.Connection, path: Path, expected: set[str]) -> None:
    tables = {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    missing = expected - tables
    if missing:
        raise DatabaseVersionError(
            f"Database {path} claims the current version but is missing tables: {sorted(missing)}"
        )


def initialize_project_state_db(path: Path) -> None:
    existed = path.exists()
    conn = connect_db(path, telemetry=False)
    try:
        version = _validate_application_id(conn, path)
        if existed and version not in (0, PROJECT_STATE_DB_VERSION):
            if version < PROJECT_STATE_DB_VERSION:
                raise DatabaseVersionError(
                    f"Database {path} is v{version}; explicit migration to "
                    f"v{PROJECT_STATE_DB_VERSION} is required. Run projectctl migrate."
                )
            raise DatabaseVersionError(
                f"Database {path} is newer than this ProjectCTL version: {version}"
            )

        if version == 0:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(f"PRAGMA application_id = {APPLICATION_ID}")
            _create_migrations_table(conn)
            _create_project_v1(conn)
            _record_migration(conn, 1, "project-state-baseline")
            _create_project_v2(conn)
            _record_migration(conn, 2, "m1-run-store")
            conn.execute(f"PRAGMA user_version = {PROJECT_STATE_DB_VERSION}")
            conn.commit()
        else:
            _assert_expected_tables(
                conn,
                path,
                {"schema_migrations", "project_metadata", "task_import_bindings", "runs", "run_events"},
            )
    finally:
        conn.close()


def _initialize_v1_database(
    path: Path,
    *,
    telemetry: bool,
    create_schema,
    migration_name: str,
) -> None:
    conn = connect_db(path, telemetry=telemetry)
    try:
        version = _validate_application_id(conn, path)
        if version > 1:
            raise DatabaseVersionError(f"Database {path} is newer than supported v1: {version}")
        if version == 0:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(f"PRAGMA application_id = {APPLICATION_ID}")
            _create_migrations_table(conn)
            create_schema(conn)
            _record_migration(conn, 1, migration_name)
            conn.execute("PRAGMA user_version = 1")
            conn.commit()
    finally:
        conn.close()


def initialize_telemetry_db(path: Path) -> None:
    def create(conn: sqlite3.Connection) -> None:
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

    _initialize_v1_database(
        path,
        telemetry=True,
        create_schema=create,
        migration_name="telemetry-baseline",
    )


def _create_global_v1(conn: sqlite3.Connection) -> None:
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


def _create_global_v2(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS execution_admissions (
            account_id TEXT PRIMARY KEY,
            project_instance_id TEXT NOT NULL,
            project_id TEXT NOT NULL,
            run_id TEXT NOT NULL,
            lease_owner TEXT NOT NULL,
            acquired_at TEXT NOT NULL,
            heartbeat_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            FOREIGN KEY(account_id) REFERENCES accounts(account_id)
        )
        """
    )
    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_execution_admissions_run
        ON execution_admissions(run_id)
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS execution_admission_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            observed_at TEXT NOT NULL,
            project_instance_id TEXT,
            project_id TEXT,
            run_id TEXT,
            lease_owner TEXT,
            payload_json TEXT NOT NULL DEFAULT '{}',
            FOREIGN KEY(account_id) REFERENCES accounts(account_id)
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_execution_admission_events_account
        ON execution_admission_events(account_id, id)
        """
    )


def initialize_global_state_db(path: Path) -> None:
    existed = path.exists()
    conn = connect_db(path, telemetry=False)
    try:
        version = _validate_application_id(conn, path)
        if existed and version not in (0, GLOBAL_STATE_DB_VERSION):
            if version < GLOBAL_STATE_DB_VERSION:
                raise DatabaseVersionError(
                    f"Database {path} is v{version}; explicit migration to "
                    f"v{GLOBAL_STATE_DB_VERSION} is required. Run projectctl migrate."
                )
            raise DatabaseVersionError(
                f"Database {path} is newer than this ProjectCTL version: {version}"
            )

        if version == 0:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(f"PRAGMA application_id = {APPLICATION_ID}")
            _create_migrations_table(conn)
            _create_global_v1(conn)
            _record_migration(conn, 1, "global-state-baseline")
            _create_global_v2(conn)
            _record_migration(conn, 2, "m4-global-execution-admission")
            conn.execute(f"PRAGMA user_version = {GLOBAL_STATE_DB_VERSION}")
            conn.commit()
        else:
            _assert_expected_tables(
                conn,
                path,
                {
                    "schema_migrations",
                    "accounts",
                    "quota_observations",
                    "project_registry",
                    "provider_status",
                    "execution_admissions",
                    "execution_admission_events",
                },
            )
    finally:
        conn.close()


def _sqlite_backup(source_path: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    source = sqlite3.connect(source_path)
    target = sqlite3.connect(destination)
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()


def migrate_project_state_db(path: Path) -> MigrationResult:
    if not path.exists():
        raise DatabaseVersionError(f"Missing SQLite database: {path}")

    app_id, current = inspect_db(path)
    if app_id != APPLICATION_ID:
        raise DatabaseVersionError(f"Unexpected application_id in {path}: {app_id}")
    if current > PROJECT_STATE_DB_VERSION:
        raise DatabaseVersionError(
            f"Database {path} is newer than this ProjectCTL version: {current}"
        )
    if current == PROJECT_STATE_DB_VERSION:
        return MigrationResult(path, current, current, None, False)
    if current != 1:
        raise DatabaseVersionError(
            f"No supported migration path for project state database v{current}."
        )

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = path.parent / "backups" / f"{path.name}.v{current}.{stamp}.bak"
    _sqlite_backup(path, backup)

    conn = connect_db(path, telemetry=False)
    try:
        version = _validate_application_id(conn, path)
        if version != current:
            raise DatabaseVersionError(
                f"Database version changed during migration: expected {current}, found {version}."
            )
        conn.execute("BEGIN IMMEDIATE")
        _create_migrations_table(conn)
        _record_migration(conn, 1, "project-state-baseline")
        _create_project_v2(conn)
        _record_migration(conn, 2, "m1-run-store")
        conn.execute(f"PRAGMA user_version = {PROJECT_STATE_DB_VERSION}")
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    return MigrationResult(path, current, PROJECT_STATE_DB_VERSION, backup, True)


def migrate_global_state_db(path: Path) -> MigrationResult:
    if not path.exists():
        raise DatabaseVersionError(f"Missing SQLite database: {path}")

    app_id, current = inspect_db(path)
    if app_id != APPLICATION_ID:
        raise DatabaseVersionError(f"Unexpected application_id in {path}: {app_id}")
    if current > GLOBAL_STATE_DB_VERSION:
        raise DatabaseVersionError(
            f"Database {path} is newer than this ProjectCTL version: {current}"
        )
    if current == GLOBAL_STATE_DB_VERSION:
        return MigrationResult(path, current, current, None, False)
    if current != 1:
        raise DatabaseVersionError(
            f"No supported migration path for global state database v{current}."
        )

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = path.parent / "backups" / f"{path.name}.v{current}.{stamp}.bak"
    _sqlite_backup(path, backup)

    conn = connect_db(path, telemetry=False)
    try:
        version = _validate_application_id(conn, path)
        if version != current:
            raise DatabaseVersionError(
                f"Database version changed during migration: expected {current}, found {version}."
            )
        conn.execute("BEGIN IMMEDIATE")
        _create_migrations_table(conn)
        _record_migration(conn, 1, "global-state-baseline")
        _create_global_v2(conn)
        _record_migration(conn, 2, "m4-global-execution-admission")
        conn.execute(f"PRAGMA user_version = {GLOBAL_STATE_DB_VERSION}")
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    return MigrationResult(path, current, GLOBAL_STATE_DB_VERSION, backup, True)


def inspect_db(path: Path) -> tuple[int, int]:
    if not path.exists():
        raise DatabaseVersionError(f"Missing SQLite database: {path}")
    conn = sqlite3.connect(path)
    try:
        app_id = conn.execute("PRAGMA application_id").fetchone()[0]
        user_version = conn.execute("PRAGMA user_version").fetchone()[0]
    finally:
        conn.close()
    return int(app_id), int(user_version)
