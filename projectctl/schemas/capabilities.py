from __future__ import annotations

from typing import Literal

from pydantic import AwareDatetime, Field, model_validator

from projectctl.core.enums import (
    ApprovalPolicy,
    CapabilityState,
    ExecutionSandboxMode,
    GoalStopCondition,
    NetworkPolicy,
    WorkerMode,
    WorkerStrategyKind,
)
from projectctl.schemas.base import ProjectCtlModel


class CapabilitySupport(ProjectCtlModel):
    runtime: CapabilityState = CapabilityState.UNKNOWN
    adapter: CapabilityState = CapabilityState.UNKNOWN
    experimental: bool = False
    note: str | None = None

    @property
    def usable(self) -> bool:
        return (
            self.runtime == CapabilityState.SUPPORTED
            and self.adapter == CapabilityState.SUPPORTED
        )


class WorkerRuntimeDescriptor(ProjectCtlModel):
    provider: str = Field(min_length=1)
    sdk_name: str | None = None
    sdk_version: str | None = None
    runtime_name: str | None = None
    runtime_version: str | None = None
    adapter_name: str | None = None
    adapter_version: str | None = None
    observed_at: AwareDatetime


class PermissionCapabilities(ProjectCtlModel):
    sandboxes: dict[ExecutionSandboxMode, CapabilitySupport] = Field(default_factory=dict)
    approvals: dict[ApprovalPolicy, CapabilitySupport] = Field(default_factory=dict)
    scoped_network_requests: CapabilitySupport = Field(default_factory=CapabilitySupport)
    scoped_filesystem_read_requests: CapabilitySupport = Field(default_factory=CapabilitySupport)
    scoped_filesystem_write_requests: CapabilitySupport = Field(default_factory=CapabilitySupport)


class WorkerCapabilities(ProjectCtlModel):
    schema_kind: Literal["projectctl.worker_capabilities"] = "projectctl.worker_capabilities"
    schema_version: Literal[1] = 1
    probe_kind: str = Field(default="unknown", min_length=1)
    runtime: WorkerRuntimeDescriptor
    modes: dict[WorkerMode, CapabilitySupport]
    permissions: PermissionCapabilities
    thread_resume: CapabilitySupport = Field(default_factory=CapabilitySupport)
    thread_fork: CapabilitySupport = Field(default_factory=CapabilitySupport)
    thread_compact: CapabilitySupport = Field(default_factory=CapabilitySupport)
    structured_output: CapabilitySupport = Field(default_factory=CapabilitySupport)
    skills: CapabilitySupport = Field(default_factory=CapabilitySupport)
    goal_pause_resume: CapabilitySupport = Field(default_factory=CapabilitySupport)
    notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def require_default_mode_entry(self):
        if WorkerMode.DEFAULT not in self.modes:
            raise ValueError("WorkerCapabilities must include default mode.")
        return self


class WorkerPhasePolicy(ProjectCtlModel):
    mode: WorkerMode
    sandbox: ExecutionSandboxMode
    network: NetworkPolicy = NetworkPolicy.DISABLED
    approval: ApprovalPolicy = ApprovalPolicy.DENY_ALL

    @model_validator(mode="after")
    def validate_mode_sandbox(self):
        if self.mode == WorkerMode.PLAN and self.sandbox != ExecutionSandboxMode.READ_ONLY:
            raise ValueError("Plan mode must use read_only sandbox.")
        return self


class GoalBudgetPolicy(ProjectCtlModel):
    max_turns: int = Field(default=6, ge=1, le=100)
    max_duration_seconds: int = Field(default=1800, ge=1)
    stop_on: list[GoalStopCondition] = Field(
        default_factory=lambda: [
            GoalStopCondition.OBJECTIVE_MET,
            GoalStopCondition.PERMISSION_BLOCKED,
            GoalStopCondition.QUOTA_THRESHOLD,
            GoalStopCondition.REPEATED_FAILURE,
            GoalStopCondition.HUMAN_DECISION_REQUIRED,
            GoalStopCondition.BUDGET_EXHAUSTED,
            GoalStopCondition.BLOCKED,
        ]
    )


class StrategyFallbackPolicy(ProjectCtlModel):
    allow_goal_to_plan_then_execute: bool = False
    allow_plan_to_direct: bool = False


class WorkerStrategyDecision(ProjectCtlModel):
    schema_kind: Literal["projectctl.worker_strategy_decision"] = "projectctl.worker_strategy_decision"
    schema_version: Literal[1] = 1
    task_id: str = Field(min_length=1)
    requested: WorkerStrategyKind
    resolved: WorkerStrategyKind | None = None
    compatible: bool
    capability_snapshot_digest: str = Field(min_length=1)
    planning: WorkerPhasePolicy | None = None
    execution: WorkerPhasePolicy | None = None
    goal: GoalBudgetPolicy | None = None
    unsupported: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)
    fallback_used: bool = False

    @model_validator(mode="after")
    def validate_strategy_shape(self):
        if self.compatible and self.resolved is None:
            raise ValueError("Compatible strategy decision requires resolved strategy.")
        if not self.compatible and self.resolved is not None:
            raise ValueError("Incompatible strategy decision must not resolve a strategy.")
        if self.resolved == WorkerStrategyKind.PLAN_THEN_EXECUTE:
            if self.planning is None or self.execution is None:
                raise ValueError("plan_then_execute requires planning and execution phases.")
            if self.planning.mode != WorkerMode.PLAN:
                raise ValueError("plan_then_execute planning phase must use plan mode.")
        if self.resolved == WorkerStrategyKind.GOAL and self.goal is None:
            raise ValueError("goal strategy requires goal budget policy.")
        if self.resolved == WorkerStrategyKind.REVIEW:
            if self.execution is None or self.execution.sandbox != ExecutionSandboxMode.READ_ONLY:
                raise ValueError("review strategy requires a read_only execution phase.")
        return self
