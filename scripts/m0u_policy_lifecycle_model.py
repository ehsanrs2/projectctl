"""M6.0 M0u: OFFLINE model of a guest-global policy/Unit lifecycle.

This program NEVER installs, loads, compiles or removes AppArmor policy,
systemd units, users, groups, or filesystem objects. It reads one fixed
checked-in JSON intent and models interruption/rollback obligations.
The model is deliberately NOT a kernel witness or a safe real installer.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, fields
from pathlib import Path


_INTENT = (
    Path(__file__).resolve().parent.parent
    / "docs/architecture/m0u/m0u-lifecycle-intent.json"
)
_EXPECTED = {
    "stage": "M6.0-M0u",
    "artifact_kind": "NONDEPLOYABLE_LIFECYCLE_MODEL",
    "fixture_root": "@M0U_NEW_ROOT_ONLY_GUEST_FIXTURE@",
    "unique_unit_name": "@M0U_UNALLOCATED_UNIT_NAME@",
    "unique_profile_name": "@M0U_UNALLOCATED_APPARMOR_NAME@",
    "verified_executable": "@M0U_UNRESOLVED_ROOT_PINNED_ACTOR@",
    "root_owned_recovery_journal": "@M0U_UNRESOLVED_DURABLE_JOURNAL@",
    "independent_recovery_controller": (
        "@M0U_UNRESOLVED_EXTERNAL_RECOVERY_OWNER@"
    ),
    "policy_compile_mode": "NONROOT_SKIP_KERNEL_LOAD_SKIP_CACHE",
    "kernel_global_policy_change_allowed": False,
    "system_unit_install_allowed": False,
    "root_trial_allowed": False,
    "production_migration_allowed": False,
    "authority": "NO_GO_ALL_STATES",
    "dependency": "M0t T0-T12 REMAIN UNVERIFIED",
}

# A sequence of *hypothetical* steps; nothing here executes them.
# Reconciliation of profile and unit must be independently witnessed
# BEFORE any pilot could treat cleanup as verified.
_STEPS = (
    "guest_scope_attested",
    "namespaces_collision_checked",
    "independent_recovery_agent_and_journal_ready",
    "offline_policy_compiled_without_cache",
    "profile_loaded",
    "unit_installed",
    "service_started",
    "service_stopped",
    "unit_removed",
    "profile_unloaded",
    "independent_global_absence_witness",
)
_FIRST_GLOBAL_MUTATION = _STEPS.index("profile_loaded")
_ALLOWED_FAULTS = (
    "controller_crash", "sigkill", "power_loss", "reboot",
    "disk_full", "service_start_failure",
)


@dataclass(frozen=True)
class OperatorClaims:
    """Untrusted review assertions, NOT evidence or permissions."""
    isolated_guest_and_mounts_verified: bool | None = None
    no_colliding_unit_or_profile: bool | None = None
    root_immutable_actor_and_imports_proven: bool | None = None
    external_crash_recovery_controller_exists: bool | None = None
    durable_root_only_recovery_journal_verified: bool | None = None
    profile_syntax_no_load_no_cache_verified: bool | None = None
    real_enforcing_process_label_observed: bool | None = None
    all_credential_and_fd_routes_closed: bool | None = None
    system_unit_and_policy_independently_removed: bool | None = None
    untrusted_old_code_with_both_credentials_wrote: bool | None = None


@dataclass(frozen=True)
class Decision:
    decision: str
    authorizes_root_trial: bool = False
    authorizes_policy_install: bool = False
    authorizes_migration: bool = False


def review_claims(claims: OperatorClaims) -> Decision:
    if type(claims) is not OperatorClaims:
        return Decision("NO_GO_INVALID_M0U_REVIEW_CLAIMS")
    if claims.untrusted_old_code_with_both_credentials_wrote is True:
        return Decision("NO_GO_UNTRUSTED_SAME_CREDENTIAL_OLD_CODE_BYPASS")
    for item in fields(OperatorClaims):
        expected = (
            False if item.name == "untrusted_old_code_with_both_credentials_wrote"
            else True
        )
        if getattr(claims, item.name) is not expected:
            return Decision("NO_GO_UNVERIFIED_" + item.name.upper())
    return Decision("NO_GO_EXTERNAL_KERNEL_EVIDENCE_NOT_ATTESTED")


def review_manifest(obj: object) -> Decision:
    if type(obj) is not dict:
        return Decision("NO_GO_INVALID_M0U_MANIFEST")
    if obj != _EXPECTED:
        return Decision("NO_GO_M0U_MANIFEST_DRIFT_OR_UNRESOLVED_OWNERSHIP")
    return Decision("NO_GO_M0U_MANIFEST_UNDEPLOYABLE")


def model_recovery(steps: object, *, fault: str | None = None) -> Decision:
    """Never consider *simulated* cleanup a real independent kernel witness."""
    if type(steps) not in (tuple, list):
        return Decision("NO_GO_INVALID_M0U_EVENT_SEQUENCE")
    if fault is not None and fault not in _ALLOWED_FAULTS:
        return Decision("NO_GO_UNREVIEWED_FAILURE_MODE")
    if any(type(item) is not str for item in steps):
        return Decision("NO_GO_INVALID_M0U_EVENT_SEQUENCE")
    sequence = tuple(steps)
    completed_prefix = 0
    for index, event in enumerate(sequence):
        if index >= len(_STEPS) or event != _STEPS[index]:
            if completed_prefix >= _FIRST_GLOBAL_MUTATION + 1:
                return Decision("QUARANTINE_GUEST_GLOBAL_POLICY_RECONCILIATION")
            return Decision("NO_GO_UNEXPECTED_LIFECYCLE_TRANSITION")
        completed_prefix += 1

    # All non-full prefixes are *hypothetical interruptions*. Profile
    # unloading alone cannot certify that a loaded kernel object is gone.
    if completed_prefix < len(_STEPS):
        if completed_prefix > _FIRST_GLOBAL_MUTATION:
            return Decision("QUARANTINE_GUEST_GLOBAL_POLICY_RECONCILIATION")
        return Decision("NO_GO_PRE_KERNEL_MUTATION_INCOMPLETE")

    # Even a fully played-out sequence of event *names* is not an actual
    # kernel process label, systemd unit or independent cleanup witness.
    return Decision("NO_GO_SIMULATED_ABSENCE_NOT_KERNEL_ATTESTATION")


def inspect() -> dict[str, object]:
    try:
        manifest = json.loads(_INTENT.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        manifest = None
    d = review_manifest(manifest)
    return {
        "stage": "M6.0-M0u",
        "scope": "checked_in_intent_and_in_memory_fault_model_only",
        "decision": d.decision,
        "model_full_sequence": model_recovery(_STEPS).decision,
        "model_after_profile_load_crash": model_recovery(
            _STEPS[:_FIRST_GLOBAL_MUTATION + 1], fault="controller_crash"
        ).decision,
        "authorizes_root_trial": False,
        "authorizes_policy_install": False,
        "authorizes_migration": False,
    }


def simulate_faults() -> dict[str, object]:
    outcomes = {
        fault: {
            str(index): model_recovery(_STEPS[:index], fault=fault).decision
            for index in range(len(_STEPS))
        }
        for fault in _ALLOWED_FAULTS
    }
    return {
        "stage": "M6.0-M0u",
        "decision": "NO_GO_SIMULATED_FAILURES_NOT_REAL_RECOVERY",
        "faults": list(_ALLOWED_FAULTS),
        "interruption_points": len(_STEPS),
        "quarantined_count": sum(
            d == "QUARANTINE_GUEST_GLOBAL_POLICY_RECONCILIATION"
            for cases in outcomes.values() for d in cases.values()
        ),
        "outcomes": outcomes,
        "authorizes_root_trial": False,
        "authorizes_policy_install": False,
        "authorizes_migration": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--inspect", action="store_true")
    action.add_argument("--simulate-faults", action="store_true")
    options = parser.parse_args(argv)
    payload = inspect() if options.inspect else simulate_faults()
    print(json.dumps(payload, sort_keys=True))
    return 0  # Ordinary-user offline model succeeds. No guest authority.


if __name__ == "__main__":
    raise SystemExit(main())
