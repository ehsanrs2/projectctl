from __future__ import annotations

import threading
from contextlib import AbstractContextManager

from projectctl.core.errors import RunLeaseError
from projectctl.storage.runs import RunStore


class LeaseHeartbeat(AbstractContextManager["LeaseHeartbeat"]):
    """Keep a run lease alive while a synchronous long-running operation executes."""

    def __init__(
        self,
        store: RunStore,
        run_id: str,
        *,
        owner: str,
        ttl_seconds: float = 300,
        interval_seconds: float = 60,
    ):
        if ttl_seconds <= 0:
            raise ValueError("Lease TTL must be positive.")
        if interval_seconds <= 0 or interval_seconds >= ttl_seconds:
            raise ValueError("Heartbeat interval must be positive and less than lease TTL.")
        self.store = store
        self.run_id = run_id
        self.owner = owner
        self.ttl_seconds = ttl_seconds
        self.interval_seconds = interval_seconds
        self._stop = threading.Event()
        self._error: BaseException | None = None
        self._thread: threading.Thread | None = None

    def __enter__(self) -> "LeaseHeartbeat":
        self.store.heartbeat(
            self.run_id,
            owner=self.owner,
            ttl_seconds=self.ttl_seconds,
        )
        self._thread = threading.Thread(
            target=self._loop,
            name=f"projectctl-lease-{self.run_id}",
            daemon=True,
        )
        self._thread.start()
        return self

    def _loop(self) -> None:
        while not self._stop.wait(self.interval_seconds):
            try:
                self.store.heartbeat(
                    self.run_id,
                    owner=self.owner,
                    ttl_seconds=self.ttl_seconds,
                )
            except BaseException as exc:
                self._error = exc
                self._stop.set()
                return

    def assert_healthy(self) -> None:
        if self._error is not None:
            raise RunLeaseError(
                f"Lease heartbeat failed for {self.run_id}: {self._error}"
            ) from self._error

    def __exit__(self, exc_type, exc, tb):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=max(1.0, min(5.0, self.interval_seconds + 0.5)))
        # Losing the lease is a stronger safety failure than the wrapped
        # operation: the old owner must stop mutating durable run state.
        self.assert_healthy()
        return False
