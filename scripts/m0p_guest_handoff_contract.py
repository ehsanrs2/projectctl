"""M6.0 M0p — non-authorizing dual-UID cutover pilot evidence contract.

No caller or self-reported kernel observation can certify absence of writers,
verified binary identity, global stop/start fencing, or migration permission.
"""
from __future__ import annotations

from dataclasses import dataclass, fields


@dataclass(frozen=True)
class LabObservations:
    legacy_baseline_sqlite_wrote: bool | None = None
    legacy_baseline_json_wrote: bool | None = None
    gate_denied_fresh_legacy_open: bool | None = None
    gate_denied_fresh_candidate_open: bool | None = None
    preopened_legacy_fd_survived_dac_gate: bool | None = None
    owned_preopened_fd_holder_exited: bool | None = None
    legacy_denied_after_handoff: bool | None = None
    candidate_wrote_after_handoff: bool | None = None
    legacy_program_with_candidate_credential_wrote: bool | None = None
    sqlite_version_stayed_v2: bool | None = None


@dataclass(frozen=True)
class LabDecision:
    decision: str
    authorizes_migration: bool = False


def review(observations: LabObservations) -> LabDecision:
    """The maximum valid result is a lab-only *negative* security finding."""
    if type(observations) is not LabObservations:
        return LabDecision("NO_GO_INVALID_LAB_OBSERVATIONS")
    for item in fields(observations):
        if getattr(observations, item.name) is not True:
            return LabDecision("NO_GO_UNVERIFIED_" + item.name.upper())
    # Identity separation can deny the *old UID* after release.
    # It CANNOT authenticate which binary uses the newly writable UID.
    return LabDecision("NO_GO_UNTRUSTED_CANDIDATE_EXECUTION_IDENTITY")
