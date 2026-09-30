from datetime import datetime, timedelta, timezone

from projectctl.core.enums import QuotaMode, QuotaSource, ConfidenceLevel, ResourceClass
from projectctl.quota.manager import QuotaManager
from projectctl.schemas.config import QuotaPolicy
from projectctl.schemas.quota import QuotaSnapshot, QuotaWindow

NOW = datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc)


def snapshot(five, weekly, *, age_seconds=0):
    return QuotaSnapshot(
        provider="manual",
        account="openai-default",
        observed_at=NOW - timedelta(seconds=age_seconds),
        five_hour=QuotaWindow(remaining_ratio=five, source=QuotaSource.MANUAL, confidence=ConfidenceLevel.MEDIUM),
        weekly=QuotaWindow(remaining_ratio=weekly, source=QuotaSource.MANUAL, confidence=ConfidenceLevel.MEDIUM),
    )


def test_quota_modes_use_effective_remaining_after_reserve():
    manager = QuotaManager(QuotaPolicy())
    assert manager.state(snapshot(.80, .80), now=NOW).mode == QuotaMode.NORMAL
    assert manager.state(snapshot(.40, .50), now=NOW).mode == QuotaMode.CONSERVATION
    assert manager.state(snapshot(.80, .20), now=NOW).mode == QuotaMode.CRITICAL


def test_stale_snapshot_fails_to_conservation():
    policy = QuotaPolicy(max_snapshot_age_seconds=60)
    state = QuotaManager(policy).state(snapshot(.90, .90, age_seconds=61), now=NOW)
    assert state.stale is True
    assert state.mode == QuotaMode.CONSERVATION


def test_unknown_or_stale_quota_only_allows_small_work():
    manager = QuotaManager(QuotaPolicy(max_snapshot_age_seconds=60))
    state = manager.state(snapshot(.90, .90, age_seconds=61), now=NOW)
    assert manager.eligible_for_resource(ResourceClass.TRIVIAL, state)
    assert manager.eligible_for_resource(ResourceClass.SMALL, state)
    assert not manager.eligible_for_resource(ResourceClass.MEDIUM, state)


def test_elapsed_reset_invalidates_snapshot():
    manager = QuotaManager(QuotaPolicy())
    snap = snapshot(.90, .90)
    snap.five_hour.reset_at = NOW - timedelta(seconds=1)
    state = manager.state(snap, now=NOW)
    assert state.stale is True
    assert state.mode == QuotaMode.CONSERVATION
