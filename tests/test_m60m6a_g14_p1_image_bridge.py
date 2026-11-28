"""G14-P1: synthetic full-v2 ext4 image -> detached bytes -> G4.

P0 observed debugfs changing source-image atime. Test a narrowly scoped
alternative: acquire only a known generated regular-file image using
O_NOATIME and extract only from a new private copy. No actual source,
mount, root, block device, public API, or independent qualification.
"""
from __future__ import annotations

import errno
import hashlib
import os
import shutil
import stat
import sys
from pathlib import Path

import pytest

from scripts import m6a_g14_h2_preflight as p0
from test_m60bdiag_detached_input_gate import _source
from test_m60m6a_g10_d1_wal_bridge import _preview

pytestmark = pytest.mark.skipif(
    not sys.platform.startswith("linux") or os.geteuid() == 0
    or not all(hasattr(os, x) for x in ("O_NOATIME", "O_NOFOLLOW", "O_CLOEXEC"))
    or not all(shutil.which(x, path="/usr/sbin:/usr/bin:/sbin:/bin")
               for x in ("mke2fs", "debugfs")),
    reason="G14 P1 requires ordinary-user Linux and ext4 fixture tools",
)


def _identity(st):
    return (st.st_dev, st.st_ino, st.st_mode, st.st_uid, st.st_gid,
            st.st_nlink, st.st_size, st.st_atime_ns, st.st_mtime_ns,
            st.st_ctime_ns)


def _fixture_image(tmp_path):
    source = _source(tmp_path / "generated")
    db, context = (
        source / ".projectctl/state.sqlite",
        next((source / ".projectctl/runs").glob("*/context-manifest.json")),
    )
    expected_db, expected_context = db.read_bytes(), context.read_bytes()
    assert expected_db[18:20] == b"\x01\x01"
    assert not any(db.with_name(db.name + suffix).exists()
                   for suffix in ("-wal", "-shm", "-journal"))
    expected_preview, _ = _preview(expected_db, expected_context)
    tree = tmp_path / "tree"
    fixture = tree / "fixture"
    fixture.mkdir(parents=True, mode=0o700)
    (fixture / p0.DB).write_bytes(expected_db)
    (fixture / p0.CONTEXT).write_bytes(expected_context)

    image = tmp_path / "source.raw"
    with image.open("xb") as handle:
        handle.truncate(p0.SIZE)
    mke2fs = shutil.which("mke2fs", path="/usr/sbin:/usr/bin:/sbin:/bin")
    result = p0.tool(mke2fs, ["-q", "-t", "ext4", "-F", "-d",
                             "tree", image.name], tmp_path, timeout=60)
    assert result.returncode == 0, "synthetic image creation failed"
    image.chmod(0o400)
    os.utime(image, ns=(1_500_000_000_000_000_000, image.stat().st_mtime_ns))
    before = p0.image_sample(image)
    return image, before, expected_db, expected_context, expected_preview


def _copy_fixture_image(image: Path, work: Path, expected_digest: str):
    """Test helper; no source-path interface outside generated fixtures.

    Refuse if O_NOATIME cannot be used; never reopen using plain read.
    The expected digest is held by the test, not an independent authority.
    """
    fd = os.open(image, os.O_RDONLY | os.O_NOATIME | os.O_NOFOLLOW
                 | os.O_CLOEXEC | os.O_NONBLOCK)
    try:
        initial = os.fstat(fd)
        assert stat.S_ISREG(initial.st_mode)
        assert initial.st_uid == os.geteuid()
        assert initial.st_nlink == 1 and initial.st_size == p0.SIZE
        assert _identity(image.lstat()) == _identity(initial)

        work.mkdir(mode=0o700)
        clone = work / "clone.raw"
        digest = hashlib.sha256()
        total = 0
        with clone.open("xb") as output:
            clone.chmod(0o600)
            while True:
                chunk = os.read(fd, 1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                assert total <= p0.SIZE
                digest.update(chunk)
                assert output.write(chunk) == len(chunk)
        assert total == p0.SIZE
        assert digest.hexdigest() == expected_digest
        assert _identity(os.fstat(fd)) == _identity(initial)
        assert _identity(image.lstat()) == _identity(initial)
        assert p0.image_sample(clone)["sha256"] == expected_digest
        assert clone.stat().st_ino != initial.st_ino
        return clone
    finally:
        os.close(fd)


def _extract_clone(clone: Path):
    # Only the detached clone is passed to the filesystem parser.
    assert clone.name == "clone.raw"
    debugfs = shutil.which("debugfs", path="/usr/sbin:/usr/bin:/sbin:/bin")
    work = clone.parent
    result = p0.tool(debugfs, ["-R", "stats", clone.name], work)
    assert result.returncode == 0
    assert any(line.startswith(b"Filesystem state:") and
               line.split(b":", 1)[1].strip() == b"clean"
               for line in result.stdout.splitlines())
    for name in (p0.DB, p0.CONTEXT):
        result = p0.tool(debugfs, ["-R", "dump /fixture/" + name + " " + name,
                                   clone.name], work)
        assert result.returncode == 0
    db, context = work / p0.DB, work / p0.CONTEXT
    assert db.is_file() and context.is_file()
    assert 0 < db.stat().st_size <= 16 * 1024 * 1024
    assert 0 < context.stat().st_size <= 2 * 1024 * 1024
    return db.read_bytes(), context.read_bytes()


def test_g14_p1_clone_preserves_source_sample_and_exact_g4(tmp_path):
    image, before, expected_db, expected_context, expected = _fixture_image(tmp_path)
    clone = _copy_fixture_image(image, tmp_path / "private-work", before["sha256"])
    db, context = _extract_clone(clone)
    assert db == expected_db and context == expected_context
    assert p0.image_sample(image) == before
    assert p0.image_sample(clone)["sha256"] == before["sha256"]
    # No source image, image path, or SQLite file path enters G2/G4.
    actual, _ = _preview(db, context)
    assert actual == expected
    assert _preview(db, context)[0] == actual
    assert p0.image_sample(image) == before


def test_g14_p1_noatime_denied_has_no_plain_read_fallback(tmp_path, monkeypatch):
    image, before, *_ = _fixture_image(tmp_path)
    original_open = os.open
    attempts = []

    def guarded_open(path, flags, *args, **kwargs):
        if path == image or path == str(image):
            attempts.append(flags)
            assert flags & os.O_NOATIME
            raise PermissionError(errno.EPERM, "fixture O_NOATIME denied")
        return original_open(path, flags, *args, **kwargs)

    work = tmp_path / "must-not-create"
    with monkeypatch.context() as patch:
        patch.setattr(os, "open", guarded_open)
        with pytest.raises(PermissionError):
            _copy_fixture_image(image, work, before["sha256"])
    assert len(attempts) == 1
    assert not work.exists()
    assert p0.image_sample(image) == before


def test_g14_p1_mismatched_pin_never_yields_clone_for_extraction(tmp_path):
    image, before, *_ = _fixture_image(tmp_path)
    # This assertion is a test-held identity contrast, not authentication.
    wrong_digest = "0" * 64
    assert before["sha256"] != wrong_digest
    with pytest.raises(AssertionError):
        _copy_fixture_image(image, tmp_path / "rejected-private-work", wrong_digest)
    assert p0.image_sample(image) == before
