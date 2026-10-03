from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from projectctl.core.enums import (
    ApprovalPolicy,
    CapabilityState,
    ExecutionSandboxMode,
    ResourceClass,
    RiskLevel,
    TaskStatus,
    TaskType,
    WorkerMode,
    WorkerStrategyKind,
)
from projectctl.schemas.capabilities import (
    CapabilitySupport,
    PermissionCapabilities,
    StrategyFallbackPolicy,
    WorkerCapabilities,
    WorkerPhasePolicy,
    WorkerRuntimeDescriptor,
)
from projectctl.schemas.task import NormalizedTask, TaskSource
from projectctl.workers.strategy import negotiate_strategy, recommend_strategy

NOW = datetime(2026, 10, 3, 6, 0, tzinfo=timezone.utc)


def support(runtime=True, adapter=True):
    return CapabilitySupport(
        runtime=CapabilityState.SUPPORTED if runtime else CapabilityState.UNSUPPORTED,
        adapter=CapabilityState.SUPPORTED if adapter else CapabilityState.UNSUPPORTED,
    )


def capabilities(*, plan=True, goal=True):
    return WorkerCapabilities(
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
            WorkerMode.DEFAULT: support(),
            WorkerMode.PLAN: support(runtime=plan, adapter=plan),
            WorkerMode.GOAL: support(runtime=goal, adapter=goal),
        },
        permissions=PermissionCapabilities(
            sandboxes={
                ExecutionSandboxMode.READ_ONLY: support(),
                ExecutionSandboxMode.WORKSPACE_WRITE: support(),
                ExecutionSandboxMode.DANGER_FULL_ACCESS: support(),
            },
            approvals={
                ApprovalPolicy.DENY_ALL: support(),
                ApprovalPolicy.AUTO_REVIEW: support(),
                ApprovalPolicy.EXPLICIT: support(runtime=False, adapter=False),
            },
        ),
        thread_resume=support(),
        goal_pause_resume=support(runtime=goal, adapter=goal),
    )


def task(
    task_id="t1",
    *,
    type=TaskType.FEATURE,
    resource=ResourceClass.SMALL,
    risk=RiskLevel.LOW,
):
    return NormalizedTask(
        id=task_id,
        title=task_id,
        source=TaskSource(provider="test", external_id=task_id),
        type=type,
        status=TaskStatus.READY,
        resource_class=resource,
        risk=risk,
    )


def test_plan_phase_is_always_read_only():
    with pytest.raises(ValidationError, match="Plan mode must use read_only"):
        WorkerPhasePolicy(
            mode=WorkerMode.PLAN,
            sandbox=ExecutionSandboxMode.WORKSPACE_WRITE,
        )


def test_strategy_recommendation_is_task_based_not_runtime_based():
    assert recommend_strategy(task(type=TaskType.RESEARCH)) == WorkerStrategyKind.GOAL
    assert (
        recommend_strategy(task(type=TaskType.ARCHITECTURE))
        == WorkerStrategyKind.PLAN_THEN_EXECUTE
    )
    assert (
        recommend_strategy(task(type=TaskType.FEATURE, resource=ResourceClass.LARGE))
        == WorkerStrategyKind.PLAN_THEN_EXECUTE
    )
    assert recommend_strategy(task(type=TaskType.DOCS)) == WorkerStrategyKind.DIRECT


def test_plan_then_execute_binds_plan_to_read_only():
    decision = negotiate_strategy(
        task(type=TaskType.ARCHITECTURE),
        capabilities(),
    )
    assert decision.compatible is True
    assert decision.resolved == WorkerStrategyKind.PLAN_THEN_EXECUTE
    assert decision.planning.mode == WorkerMode.PLAN
    assert decision.planning.sandbox == ExecutionSandboxMode.READ_ONLY
    assert decision.execution.sandbox == ExecutionSandboxMode.WORKSPACE_WRITE


def test_goal_does_not_silently_fallback():
    decision = negotiate_strategy(
        task(type=TaskType.RESEARCH),
        capabilities(goal=False),
    )
    assert decision.compatible is False
    assert decision.resolved is None
    assert decision.fallback_used is False
    assert "mode:goal" in decision.unsupported


def test_goal_fallback_requires_explicit_policy():
    decision = negotiate_strategy(
        task(type=TaskType.RESEARCH),
        capabilities(goal=False, plan=True),
        fallback=StrategyFallbackPolicy(
            allow_goal_to_plan_then_execute=True,
        ),
    )
    assert decision.compatible is True
    assert decision.resolved == WorkerStrategyKind.PLAN_THEN_EXECUTE
    assert decision.fallback_used is True


def test_review_strategy_is_read_only():
    decision = negotiate_strategy(
        task(type=TaskType.SECURITY),
        capabilities(),
        requested=WorkerStrategyKind.REVIEW,
    )
    assert decision.compatible is True
    assert decision.resolved == WorkerStrategyKind.REVIEW
    assert decision.execution.sandbox == ExecutionSandboxMode.READ_ONLY


def test_strategy_requires_effective_adapter_permission_support():
    caps = capabilities()
    caps.permissions.approvals[ApprovalPolicy.DENY_ALL] = support(
        runtime=True,
        adapter=False,
    )
    decision = negotiate_strategy(task(), caps)
    assert decision.compatible is False
    assert "approval:deny_all" in decision.unsupported
