"""M6.0 M0t — nonprivileged, read-only *proposed* launch-envelope review.

The two fixed templates are intentionally nondeployable and no caller can
supply a different path. The result is ALWAYS NO_GO, regardless of inputs.

DO NOT make this tool execute systemctl, apparmor_parser, sudo, or claim
that it has checked the live kernel, service, FD/UID/GID or executable bytes.
"""
from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass, fields
from pathlib import Path


_ROOT = Path(__file__).resolve().parent.parent
_UNIT = _ROOT / "docs/architecture/m0t/m0t-review-only.service.template"
_PROFILE = _ROOT / "docs/architecture/m0t/m0t-review-only.apparmor.template"

# Key-value constraints apply ONLY to the inert, checked-in template.
# They are not evidence of an installed or effective systemd unit.
_REQUIRED_UNIT = {
    "Type": "oneshot",
    "User": "63072",
    "Group": "63072",
    "SupplementaryGroups": "63073",
    "WorkingDirectory": "/",
    "ExecStart": (
        "@M0T_ROOT_OWNED_PINNED_ACTOR@ "
        "--fixture @M0T_PRIVATE_FIXTURE_DIR@"
    ),
    "AppArmorProfile": "m0t-review-@M0T_NONCE@",
    "NoNewPrivileges": "yes",
    "CapabilityBoundingSet": "",
    "AmbientCapabilities": "",
    "UMask": "0077",
    "ProtectSystem": "strict",
    "ReadWritePaths": "@M0T_PRIVATE_FIXTURE_DIR@",
    "ProtectHome": "yes",
    "RestrictSUIDSGID": "yes",
    "RestrictNamespaces": "yes",
}
_ALLOWED_UNIT_SECTIONS = {"Unit", "Service"}
_ALLOWED_UNIT_KEYS = {
    "Unit": {"Description", "ConditionPathIsDirectory"},
    "Service": set(_REQUIRED_UNIT),
}
_PROFILE_MARKERS = (
    "profile m0t-review-@M0T_NONCE@ {",
    "@M0T_EXACT_INTERPRETER_AND_LIBRARY_READ_RULES@",
    "@M0T_EXACT_ACTOR_AND_DEPENDENCY_RULES@",
    "@M0T_PRIVATE_FIXTURE_DB_WAL_SHM_JSON_STAGE_RULES@",
    "@M0T_ALLOWED_EXECUTION_TRANSITIONS_NO_UX_FALLBACK@",
)
_FORBIDDEN_PROFILE_FRAGMENTS = (
    "/usr/bin/python3 {",
    "/usr/bin/python3.* {",
    "flags=(complain)",
    "flags=(unconfined)",
    "ux,", "Ux,", "pux,", "Pux,", "cux,", "CUx,",
)


@dataclass(frozen=True)
class EnforcementClaims:
    """Untrusted human notes for future *separately authorized* kernel pilot."""
    disposable_guest_scope_attested: bool | None = None
    private_writer_gid_root_only: bool | None = None
    immutable_artifact_and_import_closure: bool | None = None
    installed_unit_identity_observed: bool | None = None
    actual_service_profile_enforce_observed: bool | None = None
    unit_restart_and_direct_launcher_scope_closed: bool | None = None
    direct_old_uid_without_gid_denied: bool | None = None
    outsider_same_uid_without_gid_denied: bool | None = None
    all_writers_and_preopened_fds_reconciled: bool | None = None
    guest_global_policy_cleanup_independently_verified: bool | None = None
    untrusted_old_code_with_both_credentials_wrote: bool | None = None


@dataclass(frozen=True)
class Decision:
    decision: str
    authorizes_migration: bool = False
    authorizes_policy_install: bool = False
    authorizes_root_trial: bool = False


def review_claims(claims: EnforcementClaims) -> Decision:
    if type(claims) is not EnforcementClaims:
        return Decision("NO_GO_INVALID_M0T_CLAIMS")
    if claims.untrusted_old_code_with_both_credentials_wrote is True:
        return Decision("NO_GO_UNTRUSTED_OLD_CODE_WITH_BOTH_CREDENTIALS")
    for item in fields(EnforcementClaims):
        value = getattr(claims, item.name)
        expected = (
            False if item.name == "untrusted_old_code_with_both_credentials_wrote"
            else True
        )
        if value is not expected:
            return Decision("NO_GO_UNVERIFIED_" + item.name.upper())
    return Decision("NO_GO_MANDATORY_ENFORCEMENT_NOT_INDEPENDENTLY_ATTESTED")


def review_unit_template(text: str) -> str:
    """Conservative allowlist parser; DO NOT use on a deployed unit."""
    if type(text) is not str or not text.endswith("\n"):
        return "NO_GO_INVALID_UNIT_TEMPLATE"
    found: dict[str, dict[str, str]] = {}
    section: str | None = None
    for source_line in text.splitlines():
        line = source_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1]
            if section not in _ALLOWED_UNIT_SECTIONS or section in found:
                return "NO_GO_UNREVIEWED_UNIT_SECTION"
            found[section] = {}
            continue
        if section is None or "=" not in line:
            return "NO_GO_INVALID_UNIT_DIRECTIVE"
        key, value = line.split("=", 1)
        if key not in _ALLOWED_UNIT_KEYS[section] or key in found[section]:
            return "NO_GO_UNREVIEWED_OR_DUPLICATE_UNIT_DIRECTIVE"
        found[section][key] = value
    if set(found) != _ALLOWED_UNIT_SECTIONS:
        return "NO_GO_MISSING_UNIT_SECTION"
    if set(found["Service"]) != set(_REQUIRED_UNIT):
        return "NO_GO_UNIT_SERVICE_KEYS_UNVERIFIED"
    if any(found["Service"][key] != value for key, value in _REQUIRED_UNIT.items()):
        return "NO_GO_UNIT_SERVICE_ENVELOPE_DRIFT"
    if found["Unit"].get("ConditionPathIsDirectory") != (
        "@M0T_PRIVATE_FIXTURE_DIR@"
    ):
        return "NO_GO_UNIT_FIXTURE_SCOPE_DRIFT"
    if found["Unit"].get("Description", "") != (
        "ProjectCTL M0t DISPOSABLE review-only service envelope"
    ):
        return "NO_GO_UNIT_DESCRIPTION_DRIFT"
    return "NO_GO_REVIEW_ONLY_UNIT_TEMPLATE_UNRESOLVED"


def review_apparmor_template(text: str) -> str:
    """Detect inert placeholder and unsafe evolution, not AppArmor syntax."""
    if type(text) is not str:
        return "NO_GO_INVALID_PROFILE_TEMPLATE"
    active_lines = [
        line.strip() for line in text.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    expected = list(_PROFILE_MARKERS) + ["}"]
    if active_lines != expected:
        return "NO_GO_UNREVIEWED_PROFILE_POLICY_CONTENT"
    if any(fragment in text for fragment in _FORBIDDEN_PROFILE_FRAGMENTS):
        return "NO_GO_UNSAFE_APPARMOR_EXEC_OR_MODE"
    return "NO_GO_REVIEW_ONLY_PROFILE_TEMPLATE_UNRESOLVED"


def inspect() -> dict[str, object]:
    try:
        unit = _UNIT.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        unit = ""
    try:
        profile = _PROFILE.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        profile = ""
    return {
        "stage": "M6.0-M0t",
        "scope": "checked_in_unrenderable_templates_only_no_kernel_inspection",
        "unit_template_decision": review_unit_template(unit),
        "profile_template_decision": review_apparmor_template(profile),
        "decision": "NO_GO_NO_GUEST_POLICY_OR_START_ENFORCEMENT_PROOF",
        "authorizes_migration": False,
        "authorizes_policy_install": False,
        "authorizes_root_trial": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inspect", required=True, action="store_true")
    parser.parse_args(argv)
    print(json.dumps(inspect(), sort_keys=True))
    return 0  # Successful static review, NEVER admission.


if __name__ == "__main__":
    raise SystemExit(main())
