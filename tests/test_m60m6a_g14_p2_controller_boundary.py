"""G14-P2: opt-in hosted-runner synthetic read-only bind boundary.

Only generated fixtures, Docker daemon/host are trusted for this experiment.
No actual source, host-root commands, device, privileged container or
independent administrative witness. A read-only view is not a frozen source:
the second test deliberately demonstrates the outside-host FD counterexample.
"""
from __future__ import annotations

import os
import re
import select
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import m6a_g14_h2_preflight as p0
from test_m60m6a_g14_p1_image_bridge import _fixture_image, _extract_clone, _identity
from test_m60m6a_g10_d1_wal_bridge import _preview

pytestmark = pytest.mark.skipif(
    os.environ.get("PROJECTCTL_G14_P2_SYNTHETIC_CI") != "1",
    reason="G14 P2 dedicated disposable Docker CI only",
)

_CHILD = """
import errno
import os
import stat
import sys

path = "/source.raw"
assert os.statvfs(path).f_flag & os.ST_RDONLY
st = os.stat(path)
assert stat.S_ISREG(st.st_mode)
assert st.st_uid == os.geteuid()
assert st.st_mode & stat.S_IWUSR  # DAC owner write permission is present

def denied(operation):
    try:
        operation()
    except OSError as exc:
        assert exc.errno == errno.EROFS, exc
    else:
        raise AssertionError("read-only view allowed mutation")

def write_open():
    fd = os.open(path, os.O_WRONLY)
    os.close(fd)

denied(write_open)
denied(lambda: os.truncate(path, 0))
denied(lambda: os.chmod(path, 0o400))
denied(lambda: os.utime(path, ns=(1600000000000000000,) * 2))
"""

_CAPTURE = _CHILD + """
assert st.st_size == 64 * 1024 * 1024
fd = os.open(path, os.O_RDONLY | os.O_NOATIME | os.O_NOFOLLOW | os.O_CLOEXEC)
try:
    total = 0
    while True:
        chunk = os.read(fd, 1024 * 1024)
        if not chunk:
            break
        total += len(chunk)
        assert total <= st.st_size
        assert sys.stdout.buffer.write(chunk) == len(chunk)
    assert total == st.st_size
    sys.stdout.buffer.flush()
finally:
    os.close(fd)
print("G14_P2_RO_OPEN_TRUNCATE_CHMOD_UTIME_DENIED", file=sys.stderr)
"""

_HOST_FD_CONTROL = _CHILD + """
import select
fd = os.open(path, os.O_RDONLY | os.O_NOATIME | os.O_CLOEXEC)
try:
    assert os.pread(fd, 1, 0) == b"A"
    print("READY", flush=True)
    assert select.select([sys.stdin], [], [], 30)[0]
    assert sys.stdin.readline() == "GO\\n"
    assert os.pread(fd, 1, 0) == b"B"
    print("G14_P2_HOST_FD_MUTATION_VISIBLE", flush=True)
finally:
    os.close(fd)
"""


def _command(image: Path, code: str, *, interactive=False):
    # The dedicated workflow supplies the locally pulled immutable image ID.
    container = os.environ.get("PROJECTCTL_G14_P2_IMAGE_ID", "")
    assert re.fullmatch(r"sha256:[0-9a-f]{64}", container)
    assert sys.platform.startswith("linux") and os.geteuid() != 0
    docker = shutil.which("docker")
    assert docker
    assert image.is_file() and not image.is_symlink()
    args = [docker, "run", "--rm", "--network", "none", "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges", "--read-only",
            "--user", f"{os.geteuid()}:{os.getegid()}",
            "--mount", f"type=bind,source={image},target=/source.raw,readonly"]
    if interactive:
        args.append("-i")
    return args + [container, "python", "-I", "-B", "-u", "-c", code]


def test_g14_p2_readonly_container_capture_preserves_full_g4(tmp_path):
    image, _, expected_db, expected_context, expected = _fixture_image(tmp_path)
    # Give the owner DAC write access, so the read-only mount itself is the
    # tested restriction, not a 0400 mode bit. Preparation precedes sampling.
    image.chmod(0o600)
    with os.fdopen(os.open(image, os.O_WRONLY | os.O_CLOEXEC), "wb"):
        pass  # os.open did not request truncation; no bytes written
    before = p0.image_sample(image)
    identity = _identity(image.lstat())
    result = subprocess.run(
        _command(image, _CAPTURE), capture_output=True, timeout=90,
        close_fds=True, check=False,
    )
    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")
    assert result.stderr == b"G14_P2_RO_OPEN_TRUNCATE_CHMOD_UTIME_DENIED\n"
    assert len(result.stdout) == p0.SIZE
    assert p0.image_sample(image) == before
    assert _identity(image.lstat()) == identity

    work = tmp_path / "host-private-copy"
    work.mkdir(mode=0o700)
    clone = work / "clone.raw"
    with clone.open("xb") as target:
        assert target.write(result.stdout) == p0.SIZE
    clone.chmod(0o600)
    assert p0.image_sample(clone)["sha256"] == before["sha256"]
    db, context = _extract_clone(clone)
    assert (db, context) == (expected_db, expected_context)
    assert _preview(db, context)[0] == expected
    assert p0.image_sample(image) == before
    assert _identity(image.lstat()) == identity
    print("G14_P2_RO_CAPTURE_G4_MATCH_SOURCE_SAMPLE_EQUAL")


def test_g14_p2_readonly_view_does_not_exclude_preopened_host_writer(tmp_path):
    # Separate sacrificial file, never the positive-case ext4 image.
    image = tmp_path / "host-fd-counterexample.raw"
    image.write_bytes(b"A")
    image.chmod(0o600)
    fd = os.open(image, os.O_WRONLY | os.O_CLOEXEC)
    process = None
    try:
        process = subprocess.Popen(
            _command(image, _HOST_FD_CONTROL, interactive=True),
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, close_fds=True,
        )
        assert select.select([process.stdout], [], [], 60)[0], "no container ready"
        assert process.stdout.readline() == b"READY\n"
        # Outside the container, the already-open descriptor still works
        # while the actor's read-only view is active. The child sees new data.
        assert os.pwrite(fd, b"B", 0) == 1
        os.fsync(fd)
        stdout, stderr = process.communicate(input=b"GO\n", timeout=40)
        assert process.returncode == 0, stderr.decode("utf-8", "replace")
        assert stdout == b"G14_P2_HOST_FD_MUTATION_VISIBLE\n"
        assert image.read_bytes() == b"B"
        print("G14_P2_RO_VIEW_IS_NOT_HOST_WRITER_EXCLUSION")
    finally:
        os.close(fd)
        if process is not None and process.poll() is None:
            process.kill()
            process.communicate(timeout=10)
