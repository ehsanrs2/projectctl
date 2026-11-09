"""M6a G1: offline, test-only, Linux no-atime detached byte acquisition.

All files are synthetic, owned by the test process, under pytest tmp_path.
This proves only a *bounded observed before/after property* of file reads on
the test filesystem. It does NOT prove no transient ABA, hostile concurrency,
independent immutability, safe capture from a live ProjectCTL source, origin,
DB+JSON epoch, custody, current state, or output CLI admission.
"""
from __future__ import annotations

import errno
import os
import stat
import sys
from pathlib import Path

import pytest

from test_m60m6a_g0_memory_detached_input import (
    _inspect_memory_image,
    _synthetic_v2_rollback_image,
    InputRefused,
)

pytestmark = pytest.mark.skipif(
    not sys.platform.startswith("linux") or
    not all(hasattr(os, name) for name in
            ("O_NOATIME", "O_NOFOLLOW", "O_DIRECTORY", "O_CLOEXEC",
             "O_NONBLOCK", "getuid", "geteuid")),
    reason="G1 is a Linux-only O_NOATIME disposable experiment",
)

_DIR = "m6a-g1-detached"
_DB = "synthetic-projectctl-state.sqlite"
_CONTEXT = "synthetic-context.json"
_ALLOWED = {_DB, _CONTEXT}
_LIMIT = 16 * 1024 * 1024
_PASS = "M6A_G1_DETACHED_NOATIME_LAB_ONLY"


class AcquisitionRefused(ValueError):
    """Sanitized test-only refusal, never a trusted source-state report."""


def _identity(info: os.stat_result) -> tuple[int, ...]:
    return (
        info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid,
        info.st_nlink, info.st_size, info.st_atime_ns,
        info.st_mtime_ns, info.st_ctime_ns,
    )


def _acquire_test_owned_leaf(
    root: Path, leaf: str, *, byte_limit: int = _LIMIT
) -> bytes:
    """Use descriptor-relative no-atime reads; never open SQLite on this path.

    Preconditions deliberately limit this helper to a known synthetic fixture
    directory and fixed filenames. A caller-provided path is NOT admission.
    No O_RDONLY fallback is permitted if NOATIME or its permission fails.
    """
    if (type(root) is not Path or not root.is_absolute()
            or root.name != _DIR or leaf not in _ALLOWED
            or type(leaf) is not str
            or type(byte_limit) is not int or byte_limit < 1
            or byte_limit > _LIMIT):
        raise AcquisitionRefused("OUTSIDE_DISPOSABLE_INPUT_SCOPE")
    if not hasattr(os, "O_NOATIME"):
        raise AcquisitionRefused("NOATIME_UNAVAILABLE")
    noatime = os.O_NOATIME
    directory_flags = (
        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        | os.O_CLOEXEC | noatime
    )
    file_flags = (
        os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
        | os.O_CLOEXEC | noatime
    )
    directory_fd = -1
    file_fd = -1
    try:
        directory_fd = os.open(root, directory_flags)
        initial_dir = os.fstat(directory_fd)
        if (not stat.S_ISDIR(initial_dir.st_mode)
                or initial_dir.st_uid != os.geteuid()
                or stat.S_IMODE(initial_dir.st_mode) != 0o700):
            raise AcquisitionRefused("UNTRUSTED_DETACHED_DIRECTORY")
        file_fd = os.open(leaf, file_flags, dir_fd=directory_fd)
        initial_file = os.fstat(file_fd)
        if (not stat.S_ISREG(initial_file.st_mode)
                or initial_file.st_uid != os.geteuid()
                or initial_file.st_nlink != 1
                or stat.S_IMODE(initial_file.st_mode) not in (0o400, 0o600)
                or initial_file.st_size < 1
                or initial_file.st_size > byte_limit):
            raise AcquisitionRefused("UNTRUSTED_DETACHED_LEAF")
        data = bytearray()
        while len(data) <= byte_limit:
            chunk = os.read(
                file_fd, min(64 * 1024, byte_limit + 1 - len(data))
            )
            if not chunk:
                break
            data.extend(chunk)
        if len(data) != initial_file.st_size or len(data) > byte_limit:
            raise AcquisitionRefused("CHANGED_OR_UNBOUNDED_LEAF")
        final_fd = os.fstat(file_fd)
        final_path = os.stat(
            leaf, dir_fd=directory_fd, follow_symlinks=False
        )
        final_dir = os.fstat(directory_fd)
        final_root_path = os.stat(root, follow_symlinks=False)
        if (_identity(initial_file) != _identity(final_fd)
                or _identity(initial_file) != _identity(final_path)
                or _identity(initial_dir) != _identity(final_dir)
                or _identity(initial_dir) != _identity(final_root_path)):
            raise AcquisitionRefused("OBSERVED_METADATA_OR_ALIAS_CHANGE")
        return bytes(data)
    except AcquisitionRefused:
        raise
    except OSError as exc:
        if exc.errno in (errno.EACCES, errno.EPERM, errno.EINVAL,
                         getattr(errno, "ENOTSUP", -1)):
            raise AcquisitionRefused("NOATIME_OR_FILE_ACCESS_DENIED") from None
        raise AcquisitionRefused("DETACHED_LEAF_READ_REFUSED") from None
    finally:
        if file_fd >= 0:
            os.close(file_fd)
        if directory_fd >= 0:
            os.close(directory_fd)


def _root(tmp_path: Path) -> Path:
    root = tmp_path / _DIR
    root.mkdir(mode=0o700)
    assert stat.S_IMODE(root.stat().st_mode) == 0o700
    return root


def _private_file(path: Path, data: bytes) -> None:
    path.write_bytes(data)
    path.chmod(0o600)


def _age(path: Path) -> None:
    # An old atime makes accidental read-side metadata changes observable.
    old = 1_500_000_000_000_000_000
    os.utime(path, ns=(old, old))


def test_real_v2_detached_bytes_use_noatime_then_g0_memory_only(tmp_path):
    root = _root(tmp_path)
    db, before_bytes = _synthetic_v2_rollback_image(root)
    assert db.name == _DB
    db.chmod(0o600)
    _age(db)
    _age(root)
    db_before = _identity(db.stat())
    root_before = _identity(root.stat())
    raw = _acquire_test_owned_leaf(root, _DB)
    assert raw == before_bytes
    assert _identity(db.stat()) == db_before
    assert _identity(root.stat()) == root_before
    assert _inspect_memory_image(raw).decision == "M6A_MEMORY_SQLITE_INPUT_LAB_ONLY"
    assert not (root / (_DB + "-wal")).exists()
    assert not (root / (_DB + "-shm")).exists()
    assert _PASS.endswith("LAB_ONLY")


def test_detached_context_bytes_keep_atime_and_directory_metadata(tmp_path):
    root = _root(tmp_path)
    leaf = root / _CONTEXT
    _private_file(leaf, b'{"fixture":true,"source":"unattested"}\n')
    _age(leaf)
    _age(root)
    a = _identity(leaf.stat())
    b = _identity(root.stat())
    assert _acquire_test_owned_leaf(root, _CONTEXT) == leaf.read_bytes()
    # The assertion above uses an ordinary read; keep its side effect out of
    # the measured window by refreshing the baseline instead.
    _age(leaf)
    _age(root)
    a = _identity(leaf.stat())
    b = _identity(root.stat())
    assert _acquire_test_owned_leaf(root, _CONTEXT).startswith(b'{"fixture"')
    assert _identity(leaf.stat()) == a
    assert _identity(root.stat()) == b


@pytest.mark.parametrize("bad_name", [
    "../state.sqlite", ".projectctl", "", "state.sqlite-wal",
    "synthetic-projectctl-state.sqlite/../wrong",
])
def test_reject_unallowlisted_names_before_io(tmp_path, monkeypatch, bad_name):
    root = _root(tmp_path)
    def fail_open(*args, **kwargs):
        raise AssertionError("must not open anything")
    monkeypatch.setattr(os, "open", fail_open)
    with pytest.raises(AcquisitionRefused, match="OUTSIDE_DISPOSABLE_INPUT_SCOPE"):
        _acquire_test_owned_leaf(root, bad_name)


@pytest.mark.parametrize("type_of_leaf", ["symlink", "hardlink", "fifo", "directory"])
def test_reject_nonregular_alias_and_hardlinked_leaves(tmp_path, type_of_leaf):
    root = _root(tmp_path)
    leaf = root / _CONTEXT
    if type_of_leaf == "symlink":
        (root / "target").write_bytes(b"x")
        leaf.symlink_to(root / "target")
    elif type_of_leaf == "hardlink":
        _private_file(leaf, b"x")
        os.link(leaf, root / "alias")
    elif type_of_leaf == "fifo":
        os.mkfifo(leaf, mode=0o600)
    else:
        leaf.mkdir()
    with pytest.raises(AcquisitionRefused):
        _acquire_test_owned_leaf(root, _CONTEXT)


def test_noatime_permission_failure_must_not_fallback_to_plain_read(tmp_path, monkeypatch):
    root = _root(tmp_path)
    leaf = root / _CONTEXT
    _private_file(leaf, b"PRIVATE")
    original_open = os.open
    flags_seen = []

    def deny_noatime(path, flags, *args, **kwargs):
        flags_seen.append(flags)
        if flags & os.O_NOATIME:
            raise PermissionError(errno.EPERM, "NOATIME refused")
        return original_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", deny_noatime)
    with pytest.raises(AcquisitionRefused, match="NOATIME_OR_FILE_ACCESS_DENIED"):
        _acquire_test_owned_leaf(root, _CONTEXT)
    assert flags_seen and all(flags & os.O_NOATIME for flags in flags_seen)


def test_unsupported_noatime_flag_refuses_without_open(tmp_path, monkeypatch):
    root = _root(tmp_path)
    _private_file(root / _CONTEXT, b"PRIVATE")
    monkeypatch.delattr(os, "O_NOATIME", raising=False)
    def fail_open(*args, **kwargs):
        raise AssertionError("must not fallback")
    monkeypatch.setattr(os, "open", fail_open)
    with pytest.raises(AcquisitionRefused, match="NOATIME_UNAVAILABLE"):
        _acquire_test_owned_leaf(root, _CONTEXT)


def test_replaced_leaf_during_read_is_detected(tmp_path, monkeypatch):
    root = _root(tmp_path)
    leaf = root / _CONTEXT
    _private_file(leaf, b"ORIGINAL-PRIVATE-BYTES")
    replacement = root / "replacement"
    _private_file(replacement, b"NEW-PRIVATE-BYTES")
    original_read = os.read
    swapped = []

    def swap_after_read(fd, size):
        content = original_read(fd, size)
        if not swapped:
            os.replace(replacement, leaf)
            swapped.append(True)
        return content

    monkeypatch.setattr(os, "read", swap_after_read)
    with pytest.raises(AcquisitionRefused, match="OBSERVED_METADATA_OR_ALIAS_CHANGE"):
        _acquire_test_owned_leaf(root, _CONTEXT)
    assert swapped


def test_injected_atime_or_ctime_change_is_refused(tmp_path, monkeypatch):
    root = _root(tmp_path)
    leaf = root / _CONTEXT
    _private_file(leaf, b"PRIVATE")
    original_read = os.read
    changed = []

    def change_atime(fd, size):
        content = original_read(fd, size)
        if not changed:
            _age(leaf)
            changed.append(True)
        return content

    monkeypatch.setattr(os, "read", change_atime)
    with pytest.raises(AcquisitionRefused, match="OBSERVED_METADATA_OR_ALIAS_CHANGE"):
        _acquire_test_owned_leaf(root, _CONTEXT)
    assert changed


def test_size_limit_fails_before_byte_read(tmp_path, monkeypatch):
    root = _root(tmp_path)
    _private_file(root / _CONTEXT, b"x" * 100)
    def fail_read(*args, **kwargs):
        raise AssertionError("oversized leaf must not read")
    monkeypatch.setattr(os, "read", fail_read)
    with pytest.raises(AcquisitionRefused, match="UNTRUSTED_DETACHED_LEAF"):
        _acquire_test_owned_leaf(root, _CONTEXT, byte_limit=10)


def test_unknown_or_missing_leaf_is_refused_without_creation(tmp_path):
    root = _root(tmp_path)
    assert not (root / _CONTEXT).exists()
    with pytest.raises(AcquisitionRefused, match="DETACHED_LEAF_READ_REFUSED"):
        _acquire_test_owned_leaf(root, _CONTEXT)
    assert not (root / _CONTEXT).exists()


def test_unapproved_parent_alias_is_refused(tmp_path):
    real_root = _root(tmp_path)
    _private_file(real_root / _CONTEXT, b"PRIVATE")
    other = tmp_path / "alias"
    other.mkdir(mode=0o700)
    symlink_root = other / _DIR
    symlink_root.symlink_to(real_root, target_is_directory=True)
    with pytest.raises(AcquisitionRefused):
        _acquire_test_owned_leaf(symlink_root, _CONTEXT)
