import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from projectctl.core.errors import DatabaseVersionError, QuotaAdmissionError
from projectctl.quota.admission import AccountAdmissionStore
from projectctl.storage.sqlite import (
    APPLICATION_ID,
    GLOBAL_STATE_DB_VERSION,
    initialize_global_state_db,
    inspect_db,
    migrate_global_state_db,
)

NOW = datetime(2026, 10, 7, 6, 0, tzinfo=timezone.utc)


def create_global_v1(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        conn.execute(f"PRAGMA application_id = {APPLICATION_ID}")
        conn.execute("PRAGMA user_version = 1")
        conn.execute(
            "CREATE TABLE schema_migrations("
            "version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL, "
            "projectctl_version TEXT NOT NULL)"
        )
        conn.execute(
            "CREATE TABLE accounts("
            "account_id TEXT PRIMARY KEY, provider TEXT NOT NULL, "
            "config_json TEXT NOT NULL DEFAULT '{}')"
        )
        conn.execute(
            "CREATE TABLE quota_observations("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, account_id TEXT NOT NULL, "
            "observed_at TEXT NOT NULL, snapshot_json TEXT NOT NULL, "
            "FOREIGN KEY(account_id) REFERENCES accounts(account_id))"
        )
        conn.execute(
            "CREATE TABLE project_registry("
            "project_instance_id TEXT PRIMARY KEY, project_id TEXT NOT NULL, "
            "project_root TEXT NOT NULL, registered_at TEXT NOT NULL, "
            "last_seen_at TEXT NOT NULL)"
        )
        conn.execute(
            "CREATE TABLE provider_status("
            "provider TEXT PRIMARY KEY, observed_at TEXT NOT NULL, status_json TEXT NOT NULL)"
        )
        conn.execute(
            "INSERT INTO accounts(account_id, provider, config_json) "
            "VALUES ('acct', 'manual', '{}')"
        )
        conn.commit()
    finally:
        conn.close()


def test_existing_global_v1_requires_explicit_migration(tmp_path: Path):
    db = tmp_path / "state.sqlite"
    create_global_v1(db)

    with pytest.raises(DatabaseVersionError, match="explicit migration"):
        initialize_global_state_db(db)


def test_global_migration_v1_to_v2_is_backup_safe(tmp_path: Path):
    db = tmp_path / "state.sqlite"
    create_global_v1(db)

    result = migrate_global_state_db(db)

    assert result.applied is True
    assert result.from_version == 1
    assert result.to_version == GLOBAL_STATE_DB_VERSION
    assert result.backup_path is not None and result.backup_path.exists()
    assert inspect_db(db) == (APPLICATION_ID, 2)
    assert inspect_db(result.backup_path) == (APPLICATION_ID, 1)

    conn = sqlite3.connect(db)
    try:
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        migrations = {
            row[0] for row in conn.execute("SELECT version FROM schema_migrations")
        }
        account = conn.execute(
            "SELECT provider FROM accounts WHERE account_id='acct'"
        ).fetchone()
    finally:
        conn.close()

    assert {"execution_admissions", "execution_admission_events"} <= tables
    assert {1, 2} <= migrations
    assert account == ("manual",)


def test_global_migration_current_database_is_noop(tmp_path: Path):
    db = tmp_path / "state.sqlite"
    initialize_global_state_db(db)

    result = migrate_global_state_db(db)

    assert result.applied is False
    assert result.backup_path is None
    assert result.to_version == GLOBAL_STATE_DB_VERSION


def test_account_admission_allows_exactly_one_concurrent_owner(tmp_path: Path):
    home = tmp_path / "home"
    initialize_global_state_db(home / "state.sqlite")
    store = AccountAdmissionStore(home, clock=lambda: NOW)
    barrier = threading.Barrier(2)

    def attempt(run_id: str) -> str:
        barrier.wait()
        try:
            store.acquire(
                account_id="acct",
                project_instance_id=f"instance-{run_id}",
                project_id=f"project-{run_id}",
                run_id=run_id,
                lease_owner=f"owner-{run_id}",
            )
            return "acquired"
        except QuotaAdmissionError:
            return "blocked"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, ["run-a", "run-b"]))

    assert sorted(results) == ["acquired", "blocked"]
    current = store.get("acct")
    assert current is not None
    assert current.run_id in {"run-a", "run-b"}


def test_same_owner_reacquire_is_idempotent_and_refreshes_expiry(tmp_path: Path):
    home = tmp_path / "home"
    initialize_global_state_db(home / "state.sqlite")
    times = iter([NOW, NOW + timedelta(seconds=30)])
    store = AccountAdmissionStore(home, clock=lambda: next(times))

    first = store.acquire(
        account_id="acct",
        project_instance_id="instance-a",
        project_id="project-a",
        run_id="run-a",
        lease_owner="owner-a",
        ttl_seconds=60,
    )
    second = store.acquire(
        account_id="acct",
        project_instance_id="instance-a",
        project_id="project-a",
        run_id="run-a",
        lease_owner="owner-a",
        ttl_seconds=60,
    )

    assert second.acquired_at == first.acquired_at
    assert second.heartbeat_at == NOW + timedelta(seconds=30)
    assert second.expires_at == NOW + timedelta(seconds=90)
    assert [event["event_type"] for event in store.events("acct")] == [
        "acquired",
        "reconciled",
    ]


def test_expired_admission_is_reclaimed_and_audited(tmp_path: Path):
    home = tmp_path / "home"
    initialize_global_state_db(home / "state.sqlite")
    first_store = AccountAdmissionStore(home, clock=lambda: NOW)
    first_store.acquire(
        account_id="acct",
        project_instance_id="instance-a",
        project_id="project-a",
        run_id="run-a",
        lease_owner="owner-a",
        ttl_seconds=10,
    )

    second_store = AccountAdmissionStore(
        home,
        clock=lambda: NOW + timedelta(seconds=11),
    )
    second = second_store.acquire(
        account_id="acct",
        project_instance_id="instance-b",
        project_id="project-b",
        run_id="run-b",
        lease_owner="owner-b",
        ttl_seconds=30,
    )

    assert second.run_id == "run-b"
    events = second_store.events("acct")
    assert [event["event_type"] for event in events] == [
        "acquired",
        "stale_reclaimed",
        "acquired",
    ]
    assert events[1]["payload"]["expired_at"] == (
        NOW + timedelta(seconds=10)
    ).isoformat()


def test_release_never_deletes_foreign_admission(tmp_path: Path):
    home = tmp_path / "home"
    initialize_global_state_db(home / "state.sqlite")
    store = AccountAdmissionStore(home, clock=lambda: NOW)
    owned = store.acquire(
        account_id="acct",
        project_instance_id="instance-a",
        project_id="project-a",
        run_id="run-a",
        lease_owner="owner-a",
    )

    foreign = owned.__class__(
        account_id=owned.account_id,
        project_instance_id=owned.project_instance_id,
        project_id=owned.project_id,
        run_id="run-foreign",
        lease_owner="owner-foreign",
        acquired_at=owned.acquired_at,
        heartbeat_at=owned.heartbeat_at,
        expires_at=owned.expires_at,
    )
    with pytest.raises(QuotaAdmissionError, match="foreign admission"):
        store.release(foreign)

    assert store.get("acct") == owned
    assert store.release(owned) is True
    assert store.get("acct") is None
    assert store.release(owned) is False
