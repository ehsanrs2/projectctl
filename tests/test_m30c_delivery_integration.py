import json
import subprocess
from types import SimpleNamespace
from datetime import datetime, timezone
from pathlib import Path

import yaml

from projectctl.application.claims import persist_claim, persist_claim_request
from projectctl.application.integration import integrate_run
from projectctl.core.digest import digest
from projectctl.core.errors import ClaimConflictError
from projectctl.core.enums import (
    ModelProfile,
    ReasoningLevel,
    RunStatus,
    VerificationCheckStatus,
    WorkerResultStatus,
    WorkerStrategyKind,
)
from projectctl.core.time import utc_now
from projectctl.git import WorktreeManager
from projectctl.project.bootstrap import initialize_project
from projectctl.schemas.delivery import (
    PublicationManifest,
    TaskDeliveryPolicy,
)
from projectctl.schemas.evidence import EvidenceManifest
from projectctl.schemas.execution import ExecutionPlan, WorkerResult
from projectctl.schemas.run import RunManifest, WorkerDescriptor
from projectctl.schemas.task_claim import TaskClaim, TaskClaimRequest
from projectctl.schemas.verification import (
    VerificationCheckResult,
    VerificationManifest,
)
from projectctl.storage.runs import RunStore
from projectctl.verification.diff import committed_diff_digest


NOW = datetime(2026, 10, 4, 8, 0, tzinfo=timezone.utc)


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


class FakeClaimer:
    def __init__(self, *, release_conflict=False):
        self.released = []
        self.release_conflict = release_conflict

    def validate(self, claim):
        return True

    def release(self, claim):
        if self.release_conflict:
            raise ClaimConflictError("claim replaced after completion")
        self.released.append(claim.task_id)


class FakePublisher:
    def __init__(self):
        self.published = False
        self.calls = []

    def _manifest(self, request, *, published, before, after, reason=None):
        return PublicationManifest(
            run_id=request.run_id,
            task_id=request.task_id,
            provider=request.provider,
            repository=request.repository,
            remote_name=request.remote_name,
            target_ref=request.target_ref,
            base_commit=request.base_commit,
            candidate_commit=request.candidate_commit,
            evidence_manifest=request.evidence_manifest,
            evidence_digest=request.evidence_digest,
            request_digest=digest(request),
            remote_before=before,
            remote_after=after,
            published=published,
            observed_at=NOW,
            reason=reason,
        )

    def reconcile(self, request):
        self.calls.append("reconcile")
        if self.published:
            return self._manifest(
                request,
                published=True,
                before=request.candidate_commit,
                after=request.candidate_commit,
            )
        return self._manifest(
            request,
            published=False,
            before=request.base_commit,
            after=request.base_commit,
            reason="not published yet",
        )

    def publish(self, request):
        self.calls.append("publish")
        self.published = True
        return self._manifest(
            request,
            published=True,
            before=request.base_commit,
            after=request.candidate_commit,
        )


class FakeWriter:
    def __init__(self, publisher):
        self.publisher = publisher
        self.completed = []

    def complete(self, task_id, *, evidence):
        assert self.publisher.published is True
        self.completed.append((task_id, evidence))

    def mark_needs_decision(self, task_id, *, reason):
        raise AssertionError("unexpected decision block")


class FakeAuthority:
    provider = "github"

    def __init__(self, claimer, publisher):
        self.claimer = claimer
        self.publisher = publisher
        self.delivery_policy = TaskDeliveryPolicy(
            provider="github",
            publication_required=True,
            remote_name="origin",
            release_claim_after_completion=True,
            release_claim_after_decision_block=True,
        )

    def require_claimer(self):
        return self.claimer

    def require_publisher(self):
        return self.publisher


def setup_ready_run(tmp_path: Path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "config", "user.email", "test@example.com")
    git(repo, "config", "user.name", "Test")
    monkeypatch.setenv("PROJECTCTL_HOME", str(tmp_path / "home"))
    initialize_project(repo)

    config_path = repo / ".projectctl" / "config.yaml"
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    raw["task_store"] = {"provider": "github", "repository": "acme/widget"}
    raw["code_transport"] = {
        "mode": "git_remote",
        "remote_name": "origin",
        "remote_identity": "github.com/acme/widget",
    }
    raw["code_delivery"] = {"mode": "direct_git"}
    config_path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")

    (repo / ".gitignore").write_text(".projectctl/\n", encoding="utf-8")
    (repo / "app.py").write_text("value = 1\n", encoding="utf-8")
    git(repo, "add", ".gitignore", "app.py", "AGENTS.md", "docs")
    git(repo, "commit", "-q", "-m", "baseline")
    base = git(repo, "rev-parse", "HEAD")
    target = git(repo, "branch", "--show-current")

    run_id = "run-github-delivery"
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
        plan_id="ep-github-delivery",
        project_id="repo",
        task_id="gh-7",
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
        task_id="gh-7",
        status=WorkerResultStatus.IMPLEMENTED,
        summary="done",
        worker_thread_id="thr-1",
        completed_at=NOW,
    )
    verification = VerificationManifest(
        run_id=run_id,
        task_id="gh-7",
        base_commit=base,
        workspace_state_digest="workspace",
        profile="default",
        profile_digest="profile-digest",
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
        task_id="gh-7",
        base_commit=base,
        candidate_commit=candidate,
        diff_digest=committed_diff_digest(worktree, base, candidate),
        workspace_state_digest="workspace",
        worker_result_digest=digest(worker_result),
        verification_manifest_digest=digest(verification),
        verification_profile_digest="profile-digest",
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

    manifest = RunManifest(
        run_id=run_id,
        task_id="gh-7",
        execution_plan_digest=digest(plan),
        status=RunStatus.READY_TO_INTEGRATE,
        base_commit=base,
        candidate_commit=candidate,
        branch_name=branch,
        worktree_id=run_id,
        worker=worker,
        evidence_manifest=f".projectctl/runs/{run_id}/evidence-manifest.json",
    )
    store = RunStore(repo)
    store.create(manifest, worktree_path=worktree, now=NOW)

    request = TaskClaimRequest(
        task_id="gh-7",
        run_id=run_id,
        actor="projectctl:test",
        base_commit=base,
        integration_target_ref=target,
        claim_token="a" * 32,
        requested_at=NOW,
    )
    claim = TaskClaim(
        provider="github",
        task_id=request.task_id,
        run_id=request.run_id,
        actor=request.actor,
        base_commit=request.base_commit,
        integration_target_ref=request.integration_target_ref,
        claim_token=request.claim_token,
        request_digest=digest(request),
        acquired=True,
        observed_at=NOW,
        repository="acme/widget",
        ownership_ref="refs/heads/projectctl/claims/issue-7",
        ownership_sha="c" * 40,
    )
    persist_claim_request(repo, store=store, request=request)
    persist_claim(repo, store=store, request=request, claim=claim)
    return repo, run_id, candidate


def test_github_delivery_completes_only_after_publication_and_releases_claim(
    tmp_path: Path, monkeypatch
):
    repo, run_id, candidate = setup_ready_run(tmp_path, monkeypatch)
    claimer = FakeClaimer()
    publisher = FakePublisher()
    writer = FakeWriter(publisher)
    authority = FakeAuthority(claimer, publisher)

    monkeypatch.setattr(
        "projectctl.application.integration.resolve_task_authority",
        lambda root: authority,
    )
    monkeypatch.setattr(
        "projectctl.application.integration.resolve_code_delivery",
        lambda root: SimpleNamespace(
            policy=SimpleNamespace(
                publication_required=True,
                supported=True,
                mode="direct_git",
                remote_name="origin",
                remote_identity="github.com/acme/widget",
            ),
            publisher=publisher,
        ),
    )
    monkeypatch.setattr(
        "projectctl.application.integration._completion_writer",
        lambda root: writer,
    )

    result = integrate_run(repo, run_id)

    assert result.record.status == RunStatus.PASSED
    assert publisher.calls == ["reconcile", "publish"]
    assert writer.completed
    task_id, evidence = writer.completed[0]
    assert task_id == "gh-7"
    assert evidence.path.endswith("/publication-manifest.json")
    assert claimer.released == ["gh-7"]
    assert result.manifest.publication_required is True
    assert result.manifest.publication_manifest == evidence.path
    assert result.manifest.publication_digest == evidence.digest
    assert result.manifest.claim_released is True
    assert result.manifest.task_completed is True
    assert git(repo, "rev-parse", result.manifest.target_ref) == candidate


def test_post_completion_claim_conflict_does_not_rewrite_task_semantics(
    tmp_path: Path, monkeypatch
):
    repo, run_id, candidate = setup_ready_run(tmp_path, monkeypatch)
    claimer = FakeClaimer(release_conflict=True)
    publisher = FakePublisher()
    writer = FakeWriter(publisher)
    authority = FakeAuthority(claimer, publisher)

    monkeypatch.setattr(
        "projectctl.application.integration.resolve_task_authority",
        lambda root: authority,
    )
    monkeypatch.setattr(
        "projectctl.application.integration.resolve_code_delivery",
        lambda root: SimpleNamespace(
            policy=SimpleNamespace(
                publication_required=True,
                supported=True,
                mode="direct_git",
                remote_name="origin",
                remote_identity="github.com/acme/widget",
            ),
            publisher=publisher,
        ),
    )
    monkeypatch.setattr(
        "projectctl.application.integration._completion_writer",
        lambda root: writer,
    )

    result = integrate_run(repo, run_id)

    assert result.record.status == RunStatus.PASSED
    assert writer.completed
    assert result.manifest.task_completed is True
    assert result.manifest.claim_released is False
    assert git(repo, "rev-parse", result.manifest.target_ref) == candidate

    events = RunStore(repo).events(run_id)
    assert any(
        event.event_type == "task.claim.ownership_lost_after_completion"
        for event in events
    )
    assert not any(
        event.event_type == "task.reconciled"
        and event.payload.get("action") == "blocked"
        for event in events
    )
