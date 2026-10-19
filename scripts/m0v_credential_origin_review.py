"""M6.0 M0v: unauthenticated assertions about credential and code origin.

No source hash or Boolean can verify runtime imports, all start surfaces or
prove independent old actors cannot borrow candidate UID + private GID.
Every result remains NO_GO, even all anticipated review claims.
"""
from __future__ import annotations

from dataclasses import dataclass, fields


@dataclass(frozen=True)
class OriginClaims:
    trusted_root_and_guest_boundary_independently_reviewed: bool | None = None
    all_group_delegation_routes_and_helpers_inventoried: bool | None = None
    service_unit_and_dropins_root_immutable: bool | None = None
    launch_actor_and_import_closure_pinned_at_exec: bool | None = None
    dynamic_code_and_environment_injection_excluded: bool | None = None
    same_uid_independent_without_group_denied: bool | None = None
    preopened_fds_and_all_aliases_reconciled: bool | None = None
    independent_recovery_owner_survives_service_failure: bool | None = None
    installed_service_process_enforce_label_observed: bool | None = None
    global_cleanup_independently_witnessed: bool | None = None
    untrusted_old_code_with_both_credentials_wrote: bool | None = None


@dataclass(frozen=True)
class OriginDecision:
    decision: str
    authorizes_migration: bool = False
    authorizes_policy_install: bool = False
    authorizes_root_trial: bool = False


def assess(claims: OriginClaims) -> OriginDecision:
    if type(claims) is not OriginClaims:
        return OriginDecision("NO_GO_INVALID_ORIGIN_CLAIMS")
    if claims.untrusted_old_code_with_both_credentials_wrote is True:
        return OriginDecision("NO_GO_UNTRUSTED_OLD_CODE_CAN_BORROW_WRITER_AUTHORITY")
    for field in fields(OriginClaims):
        expected = (
            False if field.name == "untrusted_old_code_with_both_credentials_wrote"
            else True
        )
        if getattr(claims, field.name) is not expected:
            return OriginDecision("NO_GO_UNVERIFIED_" + field.name.upper())
    return OriginDecision(
        "NO_GO_CREDENTIAL_AND_EXECUTION_ORIGIN_NOT_INDEPENDENTLY_ATTESTED"
    )
