"""M6.0 M0s — strict, nonauthorizing service-only GID test observations.

The model is untrusted console data; it never attests kernel policy,
all-writer exclusion, AppArmor, systemd or runnable migration authority.
"""
from __future__ import annotations

from dataclasses import dataclass, fields


@dataclass(frozen=True)
class GidWitnesses:
    source_stayed_v2: bool | None = None
    fixture_root_anchored: bool | None = None
    embargo_denied_legacy_uid: bool | None = None
    embargo_denied_candidate_uid: bool | None = None
    released_legacy_uid_denied_db_json: bool | None = None
    released_candidate_uid_without_gid_denied_db_json: bool | None = None
    candidate_uid_with_gid_wrote_db_json: bool | None = None
    old_code_with_candidate_uid_and_gid_wrote_db_json: bool | None = None
    negatives_preserved_sqlite_and_json: bool | None = None
    final_fixture_cleanup_attempted: bool | None = None


@dataclass(frozen=True)
class GidDecision:
    decision: str
    authorizes_migration: bool = False
    authorizes_policy_install: bool = False


def review(witnesses: GidWitnesses) -> GidDecision:
    if type(witnesses) is not GidWitnesses:
        return GidDecision("NO_GO_INVALID_M0S_WITNESSES")
    # A successful credential-borrowing old-code write is the precise
    # counterexample this lab must preserve, NOT a claim of a secure cutover.
    if witnesses.old_code_with_candidate_uid_and_gid_wrote_db_json is True:
        for field in fields(witnesses):
            if getattr(witnesses, field.name) is not True:
                return GidDecision("NO_GO_UNVERIFIED_" + field.name.upper())
        return GidDecision("NO_GO_OLD_CODE_WITH_SERVICE_GID_CAN_WRITE")
    for field in fields(witnesses):
        if getattr(witnesses, field.name) is not True:
            return GidDecision("NO_GO_UNVERIFIED_" + field.name.upper())
    return GidDecision("NO_GO_UNVERIFIED_SERVICE_GID_BYPASS")
