from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from projectctl.application.auto import _classify_terminal
from projectctl.core.enums import (
    AutoStopReason,
    CheckpointReason,
    ConfidenceLevel,
    QuotaMode,
    QuotaSource,
    ResourceClass,
    RunStatus,
)
from projectctl.quota.checkpointing import evaluate_checkpoint
from projectctl.schemas.auto import AutoRunPolicy
from projectctl.schemas.config import QuotaPolicy
from projectctl.schemas.quota import QuotaSnapshot, QuotaWindow

NOW = datetime(2026, 10, 3, 18, 0, tzinfo=timezone.utc)


def snapshot(five, weekly, *, age_seconds=0, allowed=True):
    return QuotaSnapshot(
        provider="test",
        account="acct",
        observed_at=NOW - timedelta(seconds=age_seconds),
        five_hour=QuotaWindow(
            remaining_ratio=five,
            source=QuotaSource.OFFICIAL,
            confidence=ConfidenceLevel.HIGH,
        ),
        weekly=QuotaWindow(
            remaining_ratio=weekly,
            source=QuotaSource.OFFICIAL,
            confidence=ConfidenceLevel.HIGH,
        ),
        ordinary_usage_allowed=allowed,
    )


def test_checkpoint_on_stale_live_quota():
    policy = QuotaPolicy(max_snapshot_age_seconds=60)
    decision = evaluate_checkpoint(
        policy=policy,
        resource_class=ResourceClass.SMALL,
        snapshot=snapshot(.9, .9, age_seconds=61),
        now=NOW,
    )
    assert decision is not None
    assert decision.reason == CheckpointReason.QUOTA_STALE
    assert decision.state.stale is True


def test_checkpoint_on_backend_quota_denial():
    decision = evaluate_checkpoint(
        policy=QuotaPolicy(),
        resource_class=ResourceClass.SMALL,
        snapshot=snapshot(.9, .9, allowed=False),
        now=NOW,
    )
    assert decision is not None
    assert decision.reason == CheckpointReason.QUOTA_CRITICAL
    assert decision.state.mode == QuotaMode.CRITICAL


def test_checkpoint_when_budget_no_longer_fits_current_task():
    decision = evaluate_checkpoint(
        policy=QuotaPolicy(),
        resource_class=ResourceClass.MEDIUM,
        snapshot=snapshot(.25, .60),
        now=NOW,
    )
    assert decision is not None
    assert decision.reason == CheckpointReason.QUOTA_BELOW_TASK_REQUIREMENT
    assert decision.state.mode == QuotaMode.CONSERVATION


def test_small_task_can_continue_in_conservation_when_budget_still_fits():
    decision = evaluate_checkpoint(
        policy=QuotaPolicy(),
        resource_class=ResourceClass.SMALL,
        snapshot=snapshot(.25, .60),
        now=NOW,
    )
    assert decision is None


def test_auto_treats_durable_quota_checkpoint_as_graceful_stop():
    record = SimpleNamespace(
        status=RunStatus.RUNNING,
        checkpoint_ref=".projectctl/runs/run-1/checkpoints/cp.json",
        terminal_reason=None,
    )
    reason = _classify_terminal(record, 1, AutoRunPolicy())
    assert reason == AutoStopReason.QUOTA_CHECKPOINTED
