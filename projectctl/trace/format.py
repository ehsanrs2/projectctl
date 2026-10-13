"""Pure, deterministic and privacy-bounded trace formatting.

This code does NOT collect evidence, validate source lineage, or convert
worker statements into verified outcomes. Those operations require an
approved read-only snapshot design before the M6.0 collector is enabled.
"""
from __future__ import annotations

import json

from projectctl.schemas.trace import (
    ExecutionTraceBundle,
    TraceEventCategory,
)

# Exact allowlist; event payload, type strings and actor names are NEVER
# returned. Unrecognized or newly introduced run event types are classified
# as unclassified rather than guessed by an untrusted prefix.
_EVENT_CATEGORIES: dict[str, TraceEventCategory] = {
    "run.created": "lifecycle",
    "task.claim.transition_validated": "claim",
    "task.claim.unresolved": "claim",
    "publication.requested": "delivery",
    "review.requested": "delivery",
}


def trace_event_category(raw_event_type: str) -> TraceEventCategory:
    """Classify a known durable event; do not reproduce its raw string."""
    return _EVENT_CATEGORIES.get(raw_event_type, "unclassified")


def canonical_trace_json_bytes(bundle: ExecutionTraceBundle) -> bytes:
    """Stable UTF-8 bytes for one *already validated* derived trace.

    Includes a single trailing newline for CLI pipes. No wall-clock stamp,
    raw provider payload or output destination metadata is ever appended.
    This digest/serialization is NOT run authority or an evidence receipt.
    """
    if not isinstance(bundle, ExecutionTraceBundle):
        raise TypeError("Expected a validated ExecutionTraceBundle v1.")
    return (
        json.dumps(
            bundle.model_dump(mode="json"),
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        ) + "\n"
    ).encode("utf-8")
