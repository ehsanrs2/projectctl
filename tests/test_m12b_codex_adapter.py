import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from projectctl.core.enums import (
    ApprovalPolicy,
    CheckpointReason,
    ExecutionSandboxMode,
    ModelProfile,
    QuotaMode,
    NetworkPolicy,
    ReasoningLevel,
    WorkerStrategyKind,
)
from projectctl.core.errors import CapabilityMismatchError
from projectctl.schemas.execution import ExecutionPolicy, WorkerCheckpoint, WorkerRequest
from projectctl.schemas.quota import QuotaSnapshot, QuotaWindow
from projectctl.schemas.run import WorkerDescriptor
from projectctl.workers.codex.adapter import CodexBindings, CodexWorkerAdapter

NOW = datetime(2026, 10, 3, 6, 0, tzinfo=timezone.utc)


class Approval:
    deny_all = "deny-all"
    auto_review = "auto-review"


class Sandbox:
    read_only = "read-only"
    workspace_write = "workspace-write"


class ExternalMessage:
    def __init__(self, *, tool_name, namespace, content):
        self.tool_name = tool_name
        self.namespace = namespace
        self.content = content


class FakeConfig:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


class FakeThread:
    def __init__(self, owner):
        self.owner = owner
        self.id = "thr-test"

    def run(self, message, **kwargs):
        self.owner.run_message = message
        self.owner.run_kwargs = kwargs
        return SimpleNamespace(
            status=SimpleNamespace(value="completed"),
            final_response=json.dumps(
                {
                    "status": "implemented",
                    "summary": "implemented safely",
                    "blockers": [],
                    "requested_permissions": [],
                    "suggested_verification": ["pytest"],
                }
            ),
        )


class FakeCodex:
    last = None

    def __init__(self, *, config):
        self.config = config
        self.thread_kwargs = None
        self.run_kwargs = None
        self.run_message = None
        self.metadata = SimpleNamespace(
            serverInfo=SimpleNamespace(version="0.160.0")
        )
        FakeCodex.last = self

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def thread_start(self, **kwargs):
        self.thread_kwargs = kwargs
        return FakeThread(self)


def bindings():
    return CodexBindings(
        Codex=FakeCodex,
        CodexConfig=FakeConfig,
        ApprovalMode=Approval,
        Sandbox=Sandbox,
        ExternalMessage=ExternalMessage,
        sdk_version="0.160.0",
    )


def request(strategy=WorkerStrategyKind.DIRECT, sandbox=ExecutionSandboxMode.WORKSPACE_WRITE):
    return WorkerRequest(
        run_id="run-1",
        task_id="t1",
        base_commit="abcdef1",
        branch_name="projectctl/run/run-1",
        worktree_id="run-1",
        execution_plan_digest="plan",
        capability_snapshot_digest="caps",
        strategy_decision_digest="strategy",
        strategy=strategy,
        context_manifest=".projectctl/runs/run-1/context-manifest.json",
        context_manifest_digest="ctx",
        context_sources=["AGENTS.md", "docs/PROJECT.md"],
        worker=WorkerDescriptor(
            provider="codex",
            model_profile=ModelProfile.BALANCED,
            reasoning=ReasoningLevel.MEDIUM,
        ),
        execution_policy=ExecutionPolicy(
            sandbox=sandbox,
            network=NetworkPolicy.DISABLED,
            approval=ApprovalPolicy.DENY_ALL,
        ),
        objective="Implement t1",
    )


def test_codex_adapter_uses_fail_closed_sdk_controls(tmp_path: Path):
    adapter = CodexWorkerAdapter(bindings_loader=bindings)
    result = adapter.start(request(), workspace=tmp_path)

    instance = FakeCodex.last
    assert result.status.value == "implemented"
    assert result.worker_thread_id == "thr-test"
    assert instance.config.kwargs["config_overrides"] == (
        "sandbox_workspace_write.network_access=false",
    )
    assert instance.thread_kwargs["approval_mode"] == Approval.deny_all
    assert instance.thread_kwargs["sandbox"] == Sandbox.workspace_write
    assert instance.thread_kwargs["ephemeral"] is False
    assert instance.thread_kwargs["config"]["sandbox_workspace_write"]["network_access"] is False
    assert instance.run_kwargs["approval_mode"] == Approval.deny_all
    assert instance.run_kwargs["sandbox"] == Sandbox.workspace_write
    assert instance.run_kwargs["output_schema"]["additionalProperties"] is False
    assert instance.run_message.tool_name == "projectctl_task"
    assert "AGENTS.md" in instance.run_message.content


def test_review_uses_read_only_sandbox(tmp_path: Path):
    adapter = CodexWorkerAdapter(bindings_loader=bindings)
    adapter.start(
        request(
            strategy=WorkerStrategyKind.REVIEW,
            sandbox=ExecutionSandboxMode.READ_ONLY,
        ),
        workspace=tmp_path,
    )
    assert FakeCodex.last.thread_kwargs["sandbox"] == Sandbox.read_only


@pytest.mark.parametrize(
    "strategy",
    [WorkerStrategyKind.PLAN_THEN_EXECUTE, WorkerStrategyKind.GOAL],
)
def test_native_plan_and_goal_fail_closed_until_stable_adapter_exists(
    tmp_path: Path, strategy
):
    adapter = CodexWorkerAdapter(bindings_loader=bindings)
    with pytest.raises(CapabilityMismatchError, match="not available"):
        adapter.start(request(strategy=strategy), workspace=tmp_path)


class FakeTurn:
    def __init__(self):
        self.id = "turn-test"
        self.interrupted = False

    def interrupt(self):
        self.interrupted = True
        return SimpleNamespace()

    def run(self):
        return SimpleNamespace(
            status=SimpleNamespace(value="interrupted"),
            final_response=None,
        )


class CheckpointThread(FakeThread):
    def turn(self, message, **kwargs):
        self.owner.run_message = message
        self.owner.run_kwargs = kwargs
        self.owner.turn = FakeTurn()
        return self.owner.turn


class CheckpointCodex(FakeCodex):
    def thread_start(self, **kwargs):
        self.thread_kwargs = kwargs
        return CheckpointThread(self)

    def thread_resume(self, thread_id, **kwargs):
        self.resumed_thread_id = thread_id
        self.thread_kwargs = kwargs
        return FakeThread(self)


def checkpoint_bindings():
    base = bindings()
    return CodexBindings(
        Codex=CheckpointCodex,
        CodexConfig=base.CodexConfig,
        ApprovalMode=base.ApprovalMode,
        Sandbox=base.Sandbox,
        ExternalMessage=base.ExternalMessage,
        sdk_version=base.sdk_version,
    )


class FakeCheckpointMonitor:
    def __init__(self):
        self.decision = None

    def start(self, callback):
        quota = QuotaSnapshot(
            provider="test",
            account="acct",
            observed_at=NOW,
            five_hour=QuotaWindow(),
            weekly=QuotaWindow(),
        )
        from projectctl.core.digest import digest
        self.decision = SimpleNamespace(
            reason=CheckpointReason.QUOTA_BELOW_TASK_REQUIREMENT,
            snapshot=quota,
            snapshot_digest=digest(quota),
            state=SimpleNamespace(mode=QuotaMode.CONSERVATION, stale=False),
        )
        callback(self.decision)
        return self

    def stop(self):
        return None

    def assert_healthy(self):
        return None


def test_codex_adapter_interrupts_turn_into_worker_checkpoint(tmp_path: Path):
    adapter = CodexWorkerAdapter(bindings_loader=checkpoint_bindings)
    result = adapter.start(
        request(),
        workspace=tmp_path,
        checkpoint_monitor=FakeCheckpointMonitor(),
    )

    assert isinstance(result, WorkerCheckpoint)
    assert result.worker_thread_id == "thr-test"
    assert result.worker_turn_id == "turn-test"
    assert result.reason == CheckpointReason.QUOTA_BELOW_TASK_REQUIREMENT
    assert CheckpointCodex.last.turn.interrupted is True


def test_codex_adapter_resumes_same_thread_after_checkpoint(tmp_path: Path):
    adapter = CodexWorkerAdapter(bindings_loader=checkpoint_bindings)
    req = request()
    checkpoint = WorkerCheckpoint(
        run_id=req.run_id,
        task_id=req.task_id,
        worker_thread_id="thr-original",
        worker_turn_id="turn-old",
        worktree_id=req.worktree_id,
        base_commit=req.base_commit,
        branch_name=req.branch_name,
        context_manifest_digest=req.context_manifest_digest,
        reason=CheckpointReason.QUOTA_CRITICAL,
        quota_snapshot=QuotaSnapshot(
            provider="test",
            account="acct",
            observed_at=NOW,
            five_hour=QuotaWindow(),
            weekly=QuotaWindow(),
        ),
        quota_snapshot_digest=__import__(
            "projectctl.core.digest", fromlist=["digest"]
        ).digest(
            QuotaSnapshot(
                provider="test",
                account="acct",
                observed_at=NOW,
                five_hour=QuotaWindow(),
                weekly=QuotaWindow(),
            )
        ),
        quota_mode=QuotaMode.CRITICAL,
        quota_stale=False,
        checkpoint_at=NOW,
    )

    result = adapter.resume(checkpoint, req, workspace=tmp_path)

    assert result.status.value == "implemented"
    assert CheckpointCodex.last.resumed_thread_id == "thr-original"
    assert CheckpointCodex.last.run_message.tool_name == "projectctl_checkpoint_resume"
