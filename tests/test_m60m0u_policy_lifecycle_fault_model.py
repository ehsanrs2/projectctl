"""M0u no-privilege lifecycle recovery and global side-effect refusal tests."""
from __future__ import annotations

import json
from dataclasses import fields, replace
from pathlib import Path

import pytest

from scripts import m0u_policy_lifecycle_model as m0u
from scripts.m0u_policy_lifecycle_model import (
    Decision, OperatorClaims, model_recovery, review_claims, review_manifest,
)


def _all_hypothetical() -> OperatorClaims:
    return OperatorClaims(**{
        field.name: (
            False if field.name == "untrusted_old_code_with_both_credentials_wrote"
            else True
        )
        for field in fields(OperatorClaims)
    })


def test_every_hypothetical_positive_proof_still_no_operational_authority():
    assert review_claims(_all_hypothetical()) == Decision(
        "NO_GO_EXTERNAL_KERNEL_EVIDENCE_NOT_ATTESTED"
    )


@pytest.mark.parametrize("field", [
    f.name for f in fields(OperatorClaims)
    if f.name != "untrusted_old_code_with_both_credentials_wrote"
])
@pytest.mark.parametrize("bad", [None, False, 0, 1, "yes", {}])
def test_all_review_proof_fields_are_literal_true_or_fail_closed(field, bad):
    result = review_claims(replace(_all_hypothetical(), **{field: bad}))
    assert result.decision == "NO_GO_UNVERIFIED_" + field.upper()
    assert not result.authorizes_root_trial
    assert not result.authorizes_policy_install
    assert not result.authorizes_migration


@pytest.mark.parametrize("bad", [True, None, 0, 1, "yes", {}])
def test_shared_credentials_old_code_bypass_is_never_misclassified(bad):
    result = review_claims(replace(
        _all_hypothetical(),
        untrusted_old_code_with_both_credentials_wrote=bad,
    ))
    if bad is True:
        expected = "NO_GO_UNTRUSTED_SAME_CREDENTIAL_OLD_CODE_BYPASS"
    else:
        expected = (
            "NO_GO_UNVERIFIED_UNTRUSTED_OLD_CODE_WITH_BOTH_CREDENTIALS_WROTE"
        )
    assert result.decision == expected
    assert not result.authorizes_root_trial


@pytest.mark.parametrize("bad", [None, True, False, 0, 1, "yes", [], {}])
def test_invalid_review_claims_are_rejected(bad):
    assert review_claims(bad) == Decision("NO_GO_INVALID_M0U_REVIEW_CLAIMS")


def test_shipped_manifest_is_permanently_nondeployable():
    original = json.loads(m0u._INTENT.read_text(encoding="utf-8"))
    assert review_manifest(original) == Decision("NO_GO_M0U_MANIFEST_UNDEPLOYABLE")
    assert original["kernel_global_policy_change_allowed"] is False
    assert original["system_unit_install_allowed"] is False
    assert original["root_trial_allowed"] is False
    assert original["production_migration_allowed"] is False
    for name in (
        "fixture_root", "unique_unit_name", "unique_profile_name",
        "verified_executable", "root_owned_recovery_journal",
        "independent_recovery_controller",
    ):
        assert original[name].startswith("@M0U_")
        assert original[name].endswith("@")


@pytest.mark.parametrize("tamper,value", [
    ("kernel_global_policy_change_allowed", True),
    ("system_unit_install_allowed", True),
    ("root_trial_allowed", True),
    ("production_migration_allowed", True),
    ("authority", "GO"),
    ("verified_executable", "/usr/bin/python3"),
    ("unique_unit_name", "projectctl.service"),
    ("unique_profile_name", "usr.bin.python3"),
    ("fixture_root", "/home/ehsan/projectctl-m0k-lab"),
    ("root_owned_recovery_journal", "/var/tmp/writable-journal"),
    ("independent_recovery_controller", "finally"),
])
def test_any_manifest_drift_is_refused(tamper, value):
    original = json.loads(m0u._INTENT.read_text(encoding="utf-8"))
    original[tamper] = value
    assert review_manifest(original) == Decision(
        "NO_GO_M0U_MANIFEST_DRIFT_OR_UNRESOLVED_OWNERSHIP"
    )


def test_unknown_manifest_keys_and_wrong_types_refused():
    original = json.loads(m0u._INTENT.read_text(encoding="utf-8"))
    original["test_only_upgrade"] = True
    assert review_manifest(original).decision == (
        "NO_GO_M0U_MANIFEST_DRIFT_OR_UNRESOLVED_OWNERSHIP"
    )
    for bad in ([], None, True, "ok"):
        assert review_manifest(bad) == Decision("NO_GO_INVALID_M0U_MANIFEST")


@pytest.mark.parametrize("fault", m0u._ALLOWED_FAULTS)
@pytest.mark.parametrize("index", range(len(m0u._STEPS)))
def test_each_fault_at_each_phase_fails_closed(fault, index):
    d = model_recovery(m0u._STEPS[:index], fault=fault)
    if index > m0u._FIRST_GLOBAL_MUTATION:
        expected = "QUARANTINE_GUEST_GLOBAL_POLICY_RECONCILIATION"
    else:
        expected = "NO_GO_PRE_KERNEL_MUTATION_INCOMPLETE"
    assert d.decision == expected
    assert not d.authorizes_root_trial
    assert not d.authorizes_policy_install
    assert not d.authorizes_migration


def test_full_simulated_removal_and_kernel_absence_is_not_real_witness():
    assert model_recovery(m0u._STEPS) == Decision(
        "NO_GO_SIMULATED_ABSENCE_NOT_KERNEL_ATTESTATION"
    )


@pytest.mark.parametrize("unexpected", [
    ("guest_scope_attested", "unit_installed"),
    ("profile_loaded",),
    ("unit_installed", "profile_loaded"),
    ("guest_scope_attested", "guest_scope_attested"),
    ("guest_scope_attested", "profile_unloaded"),
])
def test_unordered_or_repeated_lifecycle_actions_never_pass(unexpected):
    assert model_recovery(unexpected).decision.startswith("NO_GO_")


@pytest.mark.parametrize("bad", [None, {}, "scope", 3, True])
def test_invalid_event_payload_never_accepted(bad):
    assert model_recovery(bad) == Decision(
        "NO_GO_INVALID_M0U_EVENT_SEQUENCE"
    )


def test_extra_or_illegal_event_after_global_policy_load_is_quarantined():
    sequence = m0u._STEPS[:m0u._FIRST_GLOBAL_MUTATION + 1]
    for extra in ("unit_installed", "start_bypass", "profile_loaded"):
        # The legal next step is unit_installed; test the other events.
        if extra == "unit_installed":
            sample = sequence + ("unit_installed", "not_an_action")
        else:
            sample = sequence + (extra,)
        d = model_recovery(sample)
        assert d.decision == "QUARANTINE_GUEST_GLOBAL_POLICY_RECONCILIATION"


@pytest.mark.parametrize("bad", [
    "power_failure", "ignored", "sudo_run", "", 1,
])
def test_unknown_fault_categories_are_never_treated_as_success(bad):
    assert model_recovery((), fault=bad) == Decision(
        "NO_GO_UNREVIEWED_FAILURE_MODE"
    )


def test_inspect_is_read_only_and_all_decisions_no_go(monkeypatch, capsys):
    monkeypatch.setattr(m0u, "model_recovery", model_recovery)
    assert m0u.main(["--inspect"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["decision"] == "NO_GO_M0U_MANIFEST_UNDEPLOYABLE"
    assert data["model_after_profile_load_crash"] == (
        "QUARANTINE_GUEST_GLOBAL_POLICY_RECONCILIATION"
    )
    assert data["model_full_sequence"] == (
        "NO_GO_SIMULATED_ABSENCE_NOT_KERNEL_ATTESTATION"
    )
    assert not data["authorizes_root_trial"]
    assert not data["authorizes_policy_install"]
    assert not data["authorizes_migration"]


def test_simulate_all_failure_points_never_grants_root_or_kernel_rights(capsys):
    assert m0u.main(["--simulate-faults"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["decision"] == "NO_GO_SIMULATED_FAILURES_NOT_REAL_RECOVERY"
    assert data["quarantined_count"] > 0
    assert data["interruption_points"] == len(m0u._STEPS)
    for variants in data["outcomes"].values():
        assert all(
            value.startswith("NO_GO_") or value.startswith("QUARANTINE_")
            for value in variants.values()
        )
    assert data["authorizes_root_trial"] is False
    assert data["authorizes_policy_install"] is False
    assert data["authorizes_migration"] is False


@pytest.mark.parametrize("argv", [
    [], ["--run"], ["--install"], ["--load-profile"],
    ["--inspect", "--simulate-faults"], ["--restore"],
])
def test_no_root_or_policy_mutation_command_interface(argv):
    with pytest.raises(SystemExit) as err:
        m0u.main(argv)
    assert err.value.code != 0


def test_model_script_has_no_mutating_kernel_or_service_calls():
    content = Path(m0u.__file__).read_text(encoding="utf-8")
    for operation in (
        "subprocess.run(", "subprocess.Popen(", "os.chown(", "os.chmod(",
        "os.setgroups(", "os.setuid(", "os.setgid(",
        "systemctl start", "systemctl enable", "apparmor_parser -r",
        "apparmor_parser -a", "shutil.rmtree(", "os.kill(",
    ):
        assert operation not in content
