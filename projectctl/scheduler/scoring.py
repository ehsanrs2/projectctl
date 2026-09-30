from __future__ import annotations

from datetime import datetime, timezone

from projectctl.core.enums import QuotaMode, ResourceClass, RiskLevel
from projectctl.scheduler.resource import effective_resource_class
from projectctl.schemas.config import SchedulerConfig
from projectctl.schemas.scheduler import ScoreBreakdown
from projectctl.schemas.task import NormalizedTask


_RISK = {
    RiskLevel.LOW: 0.0,
    RiskLevel.MEDIUM: 2.0,
    RiskLevel.HIGH: 5.0,
    RiskLevel.CRITICAL: 8.0,
    RiskLevel.UNKNOWN: 3.0,
}
_RESOURCE = {
    ResourceClass.TRIVIAL: 0.0,
    ResourceClass.SMALL: 1.0,
    ResourceClass.MEDIUM: 3.0,
    ResourceClass.LARGE: 5.0,
    ResourceClass.DEEP: 8.0,
    ResourceClass.UNKNOWN: 4.0,
}


def _urgency(task: NormalizedTask, now: datetime) -> float:
    if task.due_at is None:
        return 0.0
    seconds = (task.due_at.astimezone(timezone.utc) - now.astimezone(timezone.utc)).total_seconds()
    days = seconds / 86400
    if days <= 1:
        return 5.0
    if days <= 3:
        return 4.0
    if days <= 7:
        return 3.0
    if days <= 14:
        return 2.0
    return 1.0


def _age_bonus(task: NormalizedTask, now: datetime) -> float:
    start = task.ready_since or task.created_at
    if start is None:
        return 0.0
    days = (now.astimezone(timezone.utc) - start.astimezone(timezone.utc)).total_seconds() / 86400
    if days >= 30:
        return 3.0
    if days >= 14:
        return 2.0
    if days >= 7:
        return 1.0
    return 0.0


def _quota_penalty(resource: ResourceClass, mode: QuotaMode) -> float:
    rank = {
        ResourceClass.TRIVIAL: 0,
        ResourceClass.SMALL: 1,
        ResourceClass.MEDIUM: 2,
        ResourceClass.LARGE: 3,
        ResourceClass.DEEP: 4,
        ResourceClass.UNKNOWN: 2,
    }[resource]
    if mode == QuotaMode.NORMAL:
        return 0.0
    if mode in {QuotaMode.CONSERVATION, QuotaMode.UNKNOWN}:
        return [0.0, 1.0, 4.0, 7.0, 10.0][rank]
    return [1.0, 3.0, 7.0, 9.0, 10.0][rank]


def score_task(task: NormalizedTask, *, config: SchedulerConfig, quota_mode: QuotaMode, now: datetime) -> ScoreBreakdown:
    w = config.weights
    resource = effective_resource_class(task)
    raw = {
        "priority": float(task.priority) * w.priority,
        # Active milestone is not structured in M0.4 yet; do not invent relevance.
        "milestone_relevance": 0.0 * w.milestone_relevance,
        "unblock_value": min(10.0, float(len(task.blocks) * 2)) * w.unblock_value,
        "information_gain": float(task.information_gain) * w.information_gain,
        "urgency": _urgency(task, now) * w.urgency,
        "age_bonus": _age_bonus(task, now) * w.age_bonus,
        "risk_penalty": _RISK[task.risk] * w.risk_penalty,
        "resource_penalty": _RESOURCE[resource] * w.resource_penalty,
        "quota_penalty": _quota_penalty(resource, quota_mode) * w.quota_penalty,
    }
    total = (
        raw["priority"] + raw["milestone_relevance"] + raw["unblock_value"]
        + raw["information_gain"] + raw["urgency"] + raw["age_bonus"]
        - raw["risk_penalty"] - raw["resource_penalty"] - raw["quota_penalty"]
    )
    p = config.score_precision
    values = {key: round(value, p) for key, value in raw.items()}
    return ScoreBreakdown(**values, total=round(total, p))
