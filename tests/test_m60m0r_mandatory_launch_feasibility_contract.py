"""M0r nonprivileged policy-feasibility gates, not an enforcement test.

No test calls sudo, systemctl, apparmor_parser, aa-exec, setuid, chmod,
chown, or loads kernel policy. All mutations are private tmp_path files.
"""
from __future__ import annotations

import json
from dataclasses import fields, replace
from pathlib import Path

import pytest

from scripts import m0r_guest_launch_authority_preflight as m0r
from scripts.m0r_guest_launch_authority_preflight import (
    BoundaryClaims, Decision, GuestHints, assess_claims, assess_hints,
)


def _all_claimed() -> BoundaryClaims:
    return BoundaryClaims(**{
        f.name: True for f in fields(BoundaryClaims)
    })


def _candidate_hints() -> GuestHints:
    return GuestHints(
        linux=True,
        nonroot=True,
        virtual_machine="kvm",
        var_tmp_fstype="ext4",
        apparmor_enabled="Y",
        own_apparmor_label="unconfined",
        pid1_name="systemd",
        parser_available=True,
    )


def test_even_all_claimed_positive_evidence_does_not_authorize():
    r = assess_claims(_all_claimed())
    assert r == Decision("NO_GO_INDEPENDENT_ENFORCEMENT_NOT_ATTESTED")
    assert r.authorizes_migration is False
    assert r.authorizes_policy_install is False


@pytest.mark.parametrize("gate", [f.name for f in fields(BoundaryClaims)])
@pytest.mark.parametrize("bad", [None, False, "yes", 1, 0, []])
def test_every_claim_requires_literal_true(gate, bad):
    r = assess_claims(replace(_all_claimed(), **{gate: bad}))
    if gate == "direct_same_uid_old_program_denied" and bad is False:
        expected = "NO_GO_DIRECT_SAME_UID_OLD_PROGRAM_BYPASS"
    elif gate == "direct_same_uid_python_import_denied" and bad is False:
        expected = "NO_GO_DIRECT_SAME_UID_PYTHON_IMPORT_BYPASS"
    else:
        expected = "NO_GO_UNVERIFIED_" + gate.upper()
    assert r.status == expected
    assert r.authorizes_migration is False
    assert r.authorizes_policy_install is False


@pytest.mark.parametrize("bad", [{}, [], True, "true", 1, None, object()])
def test_invalid_claim_type_is_rejected(bad):
    assert assess_claims(bad) == Decision("NO_GO_INVALID_BOUNDARY_CLAIMS")


def test_direct_same_uid_old_executable_bypass_takes_precedence_over_other_unknowns():
    sample = BoundaryClaims(
        direct_same_uid_old_program_denied=False,
        apparmor_profile_enforced_for_approved_unit=None,
    )
    assert assess_claims(sample).status == "NO_GO_DIRECT_SAME_UID_OLD_PROGRAM_BYPASS"


def test_direct_same_uid_python_import_bypass_is_explicit_stop_gate():
    sample = replace(
        _all_claimed(),
        direct_same_uid_python_import_denied=False,
    )
    assert assess_claims(sample).status == (
        "NO_GO_DIRECT_SAME_UID_PYTHON_IMPORT_BYPASS"
    )


def test_even_ideal_lsm_pid1_and_parser_hints_are_not_security_proof():
    r = assess_hints(_candidate_hints())
    assert r == Decision("NO_GO_DIRECT_SAME_UID_LAUNCH_ENFORCEMENT_UNPROVEN")


@pytest.mark.parametrize("changes,status", [
    ({"linux": False}, "NO_GO_NONROOT_LINUX_INSPECT_REQUIRED"),
    ({"nonroot": False}, "NO_GO_NONROOT_LINUX_INSPECT_REQUIRED"),
    ({"virtual_machine": "none"}, "NO_GO_GUEST_VIRTUALIZATION_UNVERIFIED"),
    ({"virtual_machine": "unknown"}, "NO_GO_GUEST_VIRTUALIZATION_UNVERIFIED"),
    ({"var_tmp_fstype": "overlay"}, "NO_GO_GUEST_LOCAL_EXT4_UNVERIFIED"),
    ({"apparmor_enabled": "N"}, "NO_GO_APPARMOR_NOT_VERIFIED_ENABLED"),
    ({"apparmor_enabled": "unknown"}, "NO_GO_APPARMOR_NOT_VERIFIED_ENABLED"),
    ({"pid1_name": "other"}, "NO_GO_SYSTEMD_PID1_UNVERIFIED"),
    ({"parser_available": False}, "NO_GO_POLICY_PARSER_NOT_PRESENT"),
])
def test_missing_capabilities_never_become_positive(changes, status):
    result = assess_hints(replace(_candidate_hints(), **changes))
    assert result.status == status
    assert not result.authorizes_migration
    assert not result.authorizes_policy_install


def test_unconfined_current_caller_label_does_not_change_result():
    for label in ("unconfined", "other (enforce)", "unknown"):
        hints = replace(_candidate_hints(), own_apparmor_label=label)
        assert assess_hints(hints).status == (
            "NO_GO_DIRECT_SAME_UID_LAUNCH_ENFORCEMENT_UNPROVEN"
        )


def test_inspect_outputs_strict_no_authority_and_never_provisions(
    monkeypatch, capsys,
):
    monkeypatch.setattr(m0r, "inspect", _candidate_hints)
    assert m0r.main(["--inspect"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["stage"] == "M6.0-M0r"
    assert result["decision"] == (
        "NO_GO_DIRECT_SAME_UID_LAUNCH_ENFORCEMENT_UNPROVEN"
    )
    assert result["authorizes_migration"] is False
    assert result["authorizes_policy_install"] is False
    assert result["observations"]["own_apparmor_label"] == "unconfined"


@pytest.mark.parametrize("raw", [
    "", " ", "\n", "\x00", "yes\nno\n", "x" * 257, "\x7f",
])
def test_fixed_kernel_hint_refuses_malformed_text(tmp_path, raw):
    p = tmp_path / "private-hint-fixture"
    p.write_text(raw, encoding="utf-8")
    assert m0r._fixed_read(p) == "unknown"


def test_missing_kernel_hint_is_unknown(tmp_path):
    assert m0r._fixed_read(tmp_path / "nonexistent") == "unknown"


def test_fixed_command_unknown_for_tool_errors(monkeypatch):
    class Result:
        returncode = 1
        stdout = ""
    monkeypatch.setattr(m0r.subprocess, "run", lambda *a, **k: Result())
    assert m0r._fixed_command(["findmnt", "-T", "/var/tmp"]) == "unknown"


def test_wrong_hint_payload_is_refused():
    assert assess_hints({}).status == "NO_GO_INVALID_GUEST_HINTS"
    assert assess_hints(None).authorizes_policy_install is False


def test_no_privileged_subprocess_execution_in_preflight_source():
    # Cheap review tripwire, not a security sandbox or attestation.
    src = Path(m0r.__file__).read_text(encoding="utf-8")
    for forbidden in (
        "sudo ", "systemctl ", "aa-exec ", "apparmor_parser ",
        "os.setuid(", "os.setgid(", "os.chown(", "os.chmod(",
        "os.kill(", "os.killpg(", "shutil.rmtree(",
    ):
        assert forbidden not in src
