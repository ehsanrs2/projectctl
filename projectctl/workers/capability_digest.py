from __future__ import annotations

import re

from projectctl.core.digest import digest
from projectctl.schemas.capabilities import WorkerCapabilities


_RUNTIME_VERSION_WITH_BANNER = re.compile(
    r"^(?P<version>[0-9]+\\.[0-9]+\\.[0-9]+"
    r"(?:[-+][A-Za-z0-9][A-Za-z0-9._-]*)?)"
    r"\\s+\\([^()\\n]+\\)(?:\\s+[^\\n]+)?$"
)


def runtime_version_identity(value: str | None) -> str | None:
    """Compare a leading runtime version, not an appended platform/user-agent banner.

    Only strip an explicitly parenthesized human-readable suffix following a
    semantic version. Unknown formats remain unchanged (fail closed). Preserve
    prerelease/build identifiers and do not modify saved raw probe evidence.
    """
    if value is None:
        return None
    match = _RUNTIME_VERSION_WITH_BANNER.fullmatch(value)
    return match.group("version") if match else value


def effective_capability_digest(capabilities: WorkerCapabilities) -> str:
    """Digest the execution-relevant capability surface.

    Observation timestamps, probe labels, and human-readable notes are excluded
    so a live re-probe can be compared with a version-only probe without false
    drift. Provider/SDK/runtime/adapter versions and all effective support
    states remain part of the digest. Human-readable runtime platform/user-agent\n    banners are excluded while the leading semantic version is preserved.\n    """

    payload = capabilities.model_dump(mode="json")
    payload.pop("probe_kind", None)
    payload.pop("notes", None)
    runtime = payload.get("runtime")
    if isinstance(runtime, dict):
        runtime.pop("observed_at", None)
        runtime["runtime_version"] = runtime_version_identity(runtime.get("runtime_version"))

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
