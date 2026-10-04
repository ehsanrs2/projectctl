import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

from projectctl.core.errors import ClaimConflictError
from projectctl.git.ref_lease import RemoteRefLease


NOW = datetime(2026, 10, 4, 6, 0, tzinfo=timezone.utc)


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def setup_remote(tmp_path: Path) -> tuple[Path, Path, str]:
    remote = tmp_path / "remote.git"
    local = tmp_path / "local"
    subprocess.run(["git", "init", "--bare", "-q", str(remote)], check=True)
    subprocess.run(["git", "init", "-q", str(local)], check=True)
    git(local, "config", "user.email", "test@example.com")
    git(local, "config", "user.name", "Test")
    (local / "file.txt").write_text("base\n", encoding="utf-8")
    git(local, "add", "file.txt")
    git(local, "commit", "-q", "-m", "base")
    git(local, "branch", "-M", "main")
    git(local, "remote", "add", "origin", str(remote))
    git(local, "push", "-q", "origin", "main")
    return local, remote, git(local, "rev-parse", "HEAD")


def test_remote_ref_lease_acquire_conflict_release_and_aba_safety(tmp_path: Path):
    local, remote, base = setup_remote(tmp_path)
    lease = RemoteRefLease(local)
    ref = "refs/heads/projectctl/claims/issue-7"

    marker_a = lease.create_marker_commit(
        base_commit=base,
        message="claim-a",
        timestamp=NOW,
    )
    marker_b = lease.create_marker_commit(
        base_commit=base,
        message="claim-b",
        timestamp=NOW,
    )
    assert marker_a != marker_b

    assert lease.acquire(ref=ref, ownership_sha=marker_a) is True
    assert lease.observe(ref) == marker_a
    assert lease.acquire(ref=ref, ownership_sha=marker_b) is False
    assert lease.observe(ref) == marker_a

    lease.release(ref=ref, ownership_sha=marker_a)
    assert lease.observe(ref) is None

    assert lease.acquire(ref=ref, ownership_sha=marker_b) is True
    with pytest.raises(ClaimConflictError, match="ownership changed"):
        lease.release(ref=ref, ownership_sha=marker_a)
    assert lease.observe(ref) == marker_b

    lease.release(ref=ref, ownership_sha=marker_b)
    assert lease.observe(ref) is None


def test_remote_ref_release_is_idempotent_after_success(tmp_path: Path):
    local, remote, base = setup_remote(tmp_path)
    lease = RemoteRefLease(local)
    ref = "refs/heads/projectctl/claims/issue-8"
    marker = lease.create_marker_commit(
        base_commit=base,
        message="claim",
        timestamp=NOW,
    )
    assert lease.acquire(ref=ref, ownership_sha=marker) is True
    lease.release(ref=ref, ownership_sha=marker)
    lease.release(ref=ref, ownership_sha=marker)
    assert lease.observe(ref) is None


def test_marker_commit_is_deterministic_for_same_inputs(tmp_path: Path):
    local, remote, base = setup_remote(tmp_path)
    lease = RemoteRefLease(local)
    first = lease.create_marker_commit(
        base_commit=base,
        message="same-request",
        timestamp=NOW,
    )
    second = lease.create_marker_commit(
        base_commit=base,
        message="same-request",
        timestamp=NOW,
    )
    assert first == second
