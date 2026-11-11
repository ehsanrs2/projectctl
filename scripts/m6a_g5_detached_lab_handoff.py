"""M6a G5: private LAB-ONLY handoff from synthetic detached file bytes.

The descriptor read helper is exactly the one previously tested in G1.
This module does NOT read real ProjectCTL source stores, authenticate origin,
establish a coherent DB/JSON epoch, expose a public source-path CLI or grant
Worker/Provider authority. It emits only G4 JSON input bytes, never stdout.
The fixed root basename and leaf names are research scope guards, not
independent proof that externally supplied files are actually synthetic.
"""
from __future__ import annotations

import base64
import errno
import json
import os
import stat
import sys
from pathlib import Path

from scripts.m6a_g4_stdin_preview import _INPUT_FORMAT, _WIRE_MAX

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
    if (not isinstance(root, Path) or not root.is_absolute()
            or root.name != _DIR or type(leaf) is not str
            or leaf not in _ALLOWED
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

_HANDOFF_DECISION = "M6A_G5_DETACHED_TEST_HANDOFF_LAB_ONLY"


def _observed_metadata(root: Path) -> tuple[tuple[int, ...], ...]:
    """Local before/after identity only: cannot detect an ABA attacker."""
    try:
        return tuple(_identity(os.lstat(root / leaf))
                     for leaf in (_DB, _CONTEXT)) + (_identity(os.lstat(root)),)
    except OSError:
        raise AcquisitionRefused("DETACHED_METADATA_UNAVAILABLE") from None


def _refuse_sqlite_sidecars(root: Path) -> None:
    """Do not read or try to recover sidecars in this rollback-only lab."""
    for suffix in ("-wal", "-shm", "-journal"):
        try:
            os.lstat(root / (_DB + suffix))
        except FileNotFoundError:
            continue
        except OSError:
            raise AcquisitionRefused("SIDE_CAR_IDENTITY_UNAVAILABLE") from None
        raise AcquisitionRefused("UNSUPPORTED_SQLITE_SIDE_CAR")


def synthetic_detached_to_g4_wire(
    root: Path, *, project_id: str, run_id: str
) -> bytes:
    """Build a G4 wire INPUT, with no stdout, external run source or writes.

    A future real source-acquisition design is a SEPARATE authorization gate.
    Both leaves are observed sequentially: no atomic epoch or hostile
    concurrency protection is claimed, even if metadata matches.
    """
    if (not sys.platform.startswith("linux")
            or not hasattr(os, "geteuid") or os.geteuid() == 0
            or not isinstance(root, Path) or not root.is_absolute()
            or root.name != _DIR
            or type(project_id) is not str or type(run_id) is not str):
        raise AcquisitionRefused("OUTSIDE_G5_LAB_INPUT_SCOPE")
    _refuse_sqlite_sidecars(root)
    before = _observed_metadata(root)
    db = _acquire_test_owned_leaf(root, _DB)
    context = _acquire_test_owned_leaf(root, _CONTEXT, byte_limit=2 * 1024 * 1024)
    _refuse_sqlite_sidecars(root)
    if before != _observed_metadata(root):
        raise AcquisitionRefused("DETACHED_CROSS_READ_CHANGE")
    wire = {
        "format": _INPUT_FORMAT,
        "project_id": project_id,
        "run_id": run_id,
        "db_b64": base64.b64encode(db).decode("ascii"),
        "artifacts_b64": {
            "context_manifest": base64.b64encode(context).decode("ascii"),
            "verification_manifest": None,
            "evidence_manifest": None,
        },
    }
    raw = (json.dumps(wire, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False) + "\n").encode("ascii")
    if len(raw) > _WIRE_MAX:
        raise AcquisitionRefused("UNBOUNDED_G5_WIRE")
    return raw
