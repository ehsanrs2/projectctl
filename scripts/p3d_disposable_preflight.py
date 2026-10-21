"""M6.0 P3d: offline, fixed-schema check of a proposed disposable-trial dossier.

No host probing, filesystem mutation, command execution, auth or attestations.
A fully populated dossier is still an untrusted CLAIM requiring separate owner
and security approval; this tool ALWAYS returns an explicit NO_GO decision.
"""
from __future__ import annotations

import json
import os
import sys
from typing import Any

_REFUSAL = "P3D_PREFLIGHT_REFUSED"
_DECISION = "P3D_NO_GO_TRIAL_NOT_AUTHORIZED"
_SCHEMA = "projectctl.m6_0.p3d.disposable_trial_request"
_TOPOLOGY = "P3C_T1_DISPOSABLE_VM_STATIC_DUAL_PRINCIPAL_WITH_TRUSTED_ADMIN"
_MAX_BYTES = 24576

EVIDENCE_KEYS = (
    "exact_disposable_vm_isolation_and_reset",
    "independent_administrator_and_observer",
    "static_principals_groups_and_no_sudo_overlap",
    "durable_disk_mount_and_custody_ancestry",
    "admin_owned_code_import_and_launcher_origin",
    "old_writer_gid_fd_alias_and_service_denial_plan",
    "single_commit_high_water_and_no_clobber_protocol",
    "crash_reboot_ack_loss_and_cleanup_protocol",
    "synthetic_only_privacy_retention_and_abort",
    "independent_security_and_owner_review",
)
SCOPE_FLAGS = (
    "uses_only_disposable_guest",
    "uses_only_synthetic_data",
    "separates_administrator_from_project_writer",
    "treats_host_and_guest_root_as_tcb",
    "excludes_full_vm_rollback_resistance_claim",
)
DENIAL_FLAGS = (
    "touch_real_project_db_or_wal",
    "use_privileged_command_from_this_review",
    "provision_identity_or_service_from_this_review",
    "modify_mount_or_host_from_this_review",
    "create_signing_key_from_this_review",
    "enable_v3_w1_r1_collector_cli",
    "expand_worker_task_authority",
    "authorize_any_disposable_trial",
    "authorize_production_custody",
)
_KEYS = frozenset({
    "schema_kind", "schema_version", "classification", "decision_claim",
    "selected_pattern", "scope_claims", "evidence_claims", "prohibited_actions",
    "cases", "owner_authorization", "reviewer_authorization",
})
_EXPECTED_CASES = tuple(f"P3-F{i:02d}" for i in range(1, 29))


class P3dRefusal(ValueError):
    """Fixed input-independent refusal."""


def _refuse() -> None:
    raise P3dRefusal(_REFUSAL)


def _no_dupes(pairs: list[tuple[str, Any]]) -> dict:
    result = {}
    for k, v in pairs:
        if k in result:
            _refuse()
        result[k] = v
    return result


def _exact_fields(obj: object, fields: frozenset[str]) -> dict:
    if type(obj) is not dict or obj.keys() != fields:
        _refuse()
    return obj


def parse_request(raw: bytes) -> dict:
    """Bounded strict decoding. Never return arbitrary fields to output."""
    if type(raw) is not bytes or not raw or len(raw) > _MAX_BYTES:
        _refuse()
    try:
        value = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=_no_dupes,
            parse_constant=lambda _: _refuse(),
        )
    except (ValueError, UnicodeError, RecursionError):
        _refuse()
    return _exact_fields(value, _KEYS)


def review_request(value: object) -> dict:
    r = _exact_fields(value, _KEYS)
    if (
        r["schema_kind"] != _SCHEMA
        or type(r["schema_version"]) is not int
        or r["schema_version"] != 1
        or r["classification"] != "UNTRUSTED_OWNER_REQUEST_NOT_APPROVAL"
        or r["decision_claim"] != "NO_GO_REQUEST_ONLY"
        or r["selected_pattern"] != _TOPOLOGY
        or r["owner_authorization"] is not False
        or r["reviewer_authorization"] is not False
    ):
        _refuse()

    scope = _exact_fields(r["scope_claims"], frozenset(SCOPE_FLAGS))
    for k in SCOPE_FLAGS:
        if type(scope[k]) is not bool:
            _refuse()
    denials = _exact_fields(r["prohibited_actions"], frozenset(DENIAL_FLAGS))
    if any(denials[k] is not False for k in DENIAL_FLAGS):
        _refuse()
    evidence = _exact_fields(r["evidence_claims"], frozenset(EVIDENCE_KEYS))
    if any(type(evidence[k]) is not str or evidence[k] not in ("MISSING", "CLAIMED_UNVERIFIED")
           for k in EVIDENCE_KEYS):
        _refuse()

    cases = r["cases"]
    if type(cases) is not list or len(cases) != 28:
        _refuse()
    for idx, c in enumerate(cases):
        entry = _exact_fields(c, frozenset({"id", "status"}))
        if entry["id"] != _EXPECTED_CASES[idx] or entry["status"] != "NOT_RUN":
            _refuse()

    missing = [k for k in EVIDENCE_KEYS if evidence[k] == "MISSING"]
    unmet = [k for k in SCOPE_FLAGS if scope[k] is False]
    status = (
        "HUMAN_CLAIMS_PRESENT_UNVERIFIED"
        if not missing and not unmet else "DOSSIER_INCOMPLETE"
    )
    return {
        "schema_kind": "projectctl.m6_0.p3d.offline_preflight_result",
        "schema_version": 1,
        "classification": "NONAUTHORITATIVE_UNTRUSTED_INPUT",
        "decision": _DECISION,
        "dossier_status": status,
        "missing_evidence_keys": missing,
        "unmet_scope_keys": unmet,
        "claimed_unverified_count": len(EVIDENCE_KEYS) - len(missing),
        "actual_trial_cases_executed": 0,
        "external_owner_review_required": True,
        "external_security_review_required": True,
        "authorizations": {k: False for k in DENIAL_FLAGS},
    }


def main() -> int:
    # Avoid using a privileged identity to even run dossier review, but this
    # check says nothing about user namespace/capability or future privileges.
    if (os.getuid() == 0 or os.geteuid() == 0 or os.getuid() != os.geteuid()
            or os.getgid() != os.getegid()):
        print(_REFUSAL, file=sys.stderr)
        return 2
    try:
        raw = sys.stdin.buffer.read(_MAX_BYTES + 1)
        result = review_request(parse_request(raw))
    except (P3dRefusal, OSError):
        print(_REFUSAL, file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True, separators=(",", ":"), ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
