import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from projectctl.application.claims import persist_claim, persist_claim_request
from projectctl.application.integration import integrate_run
from projectctl.application.recovery import recover_run
from projectctl.core.digest import digest
from projectctl.core.enums import (
    ModelProfile,
    ReasoningLevel,
    RunStatus,
    VerificationCheckStatus,
    WorkerResultStatus,
    WorkerStrategyKind,
)
from projectctl.core.errors import IntegrationError
from projectctl.git import WorktreeManager
from projectctl.git.review import review_source_branch
from projectctl.integrations.delivery import code_delivery_policy
from projectctl.integrations.review.github import GitHubReviewDeliveryAdapter
from projectctl.integrations.review.gitlab import GitLabReviewDeliveryAdapter
from projectctl.project.bootstrap import initialize_project
from projectctl.schemas.delivery import ReviewReceipt, ReviewRequest
from projectctl.schemas.evidence import EvidenceManifest
from projectctl.schemas.execution import ExecutionPlan, WorkerResult
from projectctl.schemas.run import RunManifest, WorkerDescriptor
from projectctl.schemas.task_claim import TaskClaim, TaskClaimRequest
from projectctl.schemas.verification import VerificationCheckResult, VerificationManifest
from projectctl.storage.runs import RunStore
from projectctl.verification.diff import committed_diff_digest


NOW = datetime(2026, 10, 5, 9, 0, tzinfo=timezone.utc)
TEAM_ID = "9cfb482a-81e3-4154-b5b9-2c805e70a02d"


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def review_request(provider="github"):
    return ReviewRequest(
        run_id="run-review-1",
        task_id="lin-ENG-1",
        task_provider="linear",
        review_provider=provider,
        remote_name="origin",
        remote_identity=(
            "github.com/acme/widget"
            if provider == "github"
            else "gitlab.com/acme/widget"
        ),
        source_ref="projectctl/review/run-review-1-bbbbbbbbbbbb",
        target_ref="main",
        base_commit="a" * 40,
        candidate_commit="b" * 40,
        evidence_manifest=".projectctl/runs/run-review-1/evidence-manifest.json",
        evidence_digest="evidence",
        title="ProjectCTL: lin-ENG-1",
        body="verified candidate",
        requested_at=NOW,
    )


def test_review_source_branch_is_deterministic_and_candidate_bound():
    first = review_source_branch("run:unsafe/name", "a" * 40)
    second = review_source_branch("run:unsafe/name", "a" * 40)
    other = review_source_branch("run:unsafe/name", "b" * 40)

    assert first == second
    assert first.startswith("projectctl/review/run-unsafe-name-")
    assert first != other


class FakeGitHubAdapter(GitHubReviewDeliveryAdapter):
    def __init__(self, root: Path, payload):
        self.project_root = root
        self.remote_name = "origin"
        self.remote_identity = "github.com/acme/widget"
        self.repository = "acme/widget"
        self.owner = "acme"
        self.executable = "gh-test"
        self.timeout_seconds = 1
        self.payload = payload

    def _api(self, method, endpoint, payload=None):
        del method, endpoint, payload
        return self.payload


def test_github_review_reconcile_binds_exact_head(tmp_path: Path):
    request = review_request("github")
    raw = {
        "number": 7,
        "html_url": "https://github.com/acme/widget/pull/7",
        "state": "open",
        "merged_at": None,
        "merge_commit_sha": None,
        "head": {"ref": request.source_ref, "sha": request.candidate_commit},
        "base": {"ref": request.target_ref},
    }
    adapter = FakeGitHubAdapter(tmp_path, [raw])

    receipt = adapter.reconcile(request)

    assert receipt.state == "open"
    assert receipt.review_id == "7"
    assert receipt.head_commit == request.candidate_commit
    assert not receipt.delivery_complete

    raw["head"]["sha"] = "c" * 40
    with pytest.raises(IntegrationError, match="verified candidate"):
        adapter.reconcile(request)


class FakeGitLabAdapter(GitLabReviewDeliveryAdapter):
    def __init__(self, root: Path, payload):
        super().__init__(
            root,
            remote_name="origin",
            remote_identity="gitlab.com/acme/widget",
            token="test-token",
        )
        self.payload = payload

    def _api(self, method, endpoint, payload=None, query=None):
        del method, endpoint, payload, query
        return self.payload


def test_gitlab_review_reconcile_binds_exact_head(tmp_path: Path):
    request = review_request("gitlab")
    raw = {
        "iid": 9,
        "web_url": "https://gitlab.com/acme/widget/-/merge_requests/9",
        "state": "merged",
        "source_branch": request.source_ref,
        "target_branch": request.target_ref,
        "sha": request.candidate_commit,
        "merge_commit_sha": request.candidate_commit,
        "merged_at": "2026-10-05T09:10:00Z",
    }
    adapter = FakeGitLabAdapter(tmp_path, [raw])

    receipt = adapter.reconcile(request)

    assert receipt.state == "merged"
    assert receipt.review_id == "9"
    assert receipt.head_commit == request.candidate_commit
    assert receipt.merge_commit == request.candidate_commit
    assert not receipt.delivery_complete


def test_unknown_review_host_remains_fail_closed(tmp_path: Path):
    ctl = tmp_path / ".projectctl"
    ctl.mkdir()
    config = {
        "schema_kind": "projectctl.project_config",
        "schema_version": 6,
        "project": {"id": "demo"},
        "task_store": {
            "provider": "linear",
            "team": TEAM_ID,
            "repository": None,
            "cache_max_age_seconds": 30,
        },
        "code_transport": {
            "mode": "git_remote",
            "remote_name": "origin",
            "remote_identity": "git.example.internal/acme/widget",
        },
        "code_delivery": {"mode": "review_required"},
    }
    (ctl / "config.yaml").write_text(
        yaml.safe_dump(config, sort_keys=False),
        encoding="utf-8",
    )

    policy = code_delivery_policy(tmp_path)

    assert policy.mode == "review_required"
    assert not policy.supported
    assert policy.review_provider is None


class FakeClaimer:
    def __init__(self):
        self.released = []

    def validate(self, claim):
        return True

    def release(self, claim):
        self.released.append(claim.task_id)


class FakeCompletionWriter:
    def __init__(self):
        self.completed = []

    def complete(self, task_id, *, evidence):
        self.completed.append((task_id, evidence))

    def mark_needs_decision(self, task_id, *, reason):
        raise AssertionError(f"unexpected needs-decision: {task_id} {reason}")


class FakeReviewer:
    def __init__(self):
        self.state = "open"
        self.review_id = "17"
        self.review_url = "https://gitlab.com/acme/widget/-/merge_requests/17"
        self.created = 0
        self.reconciled = 0

    def _receipt(self, request):
        merged = self.state == "merged"
        return ReviewReceipt(
            run_id=request.run_id,
            task_id=request.task_id,
            review_provider="gitlab",
            request_digest=digest(request),
            review_id=self.review_id,
            review_url=self.review_url,
            source_ref=request.source_ref,
            target_ref=request.target_ref,
            candidate_commit=request.candidate_commit,
            head_commit=request.candidate_commit,
            merge_commit=request.candidate_commit if merged else None,
            state=self.state,
            merged_at=NOW if merged else None,
            observed_at=NOW,
            reason=None if merged else "waiting",
        )

    def reconcile(self, request):
        self.reconciled += 1
        if self.created == 0:
            return ReviewReceipt(
                run_id=request.run_id,
                task_id=request.task_id,
                review_provider="gitlab",
                request_digest=digest(request),
                source_ref=request.source_ref,
                target_ref=request.target_ref,
                candidate_commit=request.candidate_commit,
                state="missing",
                observed_at=NOW,
                reason="missing",
            )
        return self._receipt(request)

    def request_review(self, request):
        self.created += 1
        return self._receipt(request)


class FakeReviewTransport:
    def __init__(self, root, *, remote_name, remote_identity):
        self.root = root
        self.remote_name = remote_name
        self.remote_identity = remote_identity

    def sync_merged_target(self, request, receipt):
        assert receipt.state == "merged"
        assert receipt.head_commit == request.candidate_commit
        return request.candidate_commit


def setup_review_run(tmp_path: Path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "config", "user.email", "test@example.com")
    git(repo, "config", "user.name", "Test")
    monkeypatch.setenv("PROJECTCTL_HOME", str(tmp_path / "home"))
    initialize_project(repo)

    config_path = repo / ".projectctl" / "config.yaml"
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    raw["task_store"] = {
        "provider": "linear",
        "repository": None,
        "team": TEAM_ID,
        "cache_max_age_seconds": 30,
    }
    raw["code_transport"] = {
        "mode": "git_remote",
        "remote_name": "origin",
        "remote_identity": "gitlab.com/acme/widget",
    }
    raw["code_delivery"] = {"mode": "review_required"}
    config_path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")

    (repo / ".gitignore").write_text(".projectctl/\n", encoding="utf-8")
    (repo / "app.py").write_text("value = 1\n", encoding="utf-8")
    git(repo, "add", ".gitignore", "app.py", "AGENTS.md", "docs")
    git(repo, "commit", "-q", "-m", "baseline")
    base = git(repo, "rev-parse", "HEAD")
    target = git(repo, "branch", "--show-current")

    run_id = "run-review-delivery"
    branch = f"projectctl/run/{run_id}"
    worktree = WorktreeManager(repo).create(
        worktree_id=run_id,
        branch_name=branch,
        base_commit=base,
    ).path
    git(worktree, "config", "user.email", "test@example.com")
    git(worktree, "config", "user.name", "Test")
    (worktree / "app.py").write_text("value = 2\n", encoding="utf-8")
    git(worktree, "add", "app.py")
    git(worktree, "commit", "-q", "-m", "candidate")
    candidate = git(worktree, "rev-parse", "HEAD")

    worker = WorkerDescriptor(
        provider="codex",
        model_profile=ModelProfile.BALANCED,
        reasoning=ReasoningLevel.MEDIUM,
    )
    plan = ExecutionPlan(
        plan_id="ep-review-delivery",
        project_id="repo",
        task_id="lin-ENG-1",
        scheduler_decision_digest="sched",
        task_snapshot_digest="tasks",
        project_state_digest="state",
        quota_snapshot_digest="quota",
        capability_snapshot_digest="caps",
        strategy_decision_digest="strategy",
        strategy=WorkerStrategyKind.DIRECT,
        base_commit=base,
        integration_target_ref=target,
        worker=worker,
        verification_profile="default",
        created_at=NOW,
    )
    worker_result = WorkerResult(
        run_id=run_id,
        task_id="lin-ENG-1",
        status=WorkerResultStatus.IMPLEMENTED,
        summary="done",
        worker_thread_id="thr-review",
        completed_at=NOW,
    )
    verification = VerificationManifest(
        run_id=run_id,
        task_id="lin-ENG-1",
        base_commit=base,
        workspace_state_digest="workspace",
        profile="default",
        profile_digest="profile",
        changed_paths=["app.py"],
        started_at=NOW,
        completed_at=NOW,
        checks=[
            VerificationCheckResult(
                id="pytest",
                argv=["pytest"],
                status=VerificationCheckStatus.PASSED,
                exit_code=0,
                duration_ms=1,
            )
        ],
        overall_pass=True,
    )
    evidence = EvidenceManifest(
        run_id=run_id,
        task_id="lin-ENG-1",
        base_commit=base,
        candidate_commit=candidate,
        diff_digest=committed_diff_digest(worktree, base, candidate),
        workspace_state_digest="workspace",
        worker_result_digest=digest(worker_result),
        verification_manifest_digest=digest(verification),
        verification_profile_digest="profile",
        changed_paths=["app.py"],
        overall_pass=True,
        generated_at=NOW,
    )

    run_dir = repo / ".projectctl" / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    for name, value in [
        ("execution-plan.json", plan),
        ("worker-result.json", worker_result),
        ("verification-manifest.json", verification),
        ("evidence-manifest.json", evidence),
    ]:
        (run_dir / name).write_text(
            json.dumps(value.model_dump(mode="json")),
            encoding="utf-8",
        )

    RunStore(repo).create(
        RunManifest(
            run_id=run_id,
            task_id="lin-ENG-1",
            execution_plan_digest=digest(plan),
            status=RunStatus.READY_TO_INTEGRATE,
            base_commit=base,
            candidate_commit=candidate,
            branch_name=branch,
            worktree_id=run_id,
            worker=worker,
            evidence_manifest=f".projectctl/runs/{run_id}/evidence-manifest.json",
        ),
        worktree_path=worktree,
        now=NOW,
    )

    claim_request = TaskClaimRequest(
        task_id="lin-ENG-1",
        run_id=run_id,
        actor="projectctl:test",
        base_commit=base,
        integration_target_ref=target,
        claim_token="d" * 32,
        requested_at=NOW,
    )
    claim = TaskClaim(
        provider="linear",
        task_id=claim_request.task_id,
        run_id=run_id,
        actor=claim_request.actor,
        base_commit=base,
        integration_target_ref=target,
        claim_token=claim_request.claim_token,
        request_digest=digest(claim_request),
        acquired=True,
        observed_at=NOW,
        repository="gitlab.com/acme/widget",
        ownership_ref="refs/heads/projectctl/claims/linear/test",
        ownership_sha="e" * 40,
    )
    store = RunStore(repo)
    persist_claim_request(repo, store=store, request=claim_request)
    persist_claim(repo, store=store, request=claim_request, claim=claim)
    return repo, run_id, candidate, target


def test_review_delivery_waits_then_recovery_completes_after_external_merge(
    tmp_path: Path,
    monkeypatch,
):
    repo, run_id, candidate, target = setup_review_run(tmp_path, monkeypatch)
    reviewer = FakeReviewer()
    claimer = FakeClaimer()
    writer = FakeCompletionWriter()
    policy = code_delivery_policy(repo)

    monkeypatch.setattr(
        "projectctl.application.integration.resolve_code_delivery",
        lambda root: SimpleNamespace(policy=policy, publisher=None, reviewer=reviewer),
    )
    monkeypatch.setattr(
        "projectctl.application.integration.resolve_task_authority",
        lambda root: SimpleNamespace(provider="linear"),
    )
    monkeypatch.setattr(
        "projectctl.application.integration.resolve_execution_ownership",
        lambda root, task_authority=None: SimpleNamespace(claimer=claimer),
    )
    monkeypatch.setattr(
        "projectctl.application.integration.execution_ownership_policy",
        lambda root: SimpleNamespace(strategy="git_ref_lease"),
    )
    monkeypatch.setattr(
        "projectctl.application.integration._completion_writer",
        lambda root: writer,
    )
    monkeypatch.setattr(
        "projectctl.application.integration.ReviewGitTransport",
        FakeReviewTransport,
    )

    pending = integrate_run(repo, run_id)

    assert pending.record.status == RunStatus.AWAITING_REVIEW
    assert pending.manifest.delivery_mode == "review_required"
    assert pending.manifest.review_state == "open"
    assert pending.manifest.review_url == reviewer.review_url
    assert not pending.manifest.task_completed
    assert writer.completed == []
    assert claimer.released == []
    assert git(repo, "rev-parse", target) == candidate

    reviewer.state = "merged"
    action = recover_run(repo, run_id)

    assert action.action == "finalized_review_delivery"
    final = RunStore(repo).get(run_id)
    assert final.status == RunStatus.PASSED
    assert writer.completed
    task_id, evidence = writer.completed[0]
    assert task_id == "lin-ENG-1"
    assert evidence.path.endswith("/review-receipt.json")
    assert claimer.released == ["lin-ENG-1"]

    receipt = json.loads(
        (repo / ".projectctl" / "runs" / run_id / "review-receipt.json").read_text(
            encoding="utf-8"
        )
    )
    assert receipt["delivery_complete"] is True
    assert receipt["head_commit"] == candidate
    assert receipt["target_commit"] == candidate


def test_review_receipt_rejects_false_completed_head():
    request = review_request("github")
    with pytest.raises(Exception, match="head must equal"):
        ReviewReceipt(
            run_id=request.run_id,
            task_id=request.task_id,
            review_provider="github",
            request_digest=digest(request),
            review_id="1",
            review_url="https://github.com/acme/widget/pull/1",
            source_ref=request.source_ref,
            target_ref=request.target_ref,
            candidate_commit=request.candidate_commit,
            head_commit="c" * 40,
            target_commit="d" * 40,
            merge_commit="d" * 40,
            state="merged",
            delivery_complete=True,
            merged_at=NOW,
            observed_at=NOW,
        )
