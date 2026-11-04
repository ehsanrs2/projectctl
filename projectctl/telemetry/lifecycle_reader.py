"""Strict allowlisted telemetry reader; measurements never authorize actions."""
from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime
from pathlib import Path

from projectctl.trace.snapshot import _FILE_FLAGS, _read_fd, TraceSnapshotError
from projectctl.trace.validate import _object_no_duplicates

SOURCES = {
    "sdk_turn_call": "projectctl.telemetry.lifecycle.observed_sdk_call",
    "worker_start_handling": "projectctl.application.execution.start_prepared_run",
    "worker_resume_handling": "projectctl.application.execution.resume_checkpointed_run",
    "worker_post_dispatch": "projectctl.application.execution._finalize_worker_outcome",
    "worker_pre_dispatch_contract": "projectctl.application.execution._load_admitted_execution_contract",
    "independent_verification": "projectctl.application.verification.verify_run",
    "integration_work": "projectctl.application.integration.integrate_run",
}


def inspect_measurements(path: Path | None, run_id: str) -> dict:
    if path is None:
        return {"state": "unknown", "reason": "no_bound_measurement_artifact"}
    try:
        fd = os.open(path, _FILE_FLAGS)
        try:
            raw = _read_fd(fd, limit=2 * 1024 * 1024)
        finally:
            os.close(fd)
        data = json.loads(raw, object_pairs_hook=_object_no_duplicates)
        if (data["schema_kind"] != "projectctl.lifecycle_measurements"
                or type(data["schema_version"]) is not int or data["schema_version"] != 1
                or data["run_id"] != run_id
                or not re.fullmatch("[a-f0-9]{32}", data["invocation_id"])
                or data["stage"] not in {"start", "resume", "verify", "integrate"}):
            raise ValueError
        if data["state"] == "pending":
            return {"state": "unknown", "reason": "pending_telemetry_reconcile_only",
                    "command_outcome": "pending", "stage": data["stage"]}
        if data["state"] not in {"returned", "interrupted_or_error"}:
            raise ValueError
        start = datetime.fromisoformat(data["started_at"])
        end = datetime.fromisoformat(data["completed_at"])
        if start.tzinfo is None or end.tzinfo is None or end < start:
            raise ValueError
        items = []
        if not isinstance(data["measurements"], list) or len(data["measurements"]) > 128:
            raise ValueError
        for item in data["measurements"]:
            boundary = item["boundary"]
            if (item["schema_kind"] != "projectctl.lifecycle_measurement"
                    or item["schema_version"] != 1 or item["source"] != SOURCES[boundary]
                    or item["clock"] != "time.monotonic_ns"
                    or type(item["duration_ns"]) is not int or item["duration_ns"] < 0
                    or item["outcome"] not in {"returned", "error", "interrupted"}
                    or item["aggregation"] != "overlapping_spans_do_not_sum"):
                raise ValueError
            safe = {k: item[k] for k in ("boundary", "source", "clock", "duration_ns", "outcome", "aggregation")}
            if boundary == "sdk_turn_call":
                from projectctl.workers.codex.usage import FIELDS, inconsistent_subsets
                usage = item["usage"]
                if (usage["source"] != "openai_codex.TurnResult.usage"
                        or usage["aggregation"] != "none_sdk_scopes_are_not_additive"
                        or usage["schema_version"] != 1):
                    raise ValueError
                scopes = {}
                for scope in ("last", "total"):
                    counters = {}
                    for field in FIELDS:
                        counter = usage["scopes"][scope][field]
                        value = counter["value"]
                        if counter["state"] == "observed" and type(value) is int and value >= 0:
                            counters[field] = {"state": "observed", "value": value}
                        elif counter["state"] == "unknown" and value is None:
                            counters[field] = {"state": "unknown", "value": None}
                        else:
                            raise ValueError
                    if inconsistent_subsets(counters):
                        raise ValueError
                    scopes[scope] = counters
                # Only the pinned SDK API has been inspected offline.
                safe["usage"] = scopes if item.get("sdk_version") == "0.160.0" else {
                    "state": "unknown", "reason": "sdk_version_not_offline_verified"}
            items.append(safe)
        return {"state": "observed", "reason": "validated_telemetry_not_authenticated_execution_proof",
                "sha256": hashlib.sha256(raw).hexdigest(), "stage": data["stage"],
                "command_outcome": data["state"],
                "measurements": items, "aggregation": "none_overlapping_boundaries"}
    except (OSError, ValueError, TypeError, KeyError, AttributeError, RecursionError, TraceSnapshotError):
        return {"state": "inconsistent", "reason": "measurement_provenance_invalid"}
