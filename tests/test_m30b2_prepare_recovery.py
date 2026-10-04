import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

from projectctl.application.claims import (
    persist_claim_request,
)
from projectctl.application.recovery import recover_run
from projectctl.core.digest import digest
from projectctl.core.enums import (
    ModelProfile,
    ReasoningLevel,
    RunStatus,
    RunTerminalReason,
)
from projectctl.project.bootstrap import initialize_project
from projectctl.schemas.execution import ExecutionPlan
from projectctl.schemas.run import RunManifest, WorkerDescriptor
from projectctl.schemas.task_claim import TaskClaim, TaskClaimRequest
from projectctl.storage.runs import RunStore


NOW = datetime(2026, 10, 4, 6, 0, tzinfo=timezone.utc)


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def setup_preparing(tmp_path: Path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "config", "user.email", "test@example.com")
    git(repo, "config", "user.name", "Test")
    monkeypatch.setenv("PROJECTCTL_HOME", str(tmp_path / "home"))
    initialize_project(repo)

    (repo / ".gitignore").write_text(".projectctl/\n", encoding="utf-8")
    git(repo, "add", ".gitignore", "AGENTS.md", "docs")
    git(repo, "commit", "-q", "-m", "base")
    base = git(repo, "rev-parse", "HEAD")
    branch = git(repo, "branch", "--show-current")

    run_id = "run-recover-prepare"
    worker = WorkerDescriptor(
        provider="codex",
        model_profile=ModelProfile.BALANCED,
        reasoning=ReasoningLevel.MEDIUM,
    )
    plan = ExecutionPlan(
        plan_id="ep-recover",
        project_id="demo",
        task_id="bd-1",
        scheduler_decision_digest="scheduler",
        task_snapshot_digest="tasks",
        project_state_digest="state",
        quota_snapshot_digest="quota",
        capability_snapshot_digest="caps",
        strategy_decision_digest="strategy",
        strategy="direct",
        base_commit=base,
        integration_target_ref=branch,
        worker=worker,
        created_at=NOW,
    )
    run_dir = repo / ".projectctl" / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "execution-plan.json").write_text(
        json.dumps(plan.model_dump(mode="json")),
        encoding="utf-8",
    )
    manifest = RunManifest(
        run_id=run_id,
        task_id="bd-1",
        execution_plan_digest=digest(plan),
        status=RunStatus.PREPARING,
        base_commit=base,
        branch_name=f"projectctl/run/{run_id}",
        worktree_id=run_id,
        worker=worker,
    )
    store = RunStore(repo)
    store.create(
        manifest,
        worktree_path=tmp_path / "home" / "worktrees" / "placeholder" / run_id,
        lease_owner="dead-owner",
        lease_ttl_seconds=1,
        now=NOW - timedelta(hours=1),
    )
    # Use the actual manager-computed path stored by normal preparation.
    from projectctl.git import WorktreeManager
    actual = WorktreeManager(repo).path_for(run_id)
    conn = __import__("sqlite3").connect(repo / ".projectctl" / "state.sqlite")
    conn.execute("UPDATE runs SET worktree_path=? WHERE run_id=?", (str(actual), run_id))
    conn.commit()
    conn.close()

    request = TaskClaimRequest(
        task_id="bd-1",
        run_id=run_id,
        actor="projectctl:old",
        base_commit=base,
        integration_target_ref=branch,
        claim_token="a" * 32,
        requested_at=NOW,
    )
    persist_claim_request(repo, store=store, request=request)
    return repo, store, plan, request


class RecoveringClaimer:
    def __init__(self, request, *, acquired=True, can_reconcile=True):
        self.request = request
        self.acquired = acquired
        self.can_reconcile = can_reconcile
        self.reconciled = 0

    def reconcile(self, request):
        self.reconciled += 1
        assert request == self.request
        if not self.can_reconcile:
            return None
        return TaskClaim(
            provider="github",
            task_id=request.task_id,
            run_id=request.run_id,
            actor=request.actor,
            base_commit=request.base_commit,
            integration_target_ref=request.integration_target_ref,
            claim_token=request.claim_token,
            request_digest=digest(request),
            acquired=self.acquired,
            observed_at=NOW,
            reason=None if self.acquired else "claim lost",
            repository="acme/widget",
            ownership_ref="refs/heads/projectctl/claims/issue-1",
            ownership_sha="b" * 40,
        )

    def validate(self, claim):
        return self.acquired and claim.ownership_sha == "b" * 40

    def release(self, claim):
        return None

    def release_legacy(self, task_id, *, actor):
        return None


class Authority:
    def __init__(self, claimer):
        self.claimer = claimer

    def require_claimer(self):
        return self.claimer


def test_recovery_reconstructs_missing_claim_result_and_worktree(
    tmp_path: Path, monkeypatch
):
    repo, store, plan, request = setup_preparing(tmp_path, monkeypatch)
    claimer = RecoveringClaimer(request)
    monkeypatch.setattr(
        "projectctl.application.recovery.resolve_task_authority",
        lambda root: Authority(claimer),
    )

    result = recover_run(repo, request.run_id)

    assert result.action == "reconciled_prepare"
    assert result.resolved_status == RunStatus.CLAIMED.value
    assert claimer.reconciled == 1
    record = store.get(request.run_id)
    assert Path(record.worktree_path).exists()
    assert git(Path(record.worktree_path), "rev-parse", "HEAD") == plan.base_commit
    claim_path = repo / ".projectctl" / "runs" / request.run_id / "task-claim.json"
    assert claim_path.exists()


def test_recovery_records_claim_loss_without_creating_worktree(
    tmp_path: Path, monkeypatch
):
    repo, store, plan, request = setup_preparing(tmp_path, monkeypatch)
    claimer = RecoveringClaimer(request, acquired=False)
    monkeypatch.setattr(
        "projectctl.application.recovery.resolve_task_authority",
        lambda root: Authority(claimer),
    )

    result = recover_run(repo, request.run_id)

    assert result.action == "prepare_claim_lost"
    assert result.resolved_status == RunStatus.FAILED.value
    record = store.get(request.run_id)
    assert record.terminal_reason == RunTerminalReason.CLAIM_LOST
    assert not Path(record.worktree_path).exists()


def test_recovery_fails_closed_when_authority_cannot_prove_request_ownership(
    tmp_path: Path, monkeypatch
):
    repo, store, plan, request = setup_preparing(tmp_path, monkeypatch)
    claimer = RecoveringClaimer(request, can_reconcile=False)
    monkeypatch.setattr(
        "projectctl.application.recovery.resolve_task_authority",
        lambda root: Authority(claimer),
    )

    result = recover_run(repo, request.run_id)

    assert result.action == "escalated_prepare_recovery"
    assert result.resolved_status == RunStatus.NEEDS_DECISION.value
    assert store.get(request.run_id).terminal_reason == RunTerminalReason.RECOVERY_UNSAFE
