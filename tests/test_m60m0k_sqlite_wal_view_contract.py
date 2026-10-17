"""M0k classification is unit-tested without any namespace or privileged mounts."""
from __future__ import annotations

import errno
import sqlite3

import pytest

from scripts.m0k_sqlite_view_contract import classify_view_write_error as classify


@pytest.mark.parametrize(
    ("sqlite_code", "view_errno", "source_errno"),
    [
        (sqlite3.SQLITE_CANTOPEN, None, None),
        (sqlite3.SQLITE_CANTOPEN, errno.EACCES, 0),
        (sqlite3.SQLITE_CANTOPEN, errno.EROFS, errno.EACCES),
        (sqlite3.SQLITE_CANTOPEN, errno.EROFS, None),
        (sqlite3.SQLITE_CANTOPEN, 0, 0),
        (sqlite3.SQLITE_IOERR, errno.EROFS, 0),
        (None, errno.EROFS, 0),
        (sqlite3.SQLITE_CANTOPEN, errno.EROFS, True),  # 1 is not success
        (sqlite3.SQLITE_CANTOPEN, errno.EROFS, False),
    ],
)
def test_cantopen_or_unrelated_failure_never_suffices(
    sqlite_code, view_errno, source_errno,
):
    assert classify(
        os_errno=None, sqlite_code=sqlite_code,
        view_create_errno=view_errno, source_create_errno=source_errno,
    ) == "unexpected_error"


@pytest.mark.parametrize("code", [sqlite3.SQLITE_CANTOPEN, sqlite3.SQLITE_CANTOPEN | 0x100])
def test_cantopen_with_independent_vfs_and_source_control_has_separate_status(code):
    assert classify(
        os_errno=None, sqlite_code=code,
        view_create_errno=errno.EROFS, source_create_errno=0,
    ) == "vfs_ro_confirmed_sqlite_cantopen"


def test_explicit_erofs_or_sqlite_readonly_remains_kernel_denied():
    assert classify(
        os_errno=errno.EROFS, sqlite_code=None,
        view_create_errno=None, source_create_errno=None,
    ) == "kernel_denied"
    assert classify(
        os_errno=None, sqlite_code=sqlite3.SQLITE_READONLY,
        view_create_errno=None, source_create_errno=None,
    ) == "kernel_denied"


def test_no_migration_grant_is_exposed_by_classifier():
    assert set(classify(
        os_errno=None, sqlite_code=14,
        view_create_errno=errno.EROFS, source_create_errno=0,
    ).split()) == {"vfs_ro_confirmed_sqlite_cantopen"}
