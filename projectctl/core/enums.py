from enum import StrEnum


class Ownership(StrEnum):
    HUMAN = "human_managed"
    TOOL = "tool_managed"
    GENERATED = "generated"


class TaskStatus(StrEnum):
    IDEA = "idea"
    PLANNED = "planned"
    READY = "ready"
    RUNNING = "running"
    BLOCKED = "blocked"
    NEEDS_DECISION = "needs_decision"
    FAILED = "failed"
    DONE = "done"
    CANCELLED = "cancelled"


class TaskType(StrEnum):
    TASK = "task"
    FEATURE = "feature"
    BUG = "bug"
    REFACTOR = "refactor"
    RESEARCH = "research"
    EXPERIMENT = "experiment"
    ARCHITECTURE = "architecture"
    SECURITY = "security"
    DOCS = "docs"
    CHORE = "chore"
    UNKNOWN = "unknown"


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"
    UNKNOWN = "unknown"


class ResourceClass(StrEnum):
    TRIVIAL = "trivial"
    SMALL = "small"
    MEDIUM = "medium"
    LARGE = "large"
    DEEP = "deep"
    UNKNOWN = "unknown"


class ModelProfile(StrEnum):
    ECONOMICAL = "economical"
    BALANCED = "balanced"
    STRONG = "strong"
    DEEP = "deep"


class ReasoningLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class QuotaSource(StrEnum):
    OFFICIAL = "official"
    MANUAL = "manual"
    ESTIMATED = "estimated"
    UNKNOWN = "unknown"


class ConfidenceLevel(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    UNKNOWN = "unknown"


class QuotaMode(StrEnum):
    NORMAL = "normal"
    CONSERVATION = "conservation"
    CRITICAL = "critical"
    UNKNOWN = "unknown"


class HealthStatus(StrEnum):
    PASS = "pass"
    WARN = "warn"
    ERROR = "error"


class RunStatusV1(StrEnum):
    """Legacy M0 run lifecycle retained for RunManifest v1 reads."""

    PLANNED = "planned"
    RUNNING = "running"
    CHECKPOINTED = "checkpointed"
    VERIFYING = "verifying"
    PASSED = "passed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    ABANDONED = "abandoned"


class RunStatus(StrEnum):
    """M1 execution lifecycle. Checkpoints are events, not lifecycle states."""

    PLANNED = "planned"
    PREPARING = "preparing"
    CLAIMED = "claimed"
    RUNNING = "running"
    VERIFYING = "verifying"
    READY_TO_INTEGRATE = "ready_to_integrate"
    INTEGRATING = "integrating"
    PASSED = "passed"
    BLOCKED_POLICY = "blocked_policy"
    NEEDS_DECISION = "needs_decision"
    FAILED = "failed"
    CANCELLED = "cancelled"
    ABANDONED = "abandoned"


class RunTerminalReason(StrEnum):
    WORKER_ERROR = "worker_error"
    VERIFICATION_FAILED = "verification_failed"
    POLICY_BLOCKED = "policy_blocked"
    CONTEXT_INVALID = "context_invalid"
    STALE_BASE = "stale_base"
    CLAIM_LOST = "claim_lost"
    TIMEOUT = "timeout"
    QUOTA_EXHAUSTED = "quota_exhausted"
    UNEXPECTED_GIT_HISTORY = "unexpected_git_history"
    INTEGRATION_CONFLICT = "integration_conflict"
    INFRASTRUCTURE_ERROR = "infrastructure_error"
    USER_CANCELLED = "user_cancelled"
    RECOVERY_UNSAFE = "recovery_unsafe"
    CAPABILITY_CHANGED = "capability_changed"
    WORKER_BLOCKED = "worker_blocked"
    WORKER_CANCELLED = "worker_cancelled"


class ExecutionSandboxMode(StrEnum):
    READ_ONLY = "read_only"
    WORKSPACE_WRITE = "workspace_write"
    DANGER_FULL_ACCESS = "danger_full_access"


class NetworkPolicy(StrEnum):
    DISABLED = "disabled"
    ENABLED = "enabled"


class ApprovalPolicy(StrEnum):
    DENY_ALL = "deny_all"
    EXPLICIT = "explicit"
    AUTO_REVIEW = "auto_review"


class CapabilityState(StrEnum):
    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"
    UNKNOWN = "unknown"


class WorkerMode(StrEnum):
    DEFAULT = "default"
    PLAN = "plan"
    GOAL = "goal"


class WorkerStrategyKind(StrEnum):
    DIRECT = "direct"
    PLAN_THEN_EXECUTE = "plan_then_execute"
    GOAL = "goal"
    REVIEW = "review"


class GoalStopCondition(StrEnum):
    OBJECTIVE_MET = "objective_met"
    PERMISSION_BLOCKED = "permission_blocked"
    QUOTA_THRESHOLD = "quota_threshold"
    REPEATED_FAILURE = "repeated_failure"
    HUMAN_DECISION_REQUIRED = "human_decision_required"
    BUDGET_EXHAUSTED = "budget_exhausted"
    BLOCKED = "blocked"


class WorkerResultStatus(StrEnum):
    IMPLEMENTED = "implemented"
    BLOCKED = "blocked"
    FAILED = "failed"
    CANCELLED = "cancelled"


class CheckpointReason(StrEnum):
    QUOTA_STALE = "quota_stale"
    QUOTA_CRITICAL = "quota_critical"
    QUOTA_BELOW_TASK_REQUIREMENT = "quota_below_task_requirement"


class VerificationCheckStatus(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    ERROR = "error"
    TIMED_OUT = "timed_out"
    SKIPPED = "skipped"


class ImportAction(StrEnum):
    CREATE = "create"
    UPDATE = "update"
    UNCHANGED = "unchanged"
    CONFLICT = "conflict"


class ExclusionReason(StrEnum):
    NOT_READY = "not_ready"
    BLOCKED = "blocked"
    HUMAN_DECISION = "human_decision_required"
    QUOTA_INSUFFICIENT = "quota_insufficient"
    QUOTA_UNKNOWN = "quota_unknown"
    MISSING_SPEC = "missing_spec"
    POLICY_VIOLATION = "policy_violation"
    INVALID_TASK = "invalid_task"
    STALE_TASK_SNAPSHOT = "stale_task_snapshot"


class RecommendationReason(StrEnum):
    TASK_COMPLEXITY = "task_complexity"
    HIGH_RISK = "high_risk"
    LOW_QUOTA = "low_quota"
    ARCHITECTURE_TASK = "architecture_task"
    RESEARCH_TASK = "research_task"
    DEFAULT_POLICY = "default_policy"


class AutoStopReason(StrEnum):
    MAX_TASKS_REACHED = "max_tasks_reached"
    NO_ELIGIBLE_TASK = "no_eligible_task"
    QUOTA_CRITICAL = "quota_critical"
    QUOTA_STALE = "quota_stale"
    QUOTA_CHECKPOINTED = "quota_checkpointed"
    HUMAN_DECISION_REQUIRED = "human_decision_required"
    POLICY_BLOCKED = "policy_blocked"
    RUN_FAILED = "run_failed"
    RECOVERY_REQUIRED = "recovery_required"
    ACTIVE_RUN_PRESENT = "active_run_present"
    MULTIPLE_ACTIVE_RUNS = "multiple_active_runs"
    MATERIAL_PROJECT_STATE_CHANGE = "material_project_state_change"
    RETRY_BUDGET_EXHAUSTED = "retry_budget_exhausted"
    COMPLETED = "completed"
