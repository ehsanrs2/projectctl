"""B3a4 experiment: no-clobber, tested v2 SQLite backup publication.

ONLY for explicit disposable-fixture rehearsals. Not registered in the
ProjectCTL migrator, verifier, Trace reader, scheduler or CLI. The caller
opens an authorized source connection; this is NOT a security-hardened
production source-path, maintenance lock or crash-recovery implementation.
"""
from __future__ import annotations

import os
import sqlite3
import stat
import tempfile
from pathlib import Path
from typing import Callable

from projectctl.storage.sqlite import APPLICATION_ID, PROJECT_STATE_DB_VERSION

_BACKUP_PHASES = (
    "staged",
    "copied",
    "validated",
    "file_fsynced",
)


class BackupRehearsalRefused(ValueError):
    """Internal typed refusal without printing source paths or SQL content."""


def _check_v2(conn: sqlite3.Connection) -> None:
    try:
        app_id = conn.execute("PRAGMA application_id").fetchone()[0]
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
    except sqlite3.Error:
        raise BackupRehearsalRefused("invalid_backup_database") from None
    if (app_id != APPLICATION_ID or version != 2 or
            integrity != "ok" or PROJECT_STATE_DB_VERSION != 2):
        raise BackupRehearsalRefused("invalid_backup_database")


def rehearse_disposable_v2_backup(
    source: sqlite3.Connection,
    destination: Path,
    *,
    fault_hook: Callable[[str, Path], None] | None = None,
) -> Path:
    """Create, validate, fsync and hard-link a v2 backup without overwrite.

    Does not open a source connection, initiate a migration, restore into
    the source, or claim snapshot equivalence with JSON artifacts.
    The first SQLite backup can read committed WAL frames but its epoch
    is *not* tied to the RunStore/filesystem writer publication protocol.

    Preconditions (NOT enforced as production security guarantees):
    caller selected a disposable source and ensured all writers quiescent.
    A later production path needs an independent maintenance/quiescence
    gate, symlink-safe anchored directories and durable recovery protocol.
    """
    if os.name != "posix" or not hasattr(os, "O_NOFOLLOW"):
        raise BackupRehearsalRefused("unsupported_platform")
    if not isinstance(source, sqlite3.Connection) or source.in_transaction:
        raise BackupRehearsalRefused("source_transaction_not_quiescent")
    if not isinstance(destination, Path) or destination.name in ("", ".", ".."):
        raise BackupRehearsalRefused("invalid_backup_destination")
    try:
        main = next(
            path for _, name, path in source.execute("PRAGMA database_list")
            if name == "main"
        )
    except (StopIteration, sqlite3.Error):
        raise BackupRehearsalRefused("invalid_backup_source") from None
    if not main or main == ":memory:":
        raise BackupRehearsalRefused("invalid_backup_source")
    _check_v2(source)

    parent = destination.parent
    try:
        mode = parent.lstat().st_mode
    except OSError:
        raise BackupRehearsalRefused("invalid_backup_directory") from None
    if not stat.S_ISDIR(mode):
        raise BackupRehearsalRefused("invalid_backup_directory")
    if destination.exists() or destination.is_symlink():
        raise BackupRehearsalRefused("backup_already_exists")

    stage: Path | None = None
    try:
        fd, name = tempfile.mkstemp(prefix=".b3a4-v2-", suffix=".sqlite", dir=parent)
        stage = Path(name)
        os.close(fd)
        if fault_hook:
            fault_hook(_BACKUP_PHASES[0], stage)

        target = sqlite3.connect(stage)
        try:
            source.backup(target)
        finally:
            target.close()
        if fault_hook:
            fault_hook(_BACKUP_PHASES[1], stage)

        check = sqlite3.connect(stage)
        try:
            _check_v2(check)
        finally:
            check.close()
        if fault_hook:
            fault_hook(_BACKUP_PHASES[2], stage)

        fd = os.open(stage, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise BackupRehearsalRefused("unsafe_backup_stage")
            os.fsync(fd)
        finally:
            os.close(fd)
        if fault_hook:
            fault_hook(_BACKUP_PHASES[3], stage)

        # Hard link creates the final name atomically and fails EEXIST.
        # Unlike os.replace, it cannot overwrite a previous backup.
        os.link(stage, destination, follow_symlinks=False)
        directory_fd = os.open(
            parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        )
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        return destination
    finally:
        if stage is not None:
            stage.unlink(missing_ok=True)
