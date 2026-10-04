import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest
from typer.testing import CliRunner

from projectctl.application.integration import integrate_run
from projectctl.application.recovery import recover_run
from projectctl.cli.entry import app
from projectctl.core.digest import digest
from projectctl.core.enums import (
    ModelProfile,
    ReasoningLevel,
    RunStatus,
    RunTerminalReason,
    VerificationCheckStatus,
    WorkerResultStatus,
    WorkerStrategyKind,
)
from projectctl.core.errors import IntegrationError
from projectctl.git import WorktreeManager
from projectctl.schemas.evidence import EvidenceManifest
from projectctl.schemas.execution import ExecutionPlan, WorkerResult
from projectctl.schemas.run import RunManifest, WorkerDescriptor
from projectctl.schemas.verification import VerificationCheckResult, VerificationManifest
from projectctl.storage.runs import RunStore
from projectctl.verification.diff import committed_diff_digest

NOW = datetime(2026, 10, 3, 9, 0, tzinfo=timezone.utc)
runner = CliRunner()


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


class FakeCompletionWriter:
    def __init__(self):
        self.completed = []
        self.needs_decision = []

    def complete(self, task_id, *, evidence):
        self.completed.append((task_id, evidence))

    def mark_needs_decision(self, task_id, *, reason):
        self.needs_decision.append((task_id, reason))


def setup_ready_run(tmp_path: Path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "config", "user.email", "test@example.com")
    git(repo, "config", "user.name", "Test")
    monkeypatch.setenv("PROJECTCTL_HOME", str(tmp_path / "home"))

    result = runner.invoke(app, ["init", str(repo)])
    assert result.exit_code == 0, result.output

    (repo / ".gitignore").write_text(".projectctl/\n", encoding="utf-8")
    (repo / "app.py").write_text("value = 1\n", encoding="utf-8")
    git(repo, "add", ".gitignore", "app.py", "AGENTS.md", "docs")
    git(repo, "commit", "-q", "-m", "baseline")
    base = git(repo, "rev-parse", "HEAD")
    target = git(repo, "branch", "--show-current")

    run_id = "run-integration"
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
        plan_id="ep-integration",
        project_id="repo",
        task_id="bd-1",
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
        task_id="bd-1",
        status=WorkerResultStatus.IMPLEMENTED,
        summary="done",
        worker_thread_id="thr-1",
        completed_at=NOW,
    )
    verification = VerificationManifest(
        run_id=run_id,
        task_id="bd-1",
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
        task_id="bd-1",
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
        task_id="bd-1",
        execution_plan_digest=digest(plan),
        status=RunStatus.READY_TO_INTEGRATE,
        base_commit=base,
        candidate_commit=candidate,
        branch_name=branch,
        worktree_id=run_id,
        worker=worker,
        evidence_manifest=f".projectctl/runs/{run_id}/evidence-manifest.json",
    )
    RunStore(repo).create(manifest, worktree_path=worktree, now=NOW)
    return repo, worktree, base, candidate, target, run_id


def test_integration_fast_forwards_closes_task_and_cleans_worktree(tmp_path: Path, monkeypatch):
    repo, worktree, base, candidate, target, run_id = setup_ready_run(tmp_path, monkeypatch)
    writer = FakeCompletionWriter()
    monkeypatch.setattr(
        "projectctl.application.integration._completion_writer",
        lambda root: writer,
    )

    integrated = integrate_run(repo, run_id)

    assert integrated.record.status == RunStatus.PASSED
    assert git(repo, "rev-parse", target) == candidate
    assert writer.completed and writer.completed[0][0] == "bd-1"
    assert integrated.manifest.task_completed is True
    assert integrated.manifest.worktree_cleaned is True
    assert not worktree.exists()


def test_target_drift_fails_closed_and_marks_needs_decision(tmp_path: Path, monkeypatch):
    repo, worktree, base, candidate, target, run_id = setup_ready_run(tmp_path, monkeypatch)
    writer = FakeCompletionWriter()
    monkeypatch.setattr(
        "projectctl.application.integration._completion_writer",
        lambda root: writer,
    )
    (repo / "other.txt").write_text("advanced\n", encoding="utf-8")
    git(repo, "add", "other.txt")
    git(repo, "commit", "-q", "-m", "advance target")

    with pytest.raises(IntegrationError, match="advanced"):
        integrate_run(repo, run_id)

    record = RunStore(repo).get(run_id)
    assert record.status == RunStatus.NEEDS_DECISION
    assert record.terminal_reason == RunTerminalReason.STALE_BASE
    assert writer.needs_decision


def test_evidence_tampering_is_detected_before_integration(tmp_path: Path, monkeypatch):
    repo, worktree, base, candidate, target, run_id = setup_ready_run(tmp_path, monkeypatch)
    writer = FakeCompletionWriter()
    monkeypatch.setattr(
        "projectctl.application.integration._completion_writer",
        lambda root: writer,
    )
    path = repo / ".projectctl" / "runs" / run_id / "evidence-manifest.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["diff_digest"] = "sha256:tampered"
    path.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(IntegrationError, match="diff digest"):
        integrate_run(repo, run_id)

    assert RunStore(repo).get(run_id).status == RunStatus.READY_TO_INTEGRATE
    assert git(repo, "rev-parse", target) == base
    assert writer.completed == []


def test_recovery_finishes_crash_after_fast_forward(tmp_path: Path, monkeypatch):
    repo, worktree, base, candidate, target, run_id = setup_ready_run(tmp_path, monkeypatch)
    writer = FakeCompletionWriter()
    monkeypatch.setattr(
        "projectctl.application.integration._completion_writer",
        lambda root: writer,
    )
    store = RunStore(repo)
    store.transition(
        run_id,
        expected={RunStatus.READY_TO_INTEGRATE},
        status=RunStatus.INTEGRATING,
    )
    git(repo, "merge", "--ff-only", candidate)

    action = recover_run(repo, run_id)

    assert action.action == "finalized_delivery"
    assert RunStore(repo).get(run_id).status == RunStatus.PASSED
    assert writer.completed
    assert not worktree.exists()


def test_m14_cli_commands_are_registered():
    assert runner.invoke(app, ["run", "integrate", "--help"]).exit_code == 0
    assert runner.invoke(app, ["run", "recover", "--help"]).exit_code == 0
