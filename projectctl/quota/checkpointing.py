from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime
from typing import Callable

from projectctl.core.digest import digest
from projectctl.core.enums import CheckpointReason, QuotaMode, ResourceClass
from projectctl.core.time import utc_now
from projectctl.quota.manager import QuotaManager, QuotaState
from projectctl.quota.resolver import read_current_quota
from projectctl.schemas.config import QuotaPolicy
from projectctl.schemas.quota import QuotaSnapshot


@dataclass(frozen=True)
class QuotaCheckpointDecision:
    reason: CheckpointReason
    snapshot: QuotaSnapshot
    state: QuotaState

    @property
    def snapshot_digest(self) -> str:
        return digest(self.snapshot)


def evaluate_checkpoint(
    *,
    policy: QuotaPolicy,
    resource_class: ResourceClass,
    snapshot: QuotaSnapshot,
    now: datetime,
) -> QuotaCheckpointDecision | None:
    manager = QuotaManager(policy)
    state = manager.state(snapshot, now=now)

    if state.stale:
        return QuotaCheckpointDecision(
            reason=CheckpointReason.QUOTA_STALE,
            snapshot=snapshot,
            state=state,
        )
    if snapshot.ordinary_usage_allowed is False or state.mode == QuotaMode.CRITICAL:
        return QuotaCheckpointDecision(
            reason=CheckpointReason.QUOTA_CRITICAL,
            snapshot=snapshot,
            state=state,
        )
    if not manager.eligible_for_resource(resource_class, state):
        return QuotaCheckpointDecision(
            reason=CheckpointReason.QUOTA_BELOW_TASK_REQUIREMENT,
            snapshot=snapshot,
            state=state,
        )
    return None


class QuotaCheckpointMonitor:
    """Poll account quota while a worker turn is active and request one safe interrupt."""

    def __init__(
        self,
        *,
        account: str,
        policy: QuotaPolicy,
        resource_class: ResourceClass,
        interval_seconds: float | None = None,
        reader: Callable[[str], QuotaSnapshot] = read_current_quota,
        clock: Callable[[], datetime] = utc_now,
    ):
        self.account = account
        self.policy = policy
        self.resource_class = resource_class
        self.interval_seconds = (
            interval_seconds
            if interval_seconds is not None
            else policy.execution_monitor_interval_seconds
        )
        if self.interval_seconds <= 0:
            raise ValueError("Quota monitor interval must be positive.")
        self._reader = reader
        self._clock = clock
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._decision: QuotaCheckpointDecision | None = None
        self._error: BaseException | None = None

    @property
    def decision(self) -> QuotaCheckpointDecision | None:
        return self._decision

    @property
    def error(self) -> BaseException | None:
        return self._error

    def evaluate_once(self) -> QuotaCheckpointDecision | None:
        snapshot = self._reader(self.account)
        return evaluate_checkpoint(
            policy=self.policy,
            resource_class=self.resource_class,
            snapshot=snapshot,
            now=self._clock(),
        )

    def start(
        self,
        on_checkpoint: Callable[[QuotaCheckpointDecision], None],
    ) -> "QuotaCheckpointMonitor":
        if self._thread is not None:
            raise RuntimeError("Quota checkpoint monitor is already running.")

        def loop() -> None:
            while not self._stop.wait(self.interval_seconds):
                try:
                    decision = self.evaluate_once()
                    if decision is None:
                        continue
                    if self._stop.is_set():
                        return
                    on_checkpoint(decision)
                    self._decision = decision
                    self._stop.set()
                    return
                except BaseException as exc:
                    self._error = exc
                    self._stop.set()
                    return

        self._thread = threading.Thread(
            target=loop,
            name=f"projectctl-quota-monitor-{self.account}",
            daemon=True,
        )
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=max(1.0, min(5.0, self.interval_seconds + 0.5)))

    def assert_healthy(self) -> None:
        if self._error is not None:
            raise RuntimeError(f"Quota checkpoint monitor failed: {self._error}") from self._error
