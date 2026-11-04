"""Opt-in monotonic lifecycle observations; never an execution authority."""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
from time import monotonic_ns
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

_collector: ContextVar[list | None] = ContextVar("lifecycle_measurements", default=None)


@contextmanager
def capture_measurements():
    """Collect only within this context. Caller owns any explicit persistence.

    Nested spans overlap and MUST NOT be summed. No prompts, exception text,
    task descriptions, thread IDs or account details are captured.
    """
    records = []
    token = _collector.set(records)
    try:
        yield records
    finally:
        _collector.reset(token)


def measured(boundary: str, *, sdk_usage: bool = False):
    """Time a synchronous boundary only when a caller opts in to capture."""
    def decorate(function):
        @wraps(function)
        def call(*args, **kwargs):
            records = _collector.get()
            if records is None:
                return function(*args, **kwargs)
            start = monotonic_ns()
            outcome = "interrupted"
            result = None
            try:
                result = function(*args, **kwargs)
                outcome = "returned"
                return result
            except Exception:
                outcome = "error"
                raise
            finally:
                stop = monotonic_ns()
                record = {
                    "schema_kind": "projectctl.lifecycle_measurement",
                    "schema_version": 1,
                    "boundary": boundary,
                    "source": f"{function.__module__}.{function.__qualname__}",
                    "clock": "time.monotonic_ns",
                    "duration_ns": max(0, stop - start),
                    "outcome": outcome,
                    "aggregation": "overlapping_spans_do_not_sum",
                }
                if sdk_usage:
                    # The codex package exports its adapter in __init__. Avoid
                    # importing it while application decorators initialize.
                    from projectctl.workers.codex.usage import observe_usage
                    from importlib.metadata import PackageNotFoundError, version
                    try:
                        record["sdk_version"] = version("openai-codex")
                    except PackageNotFoundError:
                        record["sdk_version"] = "unknown"
                    record["usage"] = observe_usage(result)
                records.append(record)
        return call
    return decorate


@measured("sdk_turn_call", sdk_usage=True)
def observed_sdk_call(operation, *args, **kwargs):
    """SDK call elapsed time, including tools/transport; never pure model time."""
    return operation(*args, **kwargs)


@contextmanager
def measurement_artifact(path: Path | None, *, run_id: str, stage: str):
    """Explicit optional capture for an already-authorized existing command.

    Exclusive creation and fsync precede the command. A killed process leaves
    pending or malformed telemetry, never evidence that retry is safe. This
    artifact cannot authorize dispatch, retry, or recovery.
    """
    if path is None:
        yield
        return
    from projectctl.trace.snapshot import _valid_run_id

    _valid_run_id(run_id)
    if stage not in {"start", "resume", "verify", "integrate"}:
        raise ValueError("Unsupported measurement stage")
    fd = os.open(Path(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL
                 | getattr(os, "O_NOFOLLOW", 0), 0o600)
    payload = {
        "schema_kind": "projectctl.lifecycle_measurements", "schema_version": 1,
        "run_id": run_id, "stage": stage, "invocation_id": uuid.uuid4().hex,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "completed_at": None, "state": "pending", "measurements": [],
        "authority": "telemetry_only_not_dispatch_authority",
    }

    def persist():
        raw = json.dumps(payload, sort_keys=True, allow_nan=False).encode("utf-8")
        os.lseek(fd, 0, os.SEEK_SET)
        os.ftruncate(fd, 0)
        view = memoryview(raw)
        while view:
            written = os.write(fd, view)
            if written <= 0:
                raise OSError("measurement write failed")
            view = view[written:]
        os.fsync(fd)

    try:
        persist()
        with capture_measurements() as records:
            try:
                yield
                payload["state"] = "returned"
            except BaseException:
                payload["state"] = "interrupted_or_error"
                raise
            finally:
                payload["measurements"] = records
                payload["completed_at"] = datetime.now(timezone.utc).isoformat()
                persist()
    finally:
        os.close(fd)
