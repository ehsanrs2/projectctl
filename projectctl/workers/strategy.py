from __future__ import annotations

from projectctl.core.digest import digest
from projectctl.core.enums import (
    ApprovalPolicy,
    ExecutionSandboxMode,
    NetworkPolicy,
    ResourceClass,
    RiskLevel,
    TaskType,
    WorkerMode,
    WorkerStrategyKind,
)
from projectctl.schemas.capabilities import (
    GoalBudgetPolicy,
    StrategyFallbackPolicy,
    WorkerCapabilities,
    WorkerPhasePolicy,
    WorkerStrategyDecision,
)
from projectctl.schemas.task import NormalizedTask


def recommend_strategy(task: NormalizedTask) -> WorkerStrategyKind:
    if task.type in {TaskType.RESEARCH, TaskType.EXPERIMENT}:
        return WorkerStrategyKind.GOAL
    if task.type == TaskType.ARCHITECTURE:
        return WorkerStrategyKind.PLAN_THEN_EXECUTE
    if task.risk in {RiskLevel.HIGH, RiskLevel.CRITICAL}:
        return WorkerStrategyKind.PLAN_THEN_EXECUTE
    if task.resource_class in {ResourceClass.LARGE, ResourceClass.DEEP}:
        return WorkerStrategyKind.PLAN_THEN_EXECUTE
    if task.type == TaskType.UNKNOWN or task.resource_class == ResourceClass.UNKNOWN:
        return WorkerStrategyKind.PLAN_THEN_EXECUTE
    return WorkerStrategyKind.DIRECT


def _mode_usable(capabilities: WorkerCapabilities, mode: WorkerMode) -> bool:
    support = capabilities.modes.get(mode)
    return bool(support and support.usable)


def _supports_sandbox(
    capabilities: WorkerCapabilities,
    sandbox: ExecutionSandboxMode,
) -> bool:
    support = capabilities.permissions.sandboxes.get(sandbox)
    return bool(support and support.usable)


def _supports_approval(
    capabilities: WorkerCapabilities,
    approval: ApprovalPolicy,
) -> bool:
    support = capabilities.permissions.approvals.get(approval)
    return bool(support and support.usable)


def _evaluate(
    kind: WorkerStrategyKind,
    capabilities: WorkerCapabilities,
) -> tuple[bool, list[str]]:
    unsupported: list[str] = []

    def need(name: str, condition: bool) -> None:
        if not condition:
            unsupported.append(name)

    need("approval:deny_all", _supports_approval(capabilities, ApprovalPolicy.DENY_ALL))

    if kind == WorkerStrategyKind.DIRECT:
        need("mode:default", _mode_usable(capabilities, WorkerMode.DEFAULT))
        need(
            "sandbox:workspace_write",
            _supports_sandbox(capabilities, ExecutionSandboxMode.WORKSPACE_WRITE),
        )
    elif kind == WorkerStrategyKind.PLAN_THEN_EXECUTE:
        need("mode:plan", _mode_usable(capabilities, WorkerMode.PLAN))
        need("mode:default", _mode_usable(capabilities, WorkerMode.DEFAULT))
        need(
            "sandbox:read_only",
            _supports_sandbox(capabilities, ExecutionSandboxMode.READ_ONLY),
        )
        need(
            "sandbox:workspace_write",
            _supports_sandbox(capabilities, ExecutionSandboxMode.WORKSPACE_WRITE),
        )
    elif kind == WorkerStrategyKind.GOAL:
        need("mode:goal", _mode_usable(capabilities, WorkerMode.GOAL))
        need(
            "sandbox:workspace_write",
            _supports_sandbox(capabilities, ExecutionSandboxMode.WORKSPACE_WRITE),
        )
        need("thread_resume", capabilities.thread_resume.usable)
        need("goal_pause_resume", capabilities.goal_pause_resume.usable)
    elif kind == WorkerStrategyKind.REVIEW:
        need("mode:default", _mode_usable(capabilities, WorkerMode.DEFAULT))
        need(
            "sandbox:read_only",
            _supports_sandbox(capabilities, ExecutionSandboxMode.READ_ONLY),
        )

    return not unsupported, unsupported


def _phases(kind: WorkerStrategyKind):
    if kind == WorkerStrategyKind.DIRECT:
        return (
            None,
            WorkerPhasePolicy(
                mode=WorkerMode.DEFAULT,
                sandbox=ExecutionSandboxMode.WORKSPACE_WRITE,
                network=NetworkPolicy.DISABLED,
                approval=ApprovalPolicy.DENY_ALL,
            ),
            None,
        )
    if kind == WorkerStrategyKind.PLAN_THEN_EXECUTE:
        return (
            WorkerPhasePolicy(
                mode=WorkerMode.PLAN,
                sandbox=ExecutionSandboxMode.READ_ONLY,
                network=NetworkPolicy.DISABLED,
                approval=ApprovalPolicy.DENY_ALL,
            ),
            WorkerPhasePolicy(
                mode=WorkerMode.DEFAULT,
                sandbox=ExecutionSandboxMode.WORKSPACE_WRITE,
                network=NetworkPolicy.DISABLED,
                approval=ApprovalPolicy.DENY_ALL,
            ),
            None,
        )
    if kind == WorkerStrategyKind.GOAL:
        return (
            None,
            WorkerPhasePolicy(
                mode=WorkerMode.GOAL,
                sandbox=ExecutionSandboxMode.WORKSPACE_WRITE,
                network=NetworkPolicy.DISABLED,
                approval=ApprovalPolicy.DENY_ALL,
            ),
            GoalBudgetPolicy(),
        )
    if kind == WorkerStrategyKind.REVIEW:
        return (
            None,
            WorkerPhasePolicy(
                mode=WorkerMode.DEFAULT,
                sandbox=ExecutionSandboxMode.READ_ONLY,
                network=NetworkPolicy.DISABLED,
                approval=ApprovalPolicy.DENY_ALL,
            ),
            None,
        )
    raise AssertionError(f"Unhandled worker strategy: {kind}")


def negotiate_strategy(
    task: NormalizedTask,
    capabilities: WorkerCapabilities,
    *,
    requested: WorkerStrategyKind | None = None,
    fallback: StrategyFallbackPolicy | None = None,
) -> WorkerStrategyDecision:
    requested_kind = requested or recommend_strategy(task)
    fallback = fallback or StrategyFallbackPolicy()
    cap_digest = digest(capabilities)

    compatible, unsupported = _evaluate(requested_kind, capabilities)
    if compatible:
        planning, execution, goal = _phases(requested_kind)
        return WorkerStrategyDecision(
            task_id=task.id,
            requested=requested_kind,
            resolved=requested_kind,
            compatible=True,
            capability_snapshot_digest=cap_digest,
            planning=planning,
            execution=execution,
            goal=goal,
            reasons=[f"Strategy {requested_kind.value} is supported by the probed worker surface."],
        )

    fallback_kinds: list[WorkerStrategyKind] = []
    if (
        requested_kind == WorkerStrategyKind.GOAL
        and fallback.allow_goal_to_plan_then_execute
    ):
        fallback_kinds.append(WorkerStrategyKind.PLAN_THEN_EXECUTE)
        if fallback.allow_plan_to_direct:
            fallback_kinds.append(WorkerStrategyKind.DIRECT)
    elif (
        requested_kind == WorkerStrategyKind.PLAN_THEN_EXECUTE
        and fallback.allow_plan_to_direct
    ):
        fallback_kinds.append(WorkerStrategyKind.DIRECT)

    attempted: list[str] = []
    for fallback_kind in fallback_kinds:
        fallback_ok, fallback_unsupported = _evaluate(fallback_kind, capabilities)
        if fallback_ok:
            planning, execution, goal = _phases(fallback_kind)
            return WorkerStrategyDecision(
                task_id=task.id,
                requested=requested_kind,
                resolved=fallback_kind,
                compatible=True,
                capability_snapshot_digest=cap_digest,
                planning=planning,
                execution=execution,
                goal=goal,
                unsupported=unsupported,
                reasons=[
                    f"Requested strategy {requested_kind.value} was unsupported.",
                    f"Explicit fallback resolved to {fallback_kind.value}.",
                ],
                fallback_used=True,
            )
        attempted.append(fallback_kind.value)
        unsupported.extend(
            f"fallback:{fallback_kind.value}:{value}"
            for value in fallback_unsupported
        )

    return WorkerStrategyDecision(
        task_id=task.id,
        requested=requested_kind,
        compatible=False,
        capability_snapshot_digest=cap_digest,
        unsupported=sorted(set(unsupported)),
        reasons=[
            "Requested worker strategy is not supported by the effective runtime/adapter capability surface.",
            "No implicit strategy downgrade was applied.",
        ],
    )
