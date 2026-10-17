"""M0k: classify SQLITE_CANTOPEN only alongside direct mount-view OS evidence.

This is test-only logic. It does NOT attest to causation for SQLite's
CANTOPEN, all-writer isolation, or authority to migrate to v3.
"""
from __future__ import annotations

import errno
import sqlite3


def classify_view_write_error(
    *,
    os_errno: int | None,
    sqlite_code: int | None,
    view_create_errno: int | None,
    source_create_errno: int | None,
) -> str:
    """Strictly distinguish SQLite observations from independent VFS proof.

    CANTOPEN (14) alone can mean many things. An independent O_CREAT
    against the same disposable SQLite parent through the read-only
    view MUST yield EROFS, and a source-alias O_CREAT MUST succeed,
    before treating CANTOPEN as consistent with view-level enforcement.
    Even then, the exact SQLite-internal failure site is not proven.
    """
    if os_errno == errno.EROFS:
        return "kernel_denied"
    if type(sqlite_code) is int and sqlite_code & 255 == sqlite3.SQLITE_READONLY:
        return "kernel_denied"
    if (
        type(sqlite_code) is int
        and sqlite_code & 255 == sqlite3.SQLITE_CANTOPEN
        and view_create_errno == errno.EROFS
        and type(source_create_errno) is int
        and source_create_errno == 0
    ):
        return "vfs_ro_confirmed_sqlite_cantopen"
    return "unexpected_error"
