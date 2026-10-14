"""B3a4 backups only newly initialized disposable ProjectCTL v2 databases."""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest

from projectctl.storage.sqlite import (
    APPLICATION_ID,
    PROJECT_STATE_DB_VERSION,
    connect_db,
    initialize_project_state_db,
    inspect_db,
)
from projectctl.trace.seal_backup_lab import (
    BackupRehearsalRefused,
    rehearse_disposable_v2_backup,
)


def _source(tmp_path: Path):
    db = tmp_path / "fixture" / ".projectctl" / "state.sqlite"
    initialize_project_state_db(db)
    conn = connect_db(db)
    conn.execute(
        "INSERT INTO project_metadata(key,value) VALUES(?,?)",
        ("fixture-proof", "WAL-COMMITTED"),
    )
    conn.commit()
    assert inspect_db(db) == (APPLICATION_ID, 2)
    return conn, db


def _read_fixture(db: Path):
    conn = sqlite3.connect(db)
    try:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 2
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        return conn.execute(
            "SELECT value FROM project_metadata WHERE key='fixture-proof'"
        ).fetchone()[0]
    finally:
        conn.close()


def test_wal_committed_data_is_preserved_in_separately_published_backup(tmp_path):
    source, db = _source(tmp_path)
    try:
        assert (Path(str(db) + "-wal")).exists()
        destination = tmp_path / "fixture" / "state-v2-snapshot.bak"
        published = rehearse_disposable_v2_backup(source, destination)
        assert published == destination
        assert published.is_file()
        assert published.stat().st_mode & 0o777 == 0o600
        assert _read_fixture(destination) == "WAL-COMMITTED"
        assert inspect_db(db) == (APPLICATION_ID, 2)
        assert PROJECT_STATE_DB_VERSION == 2
        assert not list(destination.parent.glob(".b3a4-v2-*"))
    finally:
        source.close()


def test_backup_restores_into_new_disposable_database_without_replacing_authority(tmp_path):
    source, db = _source(tmp_path)
    try:
        backup = rehearse_disposable_v2_backup(
            source, tmp_path / "fixture" / "snapshot-v2.bak"
        )
        fresh = tmp_path / "restored" / "state.sqlite"
        fresh.parent.mkdir()
        copy_from = sqlite3.connect(backup)
        copy_to = sqlite3.connect(fresh)
        try:
            copy_from.backup(copy_to)
        finally:
            copy_to.close()
            copy_from.close()
        assert _read_fixture(fresh) == "WAL-COMMITTED"
        assert _read_fixture(db) == "WAL-COMMITTED"
        assert fresh != db
        assert inspect_db(db) == (APPLICATION_ID, 2)
    finally:
        source.close()


@pytest.mark.parametrize("phase", [
    "staged", "copied", "validated", "file_fsynced"
])
def test_fault_before_publish_leaves_no_visible_backup_or_staging(tmp_path, phase):
    source, db = _source(tmp_path)
    destination = tmp_path / "fixture" / "recovery-v2.bak"

    def injected_failure(current, _stage):
        if current == phase:
            raise RuntimeError("simulated_crash")

    try:
        with pytest.raises(RuntimeError, match="simulated_crash"):
            rehearse_disposable_v2_backup(
                source, destination, fault_hook=injected_failure
            )
        assert not destination.exists()
        assert not list(destination.parent.glob(".b3a4-v2-*"))
        assert _read_fixture(db) == "WAL-COMMITTED"
    finally:
        source.close()


def test_corrupt_staging_copy_is_rejected_before_publishing(tmp_path):
    source, db = _source(tmp_path)
    dest = tmp_path / "fixture" / "recovery-v2.bak"

    def corrupt(phase, staging):
        if phase == "copied":
            staging.write_bytes(b"not a SQLite database")

    try:
        with pytest.raises(BackupRehearsalRefused, match="invalid_backup_database"):
            rehearse_disposable_v2_backup(source, dest, fault_hook=corrupt)
        assert not dest.exists()
        assert not list(dest.parent.glob(".b3a4-v2-*"))
        assert _read_fixture(db) == "WAL-COMMITTED"
    finally:
        source.close()


def test_existing_backup_is_never_overwritten(tmp_path):
    source, db = _source(tmp_path)
    destination = tmp_path / "fixture" / "snapshot-v2.bak"
    try:
        rehearse_disposable_v2_backup(source, destination)
        original = destination.read_bytes()
        with pytest.raises(BackupRehearsalRefused, match="backup_already_exists"):
            rehearse_disposable_v2_backup(source, destination)
        assert destination.read_bytes() == original
        assert _read_fixture(db) == "WAL-COMMITTED"
    finally:
        source.close()


def test_symlink_backup_destination_is_rejected_without_following(tmp_path):
    source, _ = _source(tmp_path)
    outside = tmp_path / "outside.txt"
    outside.write_text("PRIVATE", encoding="utf-8")
    destination = tmp_path / "fixture" / "snapshot-v2.bak"
    destination.symlink_to(outside)
    try:
        with pytest.raises(BackupRehearsalRefused, match="backup_already_exists"):
            rehearse_disposable_v2_backup(source, destination)
        assert outside.read_text(encoding="utf-8") == "PRIVATE"
    finally:
        source.close()


def test_symlink_backup_parent_is_rejected(tmp_path):
    source, _ = _source(tmp_path)
    target = tmp_path / "fixture"
    link = tmp_path / "linked"
    link.symlink_to(target, target_is_directory=True)
    try:
        with pytest.raises(BackupRehearsalRefused, match="invalid_backup_directory"):
            rehearse_disposable_v2_backup(source, link / "unsafe.bak")
        assert not (target / "unsafe.bak").exists()
    finally:
        source.close()


def test_missing_backup_directory_is_not_created(tmp_path):
    source, _ = _source(tmp_path)
    missing = tmp_path / "missing" / "snapshot-v2.bak"
    try:
        with pytest.raises(BackupRehearsalRefused, match="invalid_backup_directory"):
            rehearse_disposable_v2_backup(source, missing)
        assert not missing.parent.exists()
    finally:
        source.close()


def test_active_source_transaction_fails_before_backup_creation(tmp_path):
    source, db = _source(tmp_path)
    destination = tmp_path / "fixture" / "snapshot-v2.bak"
    try:
        source.execute("BEGIN IMMEDIATE")
        with pytest.raises(BackupRehearsalRefused, match="source_transaction_not_quiescent"):
            rehearse_disposable_v2_backup(source, destination)
        source.rollback()
        assert not destination.exists()
        assert _read_fixture(db) == "WAL-COMMITTED"
    finally:
        source.close()


def test_memory_source_refused_with_no_files_created(tmp_path):
    source = sqlite3.connect(":memory:")
    dest = tmp_path / "ignored.bak"
    try:
        with pytest.raises(BackupRehearsalRefused, match="invalid_backup_source"):
            rehearse_disposable_v2_backup(source, dest)
        assert not dest.exists()
    finally:
        source.close()


def test_wrong_db_version_not_accepted_as_v2_backup(tmp_path):
    source, _ = _source(tmp_path)
    destination = tmp_path / "fixture" / "snapshot-v2.bak"
    try:
        source.execute("PRAGMA user_version=3")
        with pytest.raises(BackupRehearsalRefused, match="invalid_backup_database"):
            rehearse_disposable_v2_backup(source, destination)
        assert not destination.exists()
    finally:
        source.close()


def test_lab_does_not_register_or_enable_projectctl_migration(tmp_path):
    source, db = _source(tmp_path)
    try:
        assert PROJECT_STATE_DB_VERSION == 2
        assert inspect_db(db) == (APPLICATION_ID, 2)
        assert not (tmp_path / ".projectctl").exists()
        assert not list((tmp_path / "fixture").glob(".b3a4-v2-*"))
    finally:
        source.close()
