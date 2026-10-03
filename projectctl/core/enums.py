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


class WorkerResultStatus(StrEnum):
    IMPLEMENTED = "implemented"
    BLOCKED = "blocked"
    FAILED = "failed"
    CANCELLED = "cancelled"


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
