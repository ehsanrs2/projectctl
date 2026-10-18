"""M0t ordinary-user review tests. No guest-global changes or root calls."""
from __future__ import annotations

import json
from dataclasses import fields, replace
from pathlib import Path

import pytest

from scripts import m0t_enforcement_envelope_review as m0t
from scripts.m0t_enforcement_envelope_review import (
    Decision, EnforcementClaims, review_apparmor_template,
    review_claims, review_unit_template,
)


def _claims_without_known_bypass() -> EnforcementClaims:
    return EnforcementClaims(**{
        field.name: (
            False if field.name == "untrusted_old_code_with_both_credentials_wrote"
            else True
        )
        for field in fields(EnforcementClaims)
    })


def _unit() -> str:
    return m0t._UNIT.read_text(encoding="utf-8")


def _profile() -> str:
    return m0t._PROFILE.read_text(encoding="utf-8")


def test_all_review_claims_even_if_positive_cannot_be_security_admission():
    assert review_claims(_claims_without_known_bypass()) == Decision(
        "NO_GO_MANDATORY_ENFORCEMENT_NOT_INDEPENDENTLY_ATTESTED"
    )


@pytest.mark.parametrize("bad", [True, 1, "yes", {}, None])
def test_known_or_unverified_both_credential_bypass_is_no_go(bad):
    sample = replace(
        _claims_without_known_bypass(),
        untrusted_old_code_with_both_credentials_wrote=bad,
    )
    result = review_claims(sample)
    if bad is True:
        assert result.decision == "NO_GO_UNTRUSTED_OLD_CODE_WITH_BOTH_CREDENTIALS"
    else:
        assert result.decision == (
            "NO_GO_UNVERIFIED_UNTRUSTED_OLD_CODE_WITH_BOTH_CREDENTIALS_WROTE"
        )
    assert result.authorizes_root_trial is False


@pytest.mark.parametrize(
    "field_name",
    [
        f.name for f in fields(EnforcementClaims)
        if f.name != "untrusted_old_code_with_both_credentials_wrote"
    ],
)
@pytest.mark.parametrize("bad", [False, None, 0, 1, "yes", {}])
def test_all_positive_review_claims_require_literal_true(field_name, bad):
    sample = replace(_claims_without_known_bypass(), **{field_name: bad})
    result = review_claims(sample)
    assert result.decision == "NO_GO_UNVERIFIED_" + field_name.upper()
    assert not result.authorizes_migration
    assert not result.authorizes_policy_install
    assert not result.authorizes_root_trial


@pytest.mark.parametrize("bad", [True, False, None, "yes", 1, {}, []])
def test_invalid_claim_object_is_never_accepted(bad):
    assert review_claims(bad) == Decision("NO_GO_INVALID_M0T_CLAIMS")


def test_untrusted_both_credential_writer_takes_precedence_over_unknowns():
    sample = EnforcementClaims(untrusted_old_code_with_both_credentials_wrote=True)
    assert review_claims(sample).decision == (
        "NO_GO_UNTRUSTED_OLD_CODE_WITH_BOTH_CREDENTIALS"
    )


def test_shipped_systemd_template_intentionally_unresolved():
    assert review_unit_template(_unit()) == (
        "NO_GO_REVIEW_ONLY_UNIT_TEMPLATE_UNRESOLVED"
    )
    assert "@M0T_ROOT_OWNED_PINNED_ACTOR@" in _unit()
    assert "AppArmorProfile=m0t-review-@M0T_NONCE@" in _unit()


@pytest.mark.parametrize("bad_line", [
    "ExecStart=+/usr/bin/python3 -c 'print(1)'",
    "ExecStartPre=+/usr/bin/true",
    "EnvironmentFile=/var/tmp/old-writer-controlled",
    "DynamicUser=yes",
    "User=63071",
    "SupplementaryGroups=63071",
    "SupplementaryGroups=63072",
    "AppArmorProfile=-m0t-review-@M0T_NONCE@",
    "AppArmorProfile=",
    "NoNewPrivileges=no",
    "CapabilityBoundingSet=CAP_DAC_OVERRIDE",
    "AmbientCapabilities=CAP_SETGID",
    "ProtectSystem=off",
    "ReadWritePaths=/",
    "WorkingDirectory=/tmp",
    "PrivateUsers=no",
    "ExecStart=/bin/sh -c 'old writer'",
])
def test_systemd_unsafe_directive_or_override_cannot_be_accepted(bad_line):
    assert review_unit_template(_unit() + bad_line + "\n") != (
        "NO_GO_REVIEW_ONLY_UNIT_TEMPLATE_UNRESOLVED"
    )


@pytest.mark.parametrize("bad", [
    "[Service]\n",
    "[Install]\nWantedBy=multi-user.target\n",
    "[Socket]\nListenStream=0.0.0.0:9999\n",
    "not-a-section=wrong\n",
])
def test_unit_extra_section_or_invalid_records_not_accepted(bad):
    assert review_unit_template(_unit() + bad) != (
        "NO_GO_REVIEW_ONLY_UNIT_TEMPLATE_UNRESOLVED"
    )


@pytest.mark.parametrize("old,new", [
    ("User=63072", "User=63071"),
    ("Group=63072", "Group=63071"),
    ("SupplementaryGroups=63073", "SupplementaryGroups=63071"),
    ("NoNewPrivileges=yes", "NoNewPrivileges=no"),
    ("CapabilityBoundingSet=", "CapabilityBoundingSet=CAP_DAC_OVERRIDE"),
    ("AppArmorProfile=m0t-review-@M0T_NONCE@",
     "AppArmorProfile=-m0t-review-@M0T_NONCE@"),
    ("ExecStart=@M0T_ROOT_OWNED_PINNED_ACTOR@",
     "ExecStart=+/usr/bin/python3"),
    ("ReadWritePaths=@M0T_PRIVATE_FIXTURE_DIR@", "ReadWritePaths=/"),
])
def test_systemd_trusted_envelope_mutation_is_detected(old, new):
    assert old in _unit()
    assert review_unit_template(_unit().replace(old, new, 1)) != (
        "NO_GO_REVIEW_ONLY_UNIT_TEMPLATE_UNRESOLVED"
    )


def test_profile_is_intentionally_nonloadable_and_no_shared_python_attachment():
    assert review_apparmor_template(_profile()) == (
        "NO_GO_REVIEW_ONLY_PROFILE_TEMPLATE_UNRESOLVED"
    )
    assert "@M0T_EXACT_ACTOR_AND_DEPENDENCY_RULES@" in _profile()


@pytest.mark.parametrize("addition", [
    "/usr/bin/python3 {",
    "flags=(complain)",
    "flags=(unconfined)",
    "/usr/bin/python3 ix,",
    "/bin/sh ux,",
    "/bin/sh Ux,",
    "/bin/sh pux,",
    "/bin/sh Pux,",
    "  /var/tmp/** rwkl,",
    "capability dac_override,",
    "  /etc/shadow r,",
])
def test_profile_tampering_or_extra_policy_never_accepts(addition):
    original = _profile()
    changed = original.replace(
        "@M0T_EXACT_ACTOR_AND_DEPENDENCY_RULES@",
        addition, 1,
    )
    assert review_apparmor_template(changed) != (
        "NO_GO_REVIEW_ONLY_PROFILE_TEMPLATE_UNRESOLVED"
    )


def test_no_migration_or_install_permission_even_with_clean_static_templates(
    capsys, monkeypatch,
):
    monkeypatch.setattr(m0t, "_UNIT", Path(m0t._UNIT))
    assert m0t.main(["--inspect"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["stage"] == "M6.0-M0t"
    assert report["unit_template_decision"] == (
        "NO_GO_REVIEW_ONLY_UNIT_TEMPLATE_UNRESOLVED"
    )
    assert report["profile_template_decision"] == (
        "NO_GO_REVIEW_ONLY_PROFILE_TEMPLATE_UNRESOLVED"
    )
    assert report["decision"] == (
        "NO_GO_NO_GUEST_POLICY_OR_START_ENFORCEMENT_PROOF"
    )
    assert report["authorizes_migration"] is False
    assert report["authorizes_policy_install"] is False
    assert report["authorizes_root_trial"] is False


@pytest.mark.parametrize("arg", [
    ["--run"], ["--load-profile"], ["--unit", "old.service"],
    ["--inspect", "--run"],
])
def test_no_guest_mutation_interface_exists(arg):
    with pytest.raises(SystemExit) as ex:
        m0t.main(arg)
    assert ex.value.code != 0


def test_no_installer_or_process_manipulation_exists():
    code = Path(m0t.__file__).read_text(encoding="utf-8")
    for name in (
        "subprocess.run(", "os.chown(", "os.chmod(", "os.setgid(",
        "os.setuid(", "systemctl start", "apparmor_parser -r",
        "subprocess.Popen(", "shutil.rmtree(", "os.kill(",
    ):
        assert name not in code
