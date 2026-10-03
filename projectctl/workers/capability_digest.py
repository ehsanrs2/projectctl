from __future__ import annotations

from projectctl.core.digest import digest
from projectctl.schemas.capabilities import WorkerCapabilities


def effective_capability_digest(capabilities: WorkerCapabilities) -> str:
    """Digest the execution-relevant capability surface.

    Observation timestamps, probe labels, and human-readable notes are excluded
    so a live re-probe can be compared with a version-only probe without false
    drift. Provider/SDK/runtime/adapter versions and all effective support
    states remain part of the digest.
    """

    payload = capabilities.model_dump(mode="json")
    payload.pop("probe_kind", None)
    payload.pop("notes", None)
    runtime = payload.get("runtime")
    if isinstance(runtime, dict):
        runtime.pop("observed_at", None)

    def strip_notes(value):
        if isinstance(value, dict):
            value.pop("note", None)
            for child in value.values():
                strip_notes(child)
        elif isinstance(value, list):
            for child in value:
                strip_notes(child)

    strip_notes(payload)
    return digest(payload)
