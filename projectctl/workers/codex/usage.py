"""Allowlisted observations of openai-codex 0.160.0 TurnResult.usage.

ThreadTokenUsage.last and .total retain their SDK names. Neither is claimed
to be an independently billable ProjectCTL operation total. In particular,
thread totals must never be summed over checkpoint/resume operations.
"""
from __future__ import annotations

from typing import Any


FIELDS = (
    "input_tokens", "output_tokens", "cached_input_tokens",
    "reasoning_output_tokens", "total_tokens",
)


def inconsistent_subsets(counters: dict) -> tuple[str, ...]:
    """Check only available SDK pairs, independently within one usage scope."""
    return tuple(subset for subset, total in (
        ("cached_input_tokens", "input_tokens"),
        ("reasoning_output_tokens", "output_tokens"),
    ) if counters[subset]["state"] == counters[total]["state"] == "observed"
        and counters[subset]["value"] > counters[total]["value"])


def observe_usage(result: Any = None) -> dict:
    """Copy counters only, without traversing messages or serializing SDK objects.

    Cached input and reasoning output are subsets, not additional charges.
    No computed total or cross-operation aggregation is produced here.
    Missing, negative, boolean and malformed counters remain explicit unknowns.
    """
    usage = getattr(result, "usage", None)
    scopes = {}
    for scope in ("last", "total"):
        source = getattr(usage, scope, None)
        counters = {}
        for name in FIELDS:
            value = getattr(source, name, None)
            valid = type(value) is int and value >= 0
            counters[name] = {
                "state": "observed" if valid else "unknown",
                "value": value if valid else None,
                "reason": None if valid else "sdk_counter_unavailable_or_invalid",
            }
        for name in inconsistent_subsets(counters):
            counters[name] = {"state": "unknown", "value": None,
                              "reason": "sdk_subset_exceeds_parent_counter"}
        scopes[scope] = counters
    return {
        "schema_version": 1,
        "source": "openai_codex.TurnResult.usage",
        "aggregation": "none_sdk_scopes_are_not_additive",
        "scopes": scopes,
    }
