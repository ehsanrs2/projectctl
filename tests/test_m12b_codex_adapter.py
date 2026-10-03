import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from projectctl.core.enums import (
    ApprovalPolicy,
    ExecutionSandboxMode,
    ModelProfile,
    NetworkPolicy,
    ReasoningLevel,
    WorkerStrategyKind,
)
from projectctl.core.errors import CapabilityMismatchError
from projectctl.schemas.execution import ExecutionPolicy, WorkerRequest
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
