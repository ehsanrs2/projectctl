"""G12: narrow seccomp timestamp-denial complement to G11 Landlock.

Only fresh synthetic tmp_path fixtures; no actual source or root operation.
This is a four-syscall denylist on x86_64, NOT a complete sandbox, a general
metadata nonmutation guarantee, writer exclusion, or independent custody.
"""
from __future__ import annotations

import platform
import os
import subprocess
import sys

import pytest

from test_m60m6a_g10_d1_wal_bridge import (
    _NORMALIZER, _digest_pair, _fixture, _preview, _sidecar, _source_sample,
)
from test_m60m6a_g11_landlock_clone import _CHILD_PREAMBLE, _sibling_fixture

pytestmark = pytest.mark.skipif(
    not sys.platform.startswith("linux")
    or platform.machine() != "x86_64"
    or not all(hasattr(os, x) for x in ("O_PATH", "O_NOATIME", "O_NOFOLLOW", "geteuid"))
    or os.geteuid() == 0,
    reason="G12 requires ordinary-user Linux x86_64",
)

# Load the native library before applying the Landlock filesystem policy.
# All syscall rules and targets below are fixed, test-owned, and local.
# References: seccomp_rule_add(3), seccomp_load(3), Linux Landlock API.
_SECCOMP = """
try:
    sec = c.CDLL("libseccomp.so.2")
except OSError:
    print("LIBSECCOMP_UNAVAILABLE")
    sys.exit(78)

sec.seccomp_init.argtypes = [c.c_uint32]
sec.seccomp_init.restype = c.c_void_p
sec.seccomp_release.argtypes = [c.c_void_p]
sec.seccomp_release.restype = None
sec.seccomp_syscall_resolve_name.argtypes = [c.c_char_p]
sec.seccomp_syscall_resolve_name.restype = c.c_int
sec.seccomp_rule_add_array.argtypes = [
    c.c_void_p, c.c_uint32, c.c_int, c.c_uint, c.c_void_p,
]
sec.seccomp_rule_add_array.restype = c.c_int
sec.seccomp_load.argtypes = [c.c_void_p]
sec.seccomp_load.restype = c.c_int

NAMES = (b"utime", b"utimes", b"futimesat", b"utimensat")
NUMBERS = {name: sec.seccomp_syscall_resolve_name(name) for name in NAMES}
assert all(number >= 0 for number in NUMBERS.values())
assert len(set(NUMBERS.values())) == len(NAMES)

def prepare_filter():
    # SCMP_ACT_ALLOW except exactly the selected timestamp setters.
    # SCMP_ACT_ERRNO(EPERM) returns a distinctive typed refusal.
    ctx = sec.seccomp_init(0x7fff0000)
    assert ctx, "seccomp_init failed"
    try:
        for number in NUMBERS.values():
            rc = sec.seccomp_rule_add_array(
                ctx, 0x00050000 | errno.EPERM, number, 0, None,
            )
            assert rc == 0, ("seccomp_rule_add_array", rc)
        return ctx
    except BaseException:
        sec.seccomp_release(ctx)
        raise

def load_filter(ctx):
    # G11's restrict_to_clone set PR_SET_NO_NEW_PRIVS on this child.
    try:
        rc = sec.seccomp_load(ctx)
        assert rc == 0, ("seccomp_load", rc)
    finally:
        sec.seccomp_release(ctx)

def must_eperm(operation):
    try:
        operation()
    except OSError as exc:
        assert exc.errno == errno.EPERM, exc
    else:
        raise AssertionError("expected seccomp EPERM")

def identity(path):
    st = os.stat(path)
    return (st.st_dev, st.st_ino, st.st_mode, st.st_size,
            st.st_atime_ns, st.st_mtime_ns, st.st_ctime_ns)

class TimePair(c.Structure):
    _fields_ = [("first", c.c_long), ("second", c.c_long)]

def set_raw_timestamp(name, path, seconds):
    # Native x86_64 ABI: utimbuf, timeval[2], timespec[2].
    # Zero subsecond fields make the expected timestamps portable across
    # the supported fixture filesystems; no time32 compat path is claimed.
    encoded = c.c_char_p(path)
    number = NUMBERS[name]
    if name == b"utime":
        values = TimePair(seconds, seconds)
        call(number, encoded, c.byref(values))
    elif name == b"utimes":
        values = (TimePair * 2)(TimePair(seconds, 0), TimePair(seconds, 0))
        call(number, encoded, c.byref(values))
    elif name == b"futimesat":
        values = (TimePair * 2)(TimePair(seconds, 0), TimePair(seconds, 0))
        call(number, c.c_int(-100), encoded, c.byref(values))
    elif name == b"utimensat":
        values = (TimePair * 2)(TimePair(seconds, 0), TimePair(seconds, 0))
        call(number, c.c_int(-100), encoded, c.byref(values), c.c_int(0))
    else:
        raise AssertionError("unexpected timestamp syscall")
"""

_TIMESTAMP_CHILD = _CHILD_PREAMBLE + _SECCOMP + """
ctx = prepare_filter()
restrict_to_clone()
outside = "../outside/sentinel"
inside = "inside-clock"
denied(lambda: open_close(outside, os.O_WRONLY))

# Same child, same path, same syscall and valid input before/after seccomp.
# Landlock alone permits these timestamp changes on the disposable file.
for i, name in enumerate(NAMES):
    seconds = 1500000010 + i
    set_raw_timestamp(name, os.fsencode(outside), seconds)
    st = os.stat(outside)
    assert st.st_mtime_ns == seconds * 10**9
    assert st.st_atime_ns == seconds * 10**9

outside_before = identity(outside)
inside_before = identity(inside)
load_filter(ctx)
for name in NAMES:
    must_eperm(lambda: set_raw_timestamp(name, os.fsencode(outside), 1600000000))
    assert identity(outside) == outside_before

# Path and descriptor Python wrappers, including an in-clone operation:
# seccomp is not path-sensitive and also denies these inside the clone.
must_eperm(lambda: os.utime(outside, ns=(1600000000000000000,) * 2))
must_eperm(lambda: os.utime(inside, ns=(1600000000000000000,) * 2))
fd = os.open(inside, os.O_RDONLY | os.O_CLOEXEC)
try:
    must_eperm(lambda: os.utime(fd, ns=(1600000000000000000,) * 2))
finally:
    os.close(fd)
assert identity(outside) == outside_before
assert identity(inside) == inside_before
print("G12_TIMESTAMP_SYSCALLS_DENIED")
"""

_NORMALIZE_CHILD = _CHILD_PREAMBLE + _SECCOMP + """
ctx = prepare_filter()
restrict_to_clone()
load_filter(ctx)
outside = "../outside/sentinel"
denied(lambda: open_close(outside, os.O_RDONLY))
denied(lambda: open_close(outside, os.O_WRONLY))
must_eperm(lambda: os.utime(outside, ns=(1600000000000000000,) * 2))
""" + _NORMALIZER + """
print("G12_COMBINED_CLONE_NORMALIZED")
"""


def _run(work, code, expected):
    result = subprocess.run(
        [sys.executable, "-I", "-c", code],
        cwd=work, capture_output=True, timeout=20,
        close_fds=True, check=False,
    )
    if result.returncode == 77 and result.stdout == b"LANDLOCK_ABI_UNAVAILABLE\n":
        pytest.skip("Landlock ABI >= 3 unavailable; no G12 witness")
    if result.returncode == 78 and result.stdout == b"LIBSECCOMP_UNAVAILABLE\n":
        pytest.skip("libseccomp unavailable; no G12 witness")
    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")
    assert result.stdout == expected + b"\n"


def test_seccomp_denies_four_native_timestamp_syscalls_and_python_wrappers(tmp_path):
    work, sentinel = _sibling_fixture(tmp_path)
    inside = work / "inside-clock"
    inside.write_bytes(b"G12_INSIDE_CLOCK")
    inside.chmod(0o600)
    os.utime(inside, ns=(1_500_000_000_000_000_000,) * 2)
    before = inside.stat()
    _run(work, _TIMESTAMP_CHILD, b"G12_TIMESTAMP_SYSCALLS_DENIED")

    # Check before reading file data (which may legitimately update atime).
    st = sentinel.stat()
    assert st.st_atime_ns == 1_500_000_013_000_000_000
    assert st.st_mtime_ns == 1_500_000_013_000_000_000
    after = inside.stat()
    assert (after.st_atime_ns, after.st_mtime_ns, after.st_ctime_ns) == (
        before.st_atime_ns, before.st_mtime_ns, before.st_ctime_ns,
    )
    assert sentinel.read_bytes() == b"G11_SYNTHETIC_SENTINEL"
    assert inside.read_bytes() == b"G12_INSIDE_CLOCK"


def test_combined_landlock_seccomp_preserves_exact_g4_diagnostic(tmp_path):
    with _fixture(tmp_path) as (source, context, sample, pair, pinned,
                                _base, expected, _event_id):
        work, sentinel = _sibling_fixture(tmp_path)
        clone = work / "clone.sqlite"
        clone.write_bytes(pair[0])
        clone.chmod(0o600)
        wal = _sidecar(clone, "-wal")
        wal.write_bytes(pair[1])
        wal.chmod(0o600)
        before = sentinel.stat()
        _run(work, _NORMALIZE_CHILD, b"G12_COMBINED_CLONE_NORMALIZED")
        after = sentinel.stat()
        assert (after.st_atime_ns, after.st_mtime_ns, after.st_ctime_ns) == (
            before.st_atime_ns, before.st_mtime_ns, before.st_ctime_ns,
        )
        assert sentinel.read_bytes() == b"G11_SYNTHETIC_SENTINEL"
        assert not any(_sidecar(clone, suffix).exists()
                       for suffix in ("-wal", "-shm", "-journal"))
        normalized = clone.read_bytes()
        assert normalized[18:20] == b"\x01\x01"
        assert _preview(normalized, pair[2])[0] == _preview(expected, pair[2])[0]
        assert _digest_pair(pair) == pinned
        assert _source_sample(source, context) == sample
