from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from projectctl.core.enums import QuotaMode, ResourceClass
from projectctl.schemas.config import QuotaPolicy
from projectctl.schemas.quota import QuotaSnapshot


@dataclass(frozen=True)
class QuotaState:
    mode: QuotaMode
    stale: bool
    five_hour_effective: float | None
    weekly_effective: float | None
    ordinary_usage_allowed: bool | None


class QuotaManager:
    def __init__(self, policy: QuotaPolicy):
        self.policy = policy

    def state(self, snapshot: QuotaSnapshot, *, now: datetime) -> QuotaState:
        if now.tzinfo is None:
            raise ValueError("Quota evaluation time must be timezone-aware.")
        age = (now.astimezone(timezone.utc) - snapshot.observed_at.astimezone(timezone.utc)).total_seconds()
        reset_elapsed = any(
            window.reset_at is not None and now.astimezone(timezone.utc) >= window.reset_at.astimezone(timezone.utc)
            for window in (snapshot.five_hour, snapshot.weekly)
        )
        stale = age > self.policy.max_snapshot_age_seconds or reset_elapsed

        five = self._effective(snapshot.five_hour.remaining_ratio, self.policy.reserve.five_hour)
        weekly = self._effective(snapshot.weekly.remaining_ratio, self.policy.reserve.weekly)

        if snapshot.ordinary_usage_allowed is False:
            mode = QuotaMode.CRITICAL
        elif stale or five is None or weekly is None:
            mode = self.policy.unknown_quota_mode
        elif weekly <= self.policy.thresholds.critical_weekly_below:
            mode = QuotaMode.CRITICAL
        elif (
            five < self.policy.thresholds.conservation_five_hour_below
            or weekly < self.policy.thresholds.conservation_weekly_below
        ):
            mode = QuotaMode.CONSERVATION
        else:
            mode = QuotaMode.NORMAL
        return QuotaState(
            mode=mode,
            stale=stale,
            five_hour_effective=five,
            weekly_effective=weekly,
            ordinary_usage_allowed=snapshot.ordinary_usage_allowed,
        )

    @staticmethod
    def _effective(value: float | None, reserve: float) -> float | None:
        if value is None:
            return None
        return max(0.0, value - reserve)

    def eligible_for_resource(self, resource: ResourceClass, state: QuotaState) -> bool:
        if state.ordinary_usage_allowed is False:
            return False
        if resource == ResourceClass.UNKNOWN:
            return False
        if state.five_hour_effective is None or state.weekly_effective is None or state.stale:
            return resource in {ResourceClass.TRIVIAL, ResourceClass.SMALL}
        requirement = getattr(self.policy.resource_requirements, resource.value)
        return (
            state.five_hour_effective >= requirement.min_five_hour
            and state.weekly_effective >= requirement.min_weekly
        )
