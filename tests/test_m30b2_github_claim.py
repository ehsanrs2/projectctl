from datetime import datetime, timezone
from pathlib import Path

import pytest

from projectctl.core.digest import digest
from projectctl.core.errors import ClaimConflictError, TaskStoreError
from projectctl.integrations.github.claim import GitHubTaskClaimer
from projectctl.schemas.task_claim import TaskClaim, TaskClaimRequest


NOW = datetime(2026, 10, 4, 6, 0, tzinfo=timezone.utc)
BASE = "a" * 40


class FakeLease:
    def __init__(self):
        self.current = {}
        self.releases = []
        self.acquire_calls = []
        self.remote_target = BASE
        self.url = "git@github.com:acme/widget.git"

    def remote_url(self):
        return self.url

    def remote_branch(self, branch_name):
        return self.remote_target

    def create_marker_commit(self, *, base_commit, message, timestamp):
        token = message.split('"claim_token":"', 1)[1].split('"', 1)[0]
        return ("1" if token.startswith("a") else "2") * 40

    def observe(self, ref):
        return self.current.get(ref)

    def acquire(self, *, ref, ownership_sha):
        self.acquire_calls.append((ref, ownership_sha))
        if ref in self.current:
            return self.current[ref] == ownership_sha
        self.current[ref] = ownership_sha
        return True

    def release(self, *, ref, ownership_sha):
        current = self.current.get(ref)
        if current is None:
            return
        if current != ownership_sha:
            raise ClaimConflictError("ownership changed")
        self.releases.append((ref, ownership_sha))
        del self.current[ref]


def request(token="a" * 32):
    return TaskClaimRequest(
        task_id="gh-7",
        run_id="run-1",
        actor="projectctl:test",
        base_commit=BASE,
        integration_target_ref="main",
        claim_token=token,
        requested_at=NOW,
    )


def test_github_claim_acquires_idempotently_and_records_remote_proof(tmp_path: Path):
    lease = FakeLease()
    claimer = GitHubTaskClaimer(
        tmp_path,
        repository="acme/widget",
        lease=lease,
    )
    req = request()
    first = claimer.claim(req)
    second = claimer.claim(req)

    assert first.acquired is True
    assert second.acquired is True
    assert first.ownership_ref == "refs/heads/projectctl/claims/issue-7"
    assert first.ownership_sha == "1" * 40
    assert first.request_digest == digest(req)
    assert first.repository == "acme/widget"


def test_github_claim_conflict_is_nonexceptional_result(tmp_path: Path):
    lease = FakeLease()
    ref = "refs/heads/projectctl/claims/issue-7"
    lease.current[ref] = "f" * 40
    claimer = GitHubTaskClaimer(tmp_path, repository="acme/widget", lease=lease)

    claim = claimer.claim(request())

    assert claim.acquired is False
    assert "already claimed" in claim.reason
    assert lease.current[ref] == "f" * 40


def test_github_claim_requires_remote_target_to_match_execution_base(tmp_path: Path):
    lease = FakeLease()
    lease.remote_target = "b" * 40
    claimer = GitHubTaskClaimer(tmp_path, repository="acme/widget", lease=lease)

    with pytest.raises(TaskStoreError, match="differs from the execution base"):
        claimer.claim(request())


def test_github_claim_requires_origin_to_match_configured_repository(tmp_path: Path):
    lease = FakeLease()
    lease.url = "git@github.com:other/widget.git"
    claimer = GitHubTaskClaimer(tmp_path, repository="acme/widget", lease=lease)

    with pytest.raises(TaskStoreError, match="does not match"):
        claimer.claim(request())


def test_github_release_only_deletes_exact_owned_ref(tmp_path: Path):
    lease = FakeLease()
    claimer = GitHubTaskClaimer(tmp_path, repository="acme/widget", lease=lease)
    claim = claimer.claim(request())
    claimer.release(claim)
    assert lease.current == {}
    assert lease.releases == [
        ("refs/heads/projectctl/claims/issue-7", "1" * 40)
    ]


def test_github_release_refuses_wrong_provider_or_unacquired_claim(tmp_path: Path):
    lease = FakeLease()
    claimer = GitHubTaskClaimer(tmp_path, repository="acme/widget", lease=lease)
    req = request()
    bad = TaskClaim(
        provider="github",
        task_id=req.task_id,
        run_id=req.run_id,
        actor=req.actor,
        base_commit=req.base_commit,
        integration_target_ref=req.integration_target_ref,
        claim_token=req.claim_token,
        request_digest=digest(req),
        acquired=False,
        observed_at=NOW,
        repository="acme/widget",
        ownership_ref="refs/heads/projectctl/claims/issue-7",
        ownership_sha="1" * 40,
    )
    with pytest.raises(TaskStoreError, match="not acquired"):
        claimer.release(bad)
