from __future__ import annotations

from projectctl.core.enums import ExclusionReason, TaskStatus
from projectctl.quota.manager import QuotaManager, QuotaState
from projectctl.scheduler.resource import effective_resource_class
from projectctl.schemas.scheduler import EligibilityResult
from projectctl.schemas.task import NormalizedTask


def evaluate_eligibility(
    task: NormalizedTask,
    *,
    tasks_by_id: dict[str, NormalizedTask],
    quota_manager: QuotaManager,
    quota_state: QuotaState,
) -> EligibilityResult:
    reasons: list[ExclusionReason] = []
    if task.status != TaskStatus.READY:
        reasons.append(ExclusionReason.NOT_READY)

    unresolved_dependencies = [
        dep for dep in task.dependencies
        if dep not in tasks_by_id or tasks_by_id[dep].status != TaskStatus.DONE
    ]
    if unresolved_dependencies:
        reasons.append(ExclusionReason.BLOCKED)
    if task.human_decision_required:
        reasons.append(ExclusionReason.HUMAN_DECISION)

    resource = effective_resource_class(task)
    if not quota_manager.eligible_for_resource(resource, quota_state):
        if quota_state.five_hour_effective is None or quota_state.weekly_effective is None or quota_state.stale:
            reasons.append(ExclusionReason.QUOTA_UNKNOWN)
        else:
            reasons.append(ExclusionReason.QUOTA_INSUFFICIENT)

    return EligibilityResult(task_id=task.id, eligible=not reasons, reasons=reasons)
