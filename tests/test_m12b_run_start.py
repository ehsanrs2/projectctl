import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

from projectctl.application.execution import (
    ExecutionPlanningBundle,
    prepare_next_run,
    resume_checkpointed_run,
    start_prepared_run,
)
from projectctl.core.digest import digest
from projectctl.core.enums import (
    ApprovalPolicy,
    CapabilityState,
    CheckpointReason,
    ExecutionSandboxMode,
    ModelProfile,
    QuotaMode,
    ResourceClass,
    ReasoningLevel,
    RunStatus,
    RunTerminalReason,
    TaskStatus,
    TaskType,
    WorkerMode,
    WorkerResultStatus,
    WorkerStrategyKind,
)
from projectctl.core.errors import (
    CapabilityMismatchError,
    ClaimConflictError,
    QuotaAdmissionError,
    QuotaError,
    RunStoreError,
    WorkerError,
    WorktreeError,
)
from projectctl.schemas.capabilities import (
    CapabilitySupport,
    PermissionCapabilities,
    WorkerCapabilities,
    WorkerPhasePolicy,
    WorkerRuntimeDescriptor,
    WorkerStrategyDecision,
)
from projectctl.schemas.execution import (
    ClaimResult,
    ExecutionPlan,
    WorkerCheckpoint,
    WorkerResult,
)
from projectctl.application.recovery import recover_run
from projectctl.schemas.quota import QuotaSnapshot, QuotaWindow
from projectctl.quota.admission import AccountAdmissionStore
from projectctl.schemas.run import WorkerDescriptor
from projectctl.schemas.task_claim import TaskClaim
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
    def __init__(self, *, valid=True):
        self.valid = valid

    def claim(self, request):
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
        return self.valid

    def release(self, claim):
        return None

    def release_legacy(self, task_id: str, *, actor: str):
        return None


class FakeTaskStore:
    def __init__(self, task):
        self.task = task

    def get(self, task_id):
        assert task_id == self.task.id
        return self.task


class FakeAdapter:
    def __init__(self, caps, *, commit=False, checkpoint=False):
        self.caps = caps
        self.commit = commit
        self.checkpoint = checkpoint

    def probe(self):
        return self.caps

    def start(self, request, *, workspace: Path, checkpoint_monitor=None):
        (workspace / "worker_output.py").write_text("value = 1\n", encoding="utf-8")
        if self.commit:
            git(workspace, "add", "worker_output.py")
            git(workspace, "commit", "-q", "-m", "worker must not commit")
        if self.checkpoint:
            return WorkerCheckpoint(
                run_id=request.run_id,
                task_id=request.task_id,
                worker_thread_id="thr-test",
                worker_turn_id="turn-test",
                worktree_id=request.worktree_id,
                base_commit=request.base_commit,
                branch_name=request.branch_name,
                context_manifest_digest=request.context_manifest_digest,
                worker_request_digest=digest(request),
                reason=CheckpointReason.QUOTA_BELOW_TASK_REQUIREMENT,
                quota_snapshot=QuotaSnapshot(
                    provider="test",
                    account="acct",
                    observed_at=NOW,
                    five_hour=QuotaWindow(),
                    weekly=QuotaWindow(),
                ),
                quota_snapshot_digest=digest(
                    QuotaSnapshot(
                        provider="test",
                        account="acct",
                        observed_at=NOW,
                        five_hour=QuotaWindow(),
                        weekly=QuotaWindow(),
                    )
                ),
                quota_mode=QuotaMode.CONSERVATION,
                quota_stale=False,
                checkpoint_at=NOW,
            )
        return WorkerResult(
            run_id=request.run_id,
            task_id=request.task_id,
            status=WorkerResultStatus.IMPLEMENTED,
            summary="implemented",
            worker_thread_id="thr-test",
            completed_at=NOW,
        )

    def resume(self, checkpoint, request, *, workspace: Path, checkpoint_monitor=None):
        self.resumed_checkpoint = checkpoint
        (workspace / "worker_output.py").write_text("value = 2\n", encoding="utf-8")
        return WorkerResult(
            run_id=request.run_id,
            task_id=request.task_id,
            status=WorkerResultStatus.IMPLEMENTED,
            summary="resumed and implemented",
            worker_thread_id=checkpoint.worker_thread_id,
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
        resource_class=ResourceClass.SMALL,
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
        lambda root, store, run_id, actor: None,
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


def test_worker_quota_checkpoint_is_durable_and_keeps_run_resumable(tmp_path: Path, monkeypatch):
    repo, prepared, task, caps = setup_prepared(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "projectctl.application.execution._adapter_for_provider",
        lambda provider: FakeAdapter(caps, checkpoint=True),
    )

    started = start_prepared_run(repo, prepared.record.run_id)

    assert started.result is None
    assert started.checkpoint is not None
    assert started.record.status == RunStatus.RUNNING
    assert started.record.worker_thread_id == "thr-test"
    assert started.record.checkpoint_ref is not None
    checkpoint_path = repo / started.record.checkpoint_ref
    assert checkpoint_path.exists()
    persisted = WorkerCheckpoint.model_validate_json(checkpoint_path.read_text())
    assert persisted.worker_thread_id == "thr-test"
    assert persisted.worker_turn_id == "turn-test"
    assert persisted.reason == CheckpointReason.QUOTA_BELOW_TASK_REQUIREMENT
    assert persisted.workspace_digest is not None
    assert digest(persisted.quota_snapshot) == persisted.quota_snapshot_digest

    worktree = Path(started.record.worktree_path)
    assert (worktree / "worker_output.py").exists()
    assert git(worktree, "rev-parse", "HEAD") == prepared.plan.base_commit
    events = RunStore(repo).events(prepared.record.run_id)
    assert any(event.event_type == "worker.checkpointed" for event in events)


def fresh_quota():
    now = datetime.now(timezone.utc)
    return QuotaSnapshot(
        provider="test",
        account="openai-default",
        observed_at=now,
        five_hour=QuotaWindow(remaining_ratio=.90),
        weekly=QuotaWindow(remaining_ratio=.90),
    )


def test_checkpoint_recovery_is_safe_and_resume_continues_same_run(tmp_path: Path, monkeypatch):
    repo, prepared, task, caps = setup_prepared(tmp_path, monkeypatch)
    adapter = FakeAdapter(caps, checkpoint=True)
    monkeypatch.setattr(
        "projectctl.application.execution._adapter_for_provider",
        lambda provider: adapter,
    )

    started = start_prepared_run(repo, prepared.record.run_id)
    assert started.checkpoint is not None

    recovery = recover_run(repo, prepared.record.run_id)
    assert recovery.action == "checkpoint_resume_ready"
    assert recovery.resolved_status == RunStatus.RUNNING.value

    adapter.checkpoint = False
    monkeypatch.setattr(
        "projectctl.application.execution.read_current_quota",
        lambda account: fresh_quota(),
    )
    resumed = resume_checkpointed_run(repo, prepared.record.run_id)

    assert resumed.result is not None
    assert resumed.result.status == WorkerResultStatus.IMPLEMENTED
    assert resumed.record.status == RunStatus.VERIFYING
    assert resumed.record.checkpoint_ref is None
    assert resumed.record.checkpoint_at is None
    assert adapter.resumed_checkpoint.worker_thread_id == "thr-test"


def test_checkpoint_resume_fails_closed_if_partial_workspace_was_modified(tmp_path: Path, monkeypatch):
    repo, prepared, task, caps = setup_prepared(tmp_path, monkeypatch)
    adapter = FakeAdapter(caps, checkpoint=True)
    monkeypatch.setattr(
        "projectctl.application.execution._adapter_for_provider",
        lambda provider: adapter,
    )
    started = start_prepared_run(repo, prepared.record.run_id)
    worktree = Path(started.record.worktree_path)
    (worktree / "worker_output.py").write_text("tampered = True\n", encoding="utf-8")

    adapter.checkpoint = False
    monkeypatch.setattr(
        "projectctl.application.execution.read_current_quota",
        lambda account: fresh_quota(),
    )
    with pytest.raises(WorktreeError, match="workspace changed"):
        resume_checkpointed_run(repo, prepared.record.run_id)

    record = RunStore(repo).get(prepared.record.run_id)
    assert record.status == RunStatus.NEEDS_DECISION
    assert record.terminal_reason == RunTerminalReason.RECOVERY_UNSAFE


def test_checkpoint_resume_rejects_tampered_worker_request(tmp_path: Path, monkeypatch):
    repo, prepared, task, caps = setup_prepared(tmp_path, monkeypatch)
    adapter = FakeAdapter(caps, checkpoint=True)
    monkeypatch.setattr(
        "projectctl.application.execution._adapter_for_provider",
        lambda provider: adapter,
    )
    started = start_prepared_run(repo, prepared.record.run_id)

    request_path = (
        repo
        / ".projectctl"
        / "runs"
        / prepared.record.run_id
        / "worker-request.json"
    )
    raw = json.loads(request_path.read_text(encoding="utf-8"))
    raw["objective"] = "tampered objective"
    request_path.write_text(json.dumps(raw), encoding="utf-8")

    adapter.checkpoint = False
    monkeypatch.setattr(
        "projectctl.application.execution.read_current_quota",
        lambda account: fresh_quota(),
    )
    with pytest.raises(RunStoreError, match="original WorkerRequest"):
        resume_checkpointed_run(repo, prepared.record.run_id)

    record = RunStore(repo).get(prepared.record.run_id)
    assert record.status == RunStatus.NEEDS_DECISION
    assert record.terminal_reason == RunTerminalReason.CONTEXT_INVALID


def test_checkpoint_resume_rejects_tampered_checkpoint_artifact(tmp_path: Path, monkeypatch):
    repo, prepared, task, caps = setup_prepared(tmp_path, monkeypatch)
    adapter = FakeAdapter(caps, checkpoint=True)
    monkeypatch.setattr(
        "projectctl.application.execution._adapter_for_provider",
        lambda provider: adapter,
    )
    started = start_prepared_run(repo, prepared.record.run_id)
    checkpoint_path = repo / started.record.checkpoint_ref
    raw = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    raw["quota_stale"] = not raw["quota_stale"]
    checkpoint_path.write_text(json.dumps(raw), encoding="utf-8")

    adapter.checkpoint = False
    monkeypatch.setattr(
        "projectctl.application.execution.read_current_quota",
        lambda account: fresh_quota(),
    )
    with pytest.raises(RunStoreError, match="identity does not match"):
        resume_checkpointed_run(repo, prepared.record.run_id)

    record = RunStore(repo).get(prepared.record.run_id)
    assert record.status == RunStatus.NEEDS_DECISION
    assert record.terminal_reason == RunTerminalReason.RECOVERY_UNSAFE



def test_worker_start_refuses_lost_task_claim(tmp_path: Path, monkeypatch):
    repo, prepared, task, caps = setup_prepared(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "projectctl.application.execution._claimer",
        lambda root: FakeClaimer(valid=False),
    )
    monkeypatch.setattr(
        "projectctl.application.execution._adapter_for_provider",
        lambda provider: FakeAdapter(caps),
    )

    with pytest.raises(ClaimConflictError, match="ownership was lost"):
        start_prepared_run(repo, prepared.record.run_id)

    record = RunStore(repo).get(prepared.record.run_id)
    assert record.status == RunStatus.FAILED
    assert record.terminal_reason == RunTerminalReason.CLAIM_LOST
    events = RunStore(repo).events(prepared.record.run_id)
    assert any(event.event_type == "task.claim.lost" for event in events)


def test_checkpoint_resume_refuses_lost_task_claim(tmp_path: Path, monkeypatch):
    repo, prepared, task, caps = setup_prepared(tmp_path, monkeypatch)
    adapter = FakeAdapter(caps, checkpoint=True)
    monkeypatch.setattr(
        "projectctl.application.execution._adapter_for_provider",
        lambda provider: adapter,
    )
    started = start_prepared_run(repo, prepared.record.run_id)
    assert started.checkpoint is not None

    monkeypatch.setattr(
        "projectctl.application.execution._claimer",
        lambda root: FakeClaimer(valid=False),
    )
    monkeypatch.setattr(
        "projectctl.application.execution.read_current_quota",
        lambda account: fresh_quota(),
    )

    with pytest.raises(ClaimConflictError, match="ownership was lost"):
        resume_checkpointed_run(repo, prepared.record.run_id)

    record = RunStore(repo).get(prepared.record.run_id)
    assert record.status == RunStatus.FAILED
    assert record.terminal_reason == RunTerminalReason.CLAIM_LOST


def test_worker_start_releases_global_admission_after_turn(tmp_path: Path, monkeypatch):
    repo, prepared, task, caps = setup_prepared(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "projectctl.application.execution._adapter_for_provider",
        lambda provider: FakeAdapter(caps),
    )

    started = start_prepared_run(repo, prepared.record.run_id)

    assert started.record.status == RunStatus.VERIFYING
    admissions = AccountAdmissionStore()
    assert admissions.get("openai-default") is None
    event_types = [
        event["event_type"] for event in admissions.events("openai-default")
    ]
    assert event_types == ["acquired", "released"]
    run_events = RunStore(repo).events(prepared.record.run_id)
    assert any(event.event_type == "worker.admission_acquired" for event in run_events)
    assert any(event.event_type == "worker.quota_revalidated" for event in run_events)
    assert any(event.event_type == "worker.admission_released" for event in run_events)


def test_worker_start_conflict_preserves_claimed_and_never_probes(
    tmp_path: Path, monkeypatch
):
    repo, prepared, task, caps = setup_prepared(tmp_path, monkeypatch)
    admissions = AccountAdmissionStore()
    foreign = admissions.acquire(
        account_id="openai-default",
        project_instance_id="foreign-instance",
        project_id="foreign-project",
        run_id="foreign-run",
        lease_owner="foreign-owner",
    )
    monkeypatch.setattr(
        "projectctl.application.execution._adapter_for_provider",
        lambda provider: (_ for _ in ()).throw(
            AssertionError("worker provider must not be contacted without admission")
        ),
    )

    try:
        with pytest.raises(QuotaAdmissionError, match="already admitted"):
            start_prepared_run(repo, prepared.record.run_id)
    finally:
        admissions.release(foreign)

    record = RunStore(repo).get(prepared.record.run_id)
    assert record.status == RunStatus.CLAIMED
    events = RunStore(repo).events(prepared.record.run_id)
    deferred = [
        event
        for event in events
        if event.event_type == "worker.start_deferred"
    ]
    assert deferred[-1].payload["reason"] == "account_admission_unavailable"


def test_worker_start_revalidates_quota_inside_admission_and_releases_on_denial(
    tmp_path: Path, monkeypatch
):
    repo, prepared, task, caps = setup_prepared(tmp_path, monkeypatch)
    denied = QuotaSnapshot(
        provider="test",
        account="openai-default",
        observed_at=datetime.now(timezone.utc),
        five_hour=QuotaWindow(remaining_ratio=.95),
        weekly=QuotaWindow(remaining_ratio=.95),
        ordinary_usage_allowed=False,
    )
    monkeypatch.setattr(
        "projectctl.application.execution.read_current_quota",
        lambda account: denied,
    )
    monkeypatch.setattr(
        "projectctl.application.execution._adapter_for_provider",
        lambda provider: (_ for _ in ()).throw(
            AssertionError("worker provider must not be contacted after quota denial")
        ),
    )

    with pytest.raises(QuotaError, match="deferred"):
        start_prepared_run(repo, prepared.record.run_id)

    record = RunStore(repo).get(prepared.record.run_id)
    assert record.status == RunStatus.CLAIMED
    admissions = AccountAdmissionStore()
    assert admissions.get("openai-default") is None
    assert [
        event["event_type"] for event in admissions.events("openai-default")
    ] == ["acquired", "released"]


def test_checkpoint_resume_conflict_preserves_checkpoint_and_never_probes(
    tmp_path: Path, monkeypatch
):
    repo, prepared, task, caps = setup_prepared(tmp_path, monkeypatch)
    adapter = FakeAdapter(caps, checkpoint=True)
    monkeypatch.setattr(
        "projectctl.application.execution._adapter_for_provider",
        lambda provider: adapter,
    )
    started = start_prepared_run(repo, prepared.record.run_id)
    assert started.checkpoint is not None

    admissions = AccountAdmissionStore()
    foreign = admissions.acquire(
        account_id="openai-default",
        project_instance_id="foreign-instance",
        project_id="foreign-project",
        run_id="foreign-run",
        lease_owner="foreign-owner",
    )
    monkeypatch.setattr(
        "projectctl.application.execution._adapter_for_provider",
        lambda provider: (_ for _ in ()).throw(
            AssertionError("resume must not contact worker provider without admission")
        ),
    )

    try:
        with pytest.raises(QuotaAdmissionError, match="already admitted"):
            resume_checkpointed_run(repo, prepared.record.run_id)
    finally:
        admissions.release(foreign)

    record = RunStore(repo).get(prepared.record.run_id)
    assert record.status == RunStatus.RUNNING
    assert record.checkpoint_ref == started.record.checkpoint_ref
    events = RunStore(repo).events(prepared.record.run_id)
    deferred = [
        event
        for event in events
        if event.event_type == "worker.resume_deferred"
    ]
    assert deferred[-1].payload["reason"] == "account_admission_unavailable"


def test_worker_start_fails_closed_on_stale_quota_before_provider_contact(
    tmp_path: Path, monkeypatch
):
    repo, prepared, task, caps = setup_prepared(tmp_path, monkeypatch)
    stale = QuotaSnapshot(
        provider="test",
        account="openai-default",
        observed_at=datetime(2000, 1, 1, tzinfo=timezone.utc),
        five_hour=QuotaWindow(remaining_ratio=.95),
        weekly=QuotaWindow(remaining_ratio=.95),
        ordinary_usage_allowed=True,
    )
    monkeypatch.setattr(
        "projectctl.application.execution.read_current_quota",
        lambda account: stale,
    )
    monkeypatch.setattr(
        "projectctl.application.execution._adapter_for_provider",
        lambda provider: (_ for _ in ()).throw(
            AssertionError("worker provider must not be contacted with stale quota")
        ),
    )

    with pytest.raises(QuotaError, match="stale or insufficient"):
        start_prepared_run(repo, prepared.record.run_id)

    record = RunStore(repo).get(prepared.record.run_id)
    assert record.status == RunStatus.CLAIMED
