import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest
from typer.testing import CliRunner

from projectctl.application.execution import ExecutionPlanningBundle
from projectctl.cli.entry import app
from projectctl.core.digest import digest
from projectctl.core.enums import (
    ApprovalPolicy,
    CapabilityState,
    ExecutionSandboxMode,
    ModelProfile,
    ReasoningLevel,
    RunStatus,
    RunTerminalReason,
    WorkerMode,
    WorkerStrategyKind,
)
from projectctl.core.errors import RunStoreError
from projectctl.schemas.capabilities import (
    CapabilitySupport,
    PermissionCapabilities,
    WorkerCapabilities,
    WorkerPhasePolicy,
    WorkerRuntimeDescriptor,
    WorkerStrategyDecision,
)
from projectctl.schemas.execution import ExecutionPlan
from projectctl.schemas.task_claim import TaskClaim
from projectctl.schemas.run import RunManifest, WorkerDescriptor
from projectctl.storage.runs import RunStore
from projectctl.workers.capability_digest import effective_capability_digest

runner = CliRunner()
NOW = datetime(2026, 10, 3, 6, 0, tzinfo=timezone.utc)


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


class FakeClaimer:
    def __init__(self):
        self.claimed = []
        self.released = []

    def claim(self, request):
        self.claimed.append(request.task_id)
        return TaskClaim(
            provider="beads",
            task_id=request.task_id,
            run_id=request.run_id,
            actor=request.actor,
            base_commit=request.base_commit,
            integration_target_ref=request.integration_target_ref,
            claim_token=request.claim_token,
            request_digest=digest(request),
            acquired=True,
            observed_at=NOW,
        )

    def reconcile(self, request):
        return self.claim(request)

    def validate(self, claim):
        return True

    def release(self, claim):
        self.released.append(claim.task_id)

    def release_legacy(self, task_id: str, *, actor: str):
        self.released.append(task_id)


def test_prepare_and_abort_use_durable_run_state_and_external_worktree(
    tmp_path: Path, monkeypatch
):
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "config", "user.email", "test@example.com")
    git(repo, "config", "user.name", "Test")
    monkeypatch.setenv("PROJECTCTL_HOME", str(tmp_path / "home"))

    initialized = runner.invoke(app, ["init", str(repo)])
    assert initialized.exit_code == 0, initialized.output

    (repo / ".gitignore").write_text(".projectctl/\n", encoding="utf-8")
    git(repo, "add", ".gitignore", "AGENTS.md", "docs")
    git(repo, "commit", "-q", "-m", "baseline")
    base = git(repo, "rev-parse", "HEAD")

    worker = WorkerDescriptor(
        provider="codex",
        model_profile=ModelProfile.BALANCED,
        reasoning=ReasoningLevel.MEDIUM,
    )
    support = CapabilitySupport(
        runtime=CapabilityState.SUPPORTED,
        adapter=CapabilityState.SUPPORTED,
    )
    capabilities = WorkerCapabilities(
        probe_kind="test",
        runtime=WorkerRuntimeDescriptor(
            provider="codex",
            sdk_name="openai-codex",
            sdk_version="0.160.0",
            runtime_name="openai-codex-cli-bin",
            runtime_version="0.160.0",
            adapter_name="test",
            adapter_version="1",
            observed_at=NOW,
        ),
        modes={
            WorkerMode.DEFAULT: support,
            WorkerMode.PLAN: CapabilitySupport(),
            WorkerMode.GOAL: CapabilitySupport(),
        },
        permissions=PermissionCapabilities(
            sandboxes={
                ExecutionSandboxMode.WORKSPACE_WRITE: support,
                ExecutionSandboxMode.READ_ONLY: support,
            },
            approvals={ApprovalPolicy.DENY_ALL: support},
        ),
    )
    strategy = WorkerStrategyDecision(
        task_id="bd-1",
        requested=WorkerStrategyKind.DIRECT,
        resolved=WorkerStrategyKind.DIRECT,
        compatible=True,
        capability_snapshot_digest=effective_capability_digest(capabilities),
        execution=WorkerPhasePolicy(
            mode=WorkerMode.DEFAULT,
            sandbox=ExecutionSandboxMode.WORKSPACE_WRITE,
            approval=ApprovalPolicy.DENY_ALL,
        ),
    )
    plan = ExecutionPlan(
        plan_id="ep-test",
        project_id="repo",
        task_id="bd-1",
        task_source_revision="rev-1",
        scheduler_decision_digest="scheduler",
        task_snapshot_digest="tasks",
        project_state_digest="state",
        quota_snapshot_digest="quota",
        capability_snapshot_digest=effective_capability_digest(capabilities),
        strategy_decision_digest=digest(strategy),
        strategy=WorkerStrategyKind.DIRECT,
        base_commit=base,
        integration_target_ref=git(repo, "branch", "--show-current"),
        worker=worker,
        created_at=NOW,
    )
    claimer = FakeClaimer()
    monkeypatch.setattr(
        "projectctl.application.execution.build_next_execution_bundle",
        lambda root, **kwargs: ExecutionPlanningBundle(
            plan=plan,
            capabilities=capabilities,
            strategy=strategy,
        ),
    )
    validation_calls = []

    def validate_inputs(root, value):
        validation_calls.append(value.plan_id)
        return None

    monkeypatch.setattr(
        "projectctl.application.execution._validate_plan_inputs",
        validate_inputs,
    )
    monkeypatch.setattr(
        "projectctl.application.execution._claimer",
        lambda root: claimer,
    )
    # The run lifecycle here uses a fake Beads claimer and a prebuilt plan;
    # avoid requiring the real bd executable or live quota/task provider.
    # Dedicated preflight tests still exercise their production guards.
    monkeypatch.setattr(
        "projectctl.application.execution._assert_task_store_execution_capable",
        lambda root: None,
    )
    monkeypatch.setattr(
        "projectctl.application.execution._prepare_quota_reason",
        lambda root, task_id: None,
    )

    prepared = runner.invoke(
        app,
        ["run", "prepare", "--project", str(repo), "--json"],
    )
    assert prepared.exit_code == 0, prepared.output
    payload = json.loads(prepared.output)
    run_id = payload["run"]["run_id"]
    worktree = Path(payload["worktree"]["path"])

    assert payload["run"]["status"] == "claimed"
    assert payload["run"]["task_id"] == "bd-1"
    assert worktree.exists()
    assert not worktree.is_relative_to(repo)
    assert git(repo, "rev-parse", "HEAD") == base
    assert claimer.claimed == ["bd-1"]
    assert validation_calls == ["ep-test", "ep-test"]

    shown = runner.invoke(
        app,
        ["run", "show", run_id, "--project", str(repo), "--json"],
    )
    assert shown.exit_code == 0, shown.output
    shown_payload = json.loads(shown.output)
    assert shown_payload["run"]["status"] == "claimed"
    assert [event["event_type"] for event in shown_payload["events"]] == [
        "run.created",
        "run.transition",
        "task.claim.requested",
        "task.claim.observed",
        "run.transition",
    ]

    aborted = runner.invoke(
        app,
        ["run", "abort", run_id, "--project", str(repo), "--json"],
    )
    assert aborted.exit_code == 0, aborted.output
    assert json.loads(aborted.output)["status"] == "cancelled"
    assert not worktree.exists()
    assert claimer.released == ["bd-1"]



def test_abort_marks_recovery_unsafe_when_claim_release_fails(tmp_path: Path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    monkeypatch.setenv("PROJECTCTL_HOME", str(tmp_path / "home"))
    initialized = runner.invoke(app, ["init", str(repo)])
    assert initialized.exit_code == 0, initialized.output

    worker = WorkerDescriptor(
        provider="codex",
        model_profile=ModelProfile.BALANCED,
        reasoning=ReasoningLevel.MEDIUM,
    )
    manifest = RunManifest(
        run_id="run-fail-release",
        task_id="bd-1",
        execution_plan_digest="plan",
        status=RunStatus.CLAIMED,
        base_commit="abcdef1",
        branch_name="projectctl/run/run-fail-release",
        worktree_id="run-fail-release",
        worker=worker,
    )
    store = RunStore(repo)
    store.create(
        manifest,
        worktree_path=tmp_path / "home" / "worktrees" / "fake" / "run-fail-release",
        now=NOW,
    )

    class FailingClaimer:
        def release(self, claim):
            raise RuntimeError("release failed")

        def release_legacy(self, task_id: str, *, actor: str):
            raise RuntimeError("release failed")

    monkeypatch.setattr(
        "projectctl.application.execution._claimer",
        lambda root: FailingClaimer(),
    )
    monkeypatch.setattr(
        "projectctl.application.execution.WorktreeManager.remove",
        lambda self, **kwargs: None,
    )

    with pytest.raises(RunStoreError, match="claim could not be released"):
        from projectctl.application.execution import abort_prepared_run
        abort_prepared_run(repo, "run-fail-release")

    record = store.get("run-fail-release")
    assert record.status == RunStatus.NEEDS_DECISION
    assert record.terminal_reason == RunTerminalReason.RECOVERY_UNSAFE
