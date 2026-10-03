import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

from projectctl.application.execution import (
    ExecutionPlanningBundle,
    prepare_next_run,
    start_prepared_run,
)
from projectctl.core.digest import digest
from projectctl.core.enums import (
    ApprovalPolicy,
    CapabilityState,
    ExecutionSandboxMode,
    ModelProfile,
    ReasoningLevel,
    RunStatus,
    RunTerminalReason,
    TaskStatus,
    TaskType,
    WorkerMode,
    WorkerResultStatus,
    WorkerStrategyKind,
)
from projectctl.core.errors import CapabilityMismatchError, WorkerError
from projectctl.schemas.capabilities import (
    CapabilitySupport,
    PermissionCapabilities,
    WorkerCapabilities,
    WorkerPhasePolicy,
    WorkerRuntimeDescriptor,
    WorkerStrategyDecision,
)
from projectctl.schemas.execution import ClaimResult, ExecutionPlan, WorkerResult
from projectctl.schemas.run import WorkerDescriptor
from projectctl.schemas.task import NormalizedTask, TaskSource
from projectctl.storage.runs import RunStore
from projectctl.workers.capability_digest import effective_capability_digest
from typer.testing import CliRunner
from projectctl.cli.entry import app

NOW = datetime(2026, 10, 3, 6, 0, tzinfo=timezone.utc)
runner = CliRunner()


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def supported_capabilities(runtime_version="0.160.0"):
    support = CapabilitySupport(
        runtime=CapabilityState.SUPPORTED,
        adapter=CapabilityState.SUPPORTED,
    )
    return WorkerCapabilities(
        probe_kind="test",
        runtime=WorkerRuntimeDescriptor(
            provider="codex",
            sdk_name="openai-codex",
            sdk_version="0.160.0",
            runtime_name="openai-codex-cli-bin",
            runtime_version=runtime_version,
            adapter_name="projectctl.codex",
            adapter_version="0.9.0",
            observed_at=NOW,
        ),
        modes={
            WorkerMode.DEFAULT: support,
            WorkerMode.PLAN: CapabilitySupport(),
            WorkerMode.GOAL: CapabilitySupport(),
        },
        permissions=PermissionCapabilities(
            sandboxes={
                ExecutionSandboxMode.READ_ONLY: support,
                ExecutionSandboxMode.WORKSPACE_WRITE: support,
            },
            approvals={ApprovalPolicy.DENY_ALL: support},
        ),
        structured_output=support,
    )


class FakeClaimer:
    def claim(self, task_id: str, *, actor: str):
        return ClaimResult(
            task_id=task_id,
            actor=actor,
            claimed=True,
            observed_at=NOW,
        )

    def release(self, task_id: str, *, actor: str):
        return None


class FakeTaskStore:
    def __init__(self, task):
        self.task = task

    def get(self, task_id):
        assert task_id == self.task.id
        return self.task


class FakeAdapter:
    def __init__(self, caps, *, commit=False):
        self.caps = caps
        self.commit = commit

    def probe(self):
        return self.caps

    def start(self, request, *, workspace: Path, checkpoint_monitor=None):
        (workspace / "worker_output.py").write_text("value = 1\n", encoding="utf-8")
        if self.commit:
            git(workspace, "add", "worker_output.py")
            git(workspace, "commit", "-q", "-m", "worker must not commit")
        return WorkerResult(
            run_id=request.run_id,
            task_id=request.task_id,
            status=WorkerResultStatus.IMPLEMENTED,
            summary="implemented",
            worker_thread_id="thr-test",
            completed_at=NOW,
        )


def setup_prepared(tmp_path: Path, monkeypatch):
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

    task = NormalizedTask(
        id="bd-1",
        title="Implement worker change",
        source=TaskSource(provider="test", external_id="bd-1"),
        type=TaskType.FEATURE,
        status=TaskStatus.RUNNING,
    )
    caps = supported_capabilities()
    strategy = WorkerStrategyDecision(
        task_id=task.id,
        requested=WorkerStrategyKind.DIRECT,
        resolved=WorkerStrategyKind.DIRECT,
        compatible=True,
        capability_snapshot_digest=effective_capability_digest(caps),
        execution=WorkerPhasePolicy(
            mode=WorkerMode.DEFAULT,
            sandbox=ExecutionSandboxMode.WORKSPACE_WRITE,
            approval=ApprovalPolicy.DENY_ALL,
        ),
    )
    plan = ExecutionPlan(
        plan_id="ep-test",
        project_id="repo",
        task_id=task.id,
        scheduler_decision_digest="scheduler",
        task_snapshot_digest="tasks",
        project_state_digest="state",
        quota_snapshot_digest="quota",
        capability_snapshot_digest=effective_capability_digest(caps),
        strategy_decision_digest=digest(strategy),
        strategy=WorkerStrategyKind.DIRECT,
        base_commit=base,
        integration_target_ref=git(repo, "branch", "--show-current"),
        worker=WorkerDescriptor(
            provider="codex",
            model_profile=ModelProfile.BALANCED,
            reasoning=ReasoningLevel.MEDIUM,
        ),
        created_at=NOW,
    )
    planning = ExecutionPlanningBundle(plan=plan, capabilities=caps, strategy=strategy)

    monkeypatch.setattr(
        "projectctl.application.execution.build_next_execution_bundle",
        lambda root, **kwargs: planning,
    )
    monkeypatch.setattr(
        "projectctl.application.execution._validate_plan_inputs",
        lambda root, value: None,
    )
    monkeypatch.setattr(
        "projectctl.application.execution._claimer",
        lambda root: FakeClaimer(),
    )
    monkeypatch.setattr(
        "projectctl.application.execution.task_store_for_project",
        lambda root: FakeTaskStore(task),
    )
    monkeypatch.setattr(
        "projectctl.context.assembler.task_store_for_project",
        lambda root: FakeTaskStore(task),
    )
    monkeypatch.setattr(
        "projectctl.application.task_lifecycle.release_task_for_retry",
        lambda root, task_id, actor: None,
    )
    monkeypatch.setattr(
        "projectctl.application.task_lifecycle.block_task_for_decision",
        lambda root, task_id, reason: None,
    )

    prepared = prepare_next_run(repo)
    return repo, prepared, task, caps


def test_worker_implemented_moves_run_only_to_verifying(tmp_path: Path, monkeypatch):
    repo, prepared, task, caps = setup_prepared(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "projectctl.application.execution._adapter_for_provider",
        lambda provider: FakeAdapter(caps),
    )

    started = start_prepared_run(repo, prepared.record.run_id)

    assert started.record.status == RunStatus.VERIFYING
    assert started.result.status == WorkerResultStatus.IMPLEMENTED
    assert started.result.worker_thread_id == "thr-test"
    worktree = Path(prepared.record.worktree_path)
    assert (worktree / "worker_output.py").exists()
    assert git(worktree, "rev-parse", "HEAD") == prepared.plan.base_commit

    run_dir = repo / ".projectctl" / "runs" / prepared.record.run_id
    assert (run_dir / "context-manifest.json").exists()
    assert (run_dir / "worker-request.json").exists()
    assert (run_dir / "worker-result.json").exists()
    manifest = RunStore(repo).manifest(prepared.record.run_id)
    assert manifest.context_manifest is not None
    assert manifest.worker_thread_id == "thr-test"


def test_worker_hidden_commit_is_rejected(tmp_path: Path, monkeypatch):
    repo, prepared, task, caps = setup_prepared(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "projectctl.application.execution._adapter_for_provider",
        lambda provider: FakeAdapter(caps, commit=True),
    )

    with pytest.raises(WorkerError, match="Git HEAD"):
        start_prepared_run(repo, prepared.record.run_id)

    record = RunStore(repo).get(prepared.record.run_id)
    assert record.status == RunStatus.FAILED
    assert record.terminal_reason == RunTerminalReason.UNEXPECTED_GIT_HISTORY


def test_live_capability_drift_requires_decision(tmp_path: Path, monkeypatch):
    repo, prepared, task, caps = setup_prepared(tmp_path, monkeypatch)
    changed = supported_capabilities(runtime_version="0.161.0")
    monkeypatch.setattr(
        "projectctl.application.execution._adapter_for_provider",
        lambda provider: FakeAdapter(changed),
    )

    with pytest.raises(CapabilityMismatchError, match="changed"):
        start_prepared_run(repo, prepared.record.run_id)

    record = RunStore(repo).get(prepared.record.run_id)
    assert record.status == RunStatus.NEEDS_DECISION
    assert record.terminal_reason == RunTerminalReason.CAPABILITY_CHANGED
