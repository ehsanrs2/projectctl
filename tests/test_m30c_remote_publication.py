import subprocess
from datetime import datetime, timezone
from pathlib import Path

from projectctl.git.publication import GitRemotePublisher
from projectctl.schemas.delivery import PublicationRequest


NOW = datetime(2026, 10, 4, 8, 0, tzinfo=timezone.utc)


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def setup_remote(tmp_path: Path):
    remote = tmp_path / "remote.git"
    local = tmp_path / "local"
    subprocess.run(["git", "init", "--bare", "-q", str(remote)], check=True)
    subprocess.run(["git", "init", "-q", str(local)], check=True)
    git(local, "config", "user.email", "test@example.com")
    git(local, "config", "user.name", "Test")
    (local / "app.py").write_text("value = 1\n", encoding="utf-8")
    git(local, "add", "app.py")
    git(local, "commit", "-q", "-m", "base")
    git(local, "branch", "-M", "main")
    git(local, "remote", "add", "origin", str(remote))
    git(local, "push", "-q", "origin", "main")
    base = git(local, "rev-parse", "HEAD")

    git(local, "checkout", "-qb", "candidate")
    (local / "app.py").write_text("value = 2\n", encoding="utf-8")
    git(local, "add", "app.py")
    git(local, "commit", "-q", "-m", "candidate")
    candidate = git(local, "rev-parse", "HEAD")
    return local, remote, base, candidate


def request(base: str, candidate: str) -> PublicationRequest:
    return PublicationRequest(
        run_id="run-1",
        task_id="gh-7",
        provider="github",
        repository="acme/widget",
        remote_name="origin",
        target_ref="main",
        base_commit=base,
        candidate_commit=candidate,
        evidence_manifest=".projectctl/runs/run-1/evidence-manifest.json",
        evidence_digest="sha256:evidence",
        requested_at=NOW,
    )


def test_remote_publisher_is_exact_base_and_idempotently_observable(tmp_path: Path, monkeypatch):
    local, remote, base, candidate = setup_remote(tmp_path)
    publisher = GitRemotePublisher(local, repository="acme/widget")
    monkeypatch.setattr(publisher, "_assert_remote_identity", lambda: None)

    before = publisher.reconcile(request(base, candidate))
    assert before.published is False
    assert before.remote_after == base

    published = publisher.publish(request(base, candidate))
    assert published.published is True
    assert published.remote_before == base
    assert published.remote_after == candidate
    assert git(remote, "rev-parse", "refs/heads/main") == candidate

    repeated = publisher.publish(request(base, candidate))
    assert repeated.published is True
    assert repeated.remote_after == candidate


def test_remote_publisher_refuses_stale_target_without_overwrite(tmp_path: Path, monkeypatch):
    local, remote, base, candidate = setup_remote(tmp_path)

    git(local, "checkout", "-q", "main")
    (local / "other.py").write_text("external = True\n", encoding="utf-8")
    git(local, "add", "other.py")
    git(local, "commit", "-q", "-m", "external")
    external = git(local, "rev-parse", "HEAD")
    git(local, "push", "-q", "origin", "main")

    publisher = GitRemotePublisher(local, repository="acme/widget")
    monkeypatch.setattr(publisher, "_assert_remote_identity", lambda: None)
    result = publisher.publish(request(base, candidate))

    assert result.published is False
    assert result.remote_before == external
    assert result.remote_after == external
    assert git(remote, "rev-parse", "refs/heads/main") == external
