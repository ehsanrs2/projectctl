"""G11: process-local filesystem restriction on disposable G10 clones.

Only generated tmp_path fixtures, no actual project/source selection and
no global kernel policy installation. Landlock ABI >= 3, Linux x86_64.
This does not establish writer exclusion, metadata nonmutation, independent
custody, network isolation, or a general-purpose sandbox.
"""
from __future__ import annotations

import os
import platform
import subprocess
import sys

import pytest

from test_m60m6a_g10_d1_wal_bridge import (
    _NORMALIZER, _digest_pair, _fixture, _preview, _sidecar, _source_sample,
)

pytestmark = pytest.mark.skipif(
    not sys.platform.startswith("linux")
    or platform.machine() != "x86_64"
    or not all(hasattr(os, x) for x in ("O_PATH", "O_NOATIME", "O_NOFOLLOW", "geteuid"))
    or os.geteuid() == 0,
    reason="G11 requires ordinary-user Linux x86_64",
)

# Linux x86_64 syscall numbers, struct layout and rights are pinned here,
# exclusively for this test. ABI 3 includes REFER and TRUNCATE.
# Reference: https://docs.kernel.org/userspace-api/landlock.html
_CHILD_PREAMBLE = """
import ctypes as c
import errno
import os
import sqlite3
import sys
from contextlib import closing

libc = c.CDLL(None, use_errno=True)
libc.syscall.restype = c.c_long
libc.prctl.restype = c.c_int

CREATE, ADD, RESTRICT = 444, 445, 446
RIGHTS = (1 << 15) - 1

class Ruleset(c.Structure):
    _fields_ = [("handled_access_fs", c.c_uint64)]

class PathBeneath(c.Structure):
    _pack_ = 1
    _fields_ = [("allowed_access", c.c_uint64), ("parent_fd", c.c_int32)]

def call(number, *args):
    result = libc.syscall(c.c_long(number), *args)
    if result == -1:
        err = c.get_errno()
        raise OSError(err, os.strerror(err))
    return result

def restrict_to_clone():
    # A missing/disabled ABI is a distinct observation, never a fallback.
    try:
        abi = call(CREATE, c.c_void_p(), c.c_size_t(0), c.c_uint(1))
    except OSError as exc:
        if exc.errno not in (errno.ENOSYS, errno.EOPNOTSUPP, errno.EPERM):
            raise
        print("LANDLOCK_ABI_UNAVAILABLE")
        sys.exit(77)
    if abi < 3:
        print("LANDLOCK_ABI_UNAVAILABLE")
        sys.exit(77)
    rules = Ruleset(RIGHTS)
    fd = call(CREATE, c.byref(rules), c.c_size_t(c.sizeof(rules)), c.c_uint(0))
    try:
        directory = os.open(".", os.O_PATH | os.O_DIRECTORY | os.O_CLOEXEC)
        try:
            rule = PathBeneath(RIGHTS, directory)
            call(ADD, c.c_int(fd), c.c_int(1), c.byref(rule), c.c_uint(0))
        finally:
            os.close(directory)
        # Only the child changes its own no_new_privs and Landlock domain.
        if libc.prctl(c.c_int(38), c.c_ulong(1), c.c_ulong(0),
                      c.c_ulong(0), c.c_ulong(0)) != 0:
            err = c.get_errno()
            raise OSError(err, os.strerror(err))
        call(RESTRICT, c.c_int(fd), c.c_uint(0))
    finally:
        os.close(fd)
    return abi

def denied(operation):
    try:
        operation()
    except OSError as exc:
        assert exc.errno in (errno.EACCES, errno.EPERM, errno.EXDEV), exc
    else:
        raise AssertionError("expected handled access to be denied")

def open_close(path, flags):
    fd = os.open(path, flags, 0o600)
    os.close(fd)
"""

_CHILD_NORMALIZE = _CHILD_PREAMBLE + """
# Positive DAC control on synthetic sibling only, closed before restriction.
outside = "../outside/sentinel"
open_close(outside, os.O_RDONLY)
open_close(outside, os.O_WRONLY)
abi = restrict_to_clone()
denied(lambda: open_close(outside, os.O_RDONLY))
denied(lambda: open_close(outside, os.O_WRONLY))
denied(lambda: os.truncate(outside, 0))
denied(lambda: open_close("../outside/new", os.O_CREAT | os.O_WRONLY | os.O_EXCL))
denied(lambda: os.unlink(outside))
""" + _NORMALIZER + """
print("LANDLOCK_CLONE_NORMALIZED")
"""

_CHILD_INHERITED = _CHILD_PREAMBLE + """
fd = int(sys.argv[1])
restrict_to_clone()
denied(lambda: open_close("../outside/sentinel", os.O_RDONLY))
# This descriptor was deliberately opened before restriction and passed
# across exec by the test. It is NOT a safe pattern for a real reader.
assert os.read(fd, 64) == b"G11_SYNTHETIC_SENTINEL"
os.close(fd)
print("LANDLOCK_PREOPENED_FD_COUNTEREXAMPLE")
"""

_CHILD_METADATA = _CHILD_PREAMBLE + """
restrict_to_clone()
path = "../outside/sentinel"
denied(lambda: open_close(path, os.O_WRONLY))
# utime is not among the ABI-3 handled rights; intentionally test only
# a harmless synthetic sibling. Do not claim full source nonmutation.
os.utime(path, ns=(1_500_000_000_000_000_000,) * 2)
print("LANDLOCK_METADATA_COUNTEREXAMPLE")
"""


def _run(work, code, expected, *, args=(), pass_fds=()):
    result = subprocess.run(
        [sys.executable, "-I", "-c", code, *args],
        cwd=work, capture_output=True, timeout=20,
        close_fds=True, pass_fds=pass_fds, check=False,
    )
    if result.returncode == 77 and result.stdout == b"LANDLOCK_ABI_UNAVAILABLE\n":
        pytest.skip("Landlock ABI >= 3 unavailable; no isolation witness")
    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")
    assert result.stdout == expected + b"\n"


def _sibling_fixture(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir(mode=0o700)
    sentinel = outside / "sentinel"
    sentinel.write_bytes(b"G11_SYNTHETIC_SENTINEL")
    sentinel.chmod(0o600)
    work = tmp_path / "clone"
    work.mkdir(mode=0o700)
    return work, sentinel


def test_landlock_restricts_handled_access_and_preserves_g4_result(tmp_path):
    with _fixture(tmp_path) as (source, context, sample, pair, pinned,
                                _base, expected, _event_id):
        work, sentinel = _sibling_fixture(tmp_path)
        clone = work / "clone.sqlite"
        clone.write_bytes(pair[0])
        clone.chmod(0o600)
        wal = _sidecar(clone, "-wal")
        wal.write_bytes(pair[1])
        wal.chmod(0o600)
        _run(work, _CHILD_NORMALIZE, b"LANDLOCK_CLONE_NORMALIZED")
        assert not (sentinel.parent / "new").exists()
        assert sentinel.read_bytes() == b"G11_SYNTHETIC_SENTINEL"
        assert not any(_sidecar(clone, suffix).exists()
                       for suffix in ("-wal", "-shm", "-journal"))
        normalized = clone.read_bytes()
        assert normalized[18:20] == b"\x01\x01"
        assert _preview(normalized, pair[2])[0] == _preview(expected, pair[2])[0]
        assert _digest_pair(pair) == pinned
        assert _source_sample(source, context) == sample


def test_landlock_does_not_revoke_deliberately_inherited_fixture_fd(tmp_path):
    work, sentinel = _sibling_fixture(tmp_path)
    fd = os.open(sentinel, os.O_RDONLY | os.O_CLOEXEC)
    try:
        _run(work, _CHILD_INHERITED, b"LANDLOCK_PREOPENED_FD_COUNTEREXAMPLE",
             args=(str(fd),), pass_fds=(fd,))
    finally:
        os.close(fd)
    assert sentinel.read_bytes() == b"G11_SYNTHETIC_SENTINEL"


def test_landlock_handled_rights_do_not_prove_metadata_nonmutation(tmp_path):
    work, sentinel = _sibling_fixture(tmp_path)
    assert sentinel.stat().st_mtime_ns != 1_500_000_000_000_000_000
    _run(work, _CHILD_METADATA, b"LANDLOCK_METADATA_COUNTEREXAMPLE")
    assert sentinel.stat().st_mtime_ns == 1_500_000_000_000_000_000
    assert sentinel.read_bytes() == b"G11_SYNTHETIC_SENTINEL"
