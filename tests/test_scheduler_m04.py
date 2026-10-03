from datetime import datetime, timedelta, timezone

from projectctl.core.enums import (
    ConfidenceLevel, ModelProfile, QuotaMode, QuotaSource, ResourceClass,
    RiskLevel, TaskStatus, TaskType,
)
from projectctl.scheduler.digests import semantic_task_snapshot_digest
from projectctl.scheduler.router import recommend_model
from projectctl.scheduler.service import SchedulerService
from projectctl.schemas.config import ProjectConfig, ProjectIdentity
from projectctl.schemas.quota import QuotaSnapshot, QuotaWindow
from projectctl.schemas.task import NormalizedTask, TaskSnapshot, TaskSource

NOW = datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc)


def task(task_id, *, priority=5, status=TaskStatus.READY, blocks=None, deps=None, risk=RiskLevel.LOW,
         resource=ResourceClass.SMALL, type=TaskType.TASK, ready_since=None, human=False):
    return NormalizedTask(
        id=task_id, title=task_id,
        source=TaskSource(provider="test", external_id=task_id, observed_at=NOW),
        status=status, priority=priority, blocks=blocks or [], dependencies=deps or [],
        risk=risk, resource_class=resource, type=type,
        ready_since=ready_since, human_decision_required=human,
    )


def quota(five=.90, weekly=.90):
    return QuotaSnapshot(
        provider="manual", account="openai-default", observed_at=NOW,
        five_hour=QuotaWindow(remaining_ratio=five, source=QuotaSource.MANUAL, confidence=ConfidenceLevel.MEDIUM),
        weekly=QuotaWindow(remaining_ratio=weekly, source=QuotaSource.MANUAL, confidence=ConfidenceLevel.MEDIUM),
    )


def config():
    return ProjectConfig(project=ProjectIdentity(id="demo"))


def test_scheduler_excludes_blocked_and_human_decision_tasks():
    tasks = [
        task("done", status=TaskStatus.DONE),
        task("blocked", deps=["missing"]),
        task("human", priority=10, human=True),
        task("ready", priority=4),
    ]
    snap = TaskSnapshot(provider="test", captured_at=NOW, source_revision="r1", tasks=tasks)
    decision = SchedulerService().decide(config=config(), tasks=snap, quota=quota(), now=NOW)
    assert decision.selected_task_id == "ready"
    by_id = {c.task_id: c for c in decision.candidates}
    assert not by_id["blocked"].eligibility.eligible
    assert not by_id["human"].eligibility.eligible


def test_scheduler_tie_break_is_deterministic_priority_unblock_age_id():
    old = NOW - timedelta(days=10)
    tasks = [
        task("b", priority=5, ready_since=old),
        task("a", priority=5, ready_since=old),
    ]
    snap = TaskSnapshot(provider="test", captured_at=NOW, source_revision="same", tasks=tasks)
    first = SchedulerService().decide(config=config(), tasks=snap, quota=quota(), now=NOW)
    second = SchedulerService().decide(config=config(), tasks=snap, quota=quota(), now=NOW)
    assert first.selected_task_id == "a"
    assert first == second


def test_low_quota_excludes_large_work_but_keeps_small():
    tasks = [task("large", priority=10, resource=ResourceClass.LARGE), task("small", priority=4)]
    snap = TaskSnapshot(provider="test", captured_at=NOW, source_revision="r", tasks=tasks)
    decision = SchedulerService().decide(config=config(), tasks=snap, quota=quota(.25, .25), now=NOW)
    assert decision.selected_task_id == "small"
    large = next(c for c in decision.candidates if c.task_id == "large")
    assert not large.eligibility.eligible


def test_router_elevates_high_risk_and_preserves_reasoning_under_pressure():
    t = task("risk", resource=ResourceClass.MEDIUM, risk=RiskLevel.HIGH)
    rec = recommend_model(t, quota_mode=QuotaMode.CONSERVATION, config=config())
    assert rec.profile in {ModelProfile.STRONG, ModelProfile.DEEP}
    assert rec.reasoning.value == "high"


def test_semantic_task_digest_ignores_capture_and_observation_times():
    t1 = task("a")
    t2 = t1.model_copy(deep=True)
    t2.source.observed_at = NOW + timedelta(minutes=2)
    s1 = TaskSnapshot(provider="test", captured_at=NOW, source_revision="r", tasks=[t1])
    s2 = TaskSnapshot(provider="test", captured_at=NOW + timedelta(minutes=5), source_revision="r", tasks=[t2])
    assert semantic_task_snapshot_digest(s1) == semantic_task_snapshot_digest(s2)
