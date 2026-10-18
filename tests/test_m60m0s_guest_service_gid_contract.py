"""M0s: unprivileged contract + root guard tests only.

NEVER run the privileged optional M0s --run in CI. All real UID/GID
changes belong to an explicitly operator-approved disposable Debian KVM
guest after separate review of the exact PR head.
"""
from __future__ import annotations

import errno
import json
import os
from dataclasses import fields, replace
from pathlib import Path

import pytest

from scripts import m0s_guest_service_gid_pilot as pilot
from scripts.m0s_service_gid_contract import GidDecision, GidWitnesses, review


def _all_true() -> GidWitnesses:
    return GidWitnesses(**{f.name: True for f in fields(GidWitnesses)})


def test_positive_bounded_witnesses_still_return_security_no_go():
    d = review(_all_true())
    assert d == GidDecision("NO_GO_OLD_CODE_WITH_SERVICE_GID_CAN_WRITE")
    assert d.authorizes_migration is False
    assert d.authorizes_policy_install is False


@pytest.mark.parametrize("field", [f.name for f in fields(GidWitnesses)])
@pytest.mark.parametrize("invalid", [False, None, 0, 1, "true", []])
def test_each_unverified_observation_fails_closed(field, invalid):
    sample = replace(_all_true(), **{field: invalid})
    d = review(sample)
    assert d.decision == "NO_GO_UNVERIFIED_" + field.upper()
    assert d.authorizes_migration is False
    assert d.authorizes_policy_install is False


@pytest.mark.parametrize("invalid", [None, True, [], {}, 1, "all_true"])
def test_untrusted_observation_payload_type_rejected(invalid):
    assert review(invalid) == GidDecision("NO_GO_INVALID_M0S_WITNESSES")


def test_genuine_privilege_bypass_hard_no_go_even_if_other_observations_true():
    result = review(_all_true())
    assert result.decision.startswith("NO_GO_")
    assert "OLD_CODE" in result.decision
    assert not result.authorizes_migration


def test_read_only_inspect_does_not_create_fixture_or_drop_credentials(
    monkeypatch, capsys,
):
    monkeypatch.setattr(pilot, "_vm", lambda: "kvm")
    monkeypatch.setattr(pilot, "_fstype", lambda: "ext4")
    monkeypatch.setattr(
        pilot, "_trial", lambda: pytest.fail("inspect must not mutate"),
    )
    monkeypatch.setattr(
        pilot, "_preflight",
        lambda ack: pytest.fail("inspect should not require root"),
    )
    assert pilot.main(["--inspect"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["decision"] == "OWNER_GUEST_REVIEW_REQUIRED"
    assert result["authorizes_policy_install"] is False
    assert result["authorizes_migration"] is False


def test_guest_refusal_before_root_trial_on_non_kvm(monkeypatch, capsys):
    monkeypatch.setattr(pilot, "_vm", lambda: "unknown")
    monkeypatch.setattr(pilot, "_fstype", lambda: "ext4")
    monkeypatch.setattr(
        pilot, "_trial", lambda: pytest.fail("must not create fixture"),
    )
    assert pilot.main(["--run", "--acknowledge", pilot._ACK]) == 1
    report = json.loads(capsys.readouterr().out)
    assert report["decision"] == "NO_GO_DISPOSABLE_LAB_REFUSED"
    assert report["reason"] == "NOT_DISPOSABLE_KVM_QEMU_LINUX_GUEST"


def test_root_ack_and_ext4_required_before_credential_changes(monkeypatch):
    monkeypatch.setattr(pilot, "_vm", lambda: "kvm")
    monkeypatch.setattr(pilot, "_fstype", lambda: "ext4")
    with pytest.raises(pilot.Refused, match="ACK_MISSING"):
        pilot._preflight(None)
    monkeypatch.setattr(pilot, "_fstype", lambda: "tmpfs")
    with pytest.raises(pilot.Refused, match="NOT_EXT4"):
        pilot._preflight(pilot._ACK)
    monkeypatch.setattr(pilot, "_fstype", lambda: "ext4")
    monkeypatch.setattr(pilot.os, "getuid", lambda: 1000)
    monkeypatch.setattr(pilot.os, "geteuid", lambda: 1000)
    with pytest.raises(pilot.Refused, match="ROOT_IN_GUEST_REQUIRED"):
        pilot._preflight(pilot._ACK)


def test_privileged_run_refuses_missing_nonroot_sudo_initiator(monkeypatch):
    monkeypatch.setattr(pilot, "_vm", lambda: "kvm")
    monkeypatch.setattr(pilot, "_fstype", lambda: "ext4")
    monkeypatch.setattr(pilot.os, "getuid", lambda: 0)
    monkeypatch.setattr(pilot.os, "geteuid", lambda: 0)
    for key in ("SUDO_UID", "SUDO_GID", "SUDO_USER"):
        monkeypatch.delenv(key, raising=False)
    with pytest.raises(pilot.Refused, match="NONROOT_SUDO_INVOKER"):
        pilot._preflight(pilot._ACK)


def test_fixed_uids_and_private_group_are_distinct():
    assert len({
        pilot._LEGACY_UID, pilot._CANDIDATE_UID, pilot._SERVICE_WRITE_GID,
    }) == 3
    assert pilot._SERVICE_WRITE_GID == 63073
    assert pilot._unused_nss_identifier is not None


def test_denials_require_real_eacces_or_eperm_db_json_attempts():
    assert pilot._denied({
        "probe": {"status": "denied", "errno": errno.EACCES},
        "db": {"status": "denied"},
        "json": {"status": "denied"},
    })
    assert pilot._denied({
        "probe": {"status": "denied", "errno": errno.EPERM},
        "db": {"status": "denied"},
        "json": {"status": "denied"},
    })
    assert not pilot._denied({
        "probe": {"status": "denied", "errno": errno.ENOENT},
        "db": {"status": "denied"},
        "json": {"status": "denied"},
    })
    assert not pilot._denied({
        "probe": {"status": "denied", "errno": errno.EACCES},
        "db": {"status": "denied"},
        "json": {"status": "wrote"},
    })


def test_positive_writes_require_all_three_operations():
    assert pilot._wrote({
        "probe": {"status": "wrote"},
        "db": {"status": "wrote"},
        "json": {"status": "wrote"},
    })
    assert not pilot._wrote({
        "probe": {"status": "wrote"},
        "db": {"status": "denied"},
        "json": {"status": "wrote"},
    })


def test_no_caller_selected_project_uid_or_program(tmp_path, monkeypatch):
    monkeypatch.setattr(pilot, "_guest_python", lambda: "/usr/bin/python3")
    for uid in (0, 1000, 99999):
        with pytest.raises(pilot.Refused, match="UNKNOWN_TEST_ACTOR_UID"):
            pilot._actor(tmp_path, uid, False, "db", "test")
    with pytest.raises(pilot.Refused, match="UNKNOWN_TEST_ACTOR_OPERATION"):
        pilot._actor(tmp_path, pilot._CANDIDATE_UID, False, "shell", "x")


def test_root_owned_fixture_must_be_new_under_var_tmp(tmp_path):
    # No mutator or permission changes; rejects an arbitrary source path.
    with pytest.raises(pilot.Refused, match="NOT_NEW_PRIVATE_M0S_FIXTURE"):
        pilot._fixture(tmp_path)


def test_guest_python_rejects_private_binary_even_through_venv_link(
    tmp_path, monkeypatch,
):
    # Unlike a real Debian venv symlink, this points to an actual *private*
    # executable. Resolution therefore stays outside the trusted /usr/bin.
    fake = tmp_path / "private" / "python3.13"
    fake.parent.mkdir()
    fake.write_bytes(b"test-owned fake interpreter; never execute")
    venv_bin = tmp_path / ".venv" / "bin"
    venv_bin.mkdir(parents=True)
    link = venv_bin / "python"
    link.symlink_to(fake)
    monkeypatch.setattr(pilot.sys, "executable", str(link))
    with pytest.raises(pilot.Refused, match="SYSTEM_PYTHON_IN_USR_BIN_REQUIRED"):
        pilot._guest_python()


def test_guest_python_allows_venv_link_resolving_to_real_system_python(
    tmp_path, monkeypatch,
):
    # Debian /home/.../.venv/bin/python commonly resolves to
    # /usr/bin/python3.13. The child runs the resolved system binary
    # with -I rather than importing from the caller's private venv.
    system_python = Path("/usr/bin/python3")
    if not system_python.is_file() or (
        system_python.resolve().parent != Path("/usr/bin")
    ):
        pytest.skip("no /usr/bin/python3 system interpreter on this runner")
    venv_bin = tmp_path / ".venv" / "bin"
    venv_bin.mkdir(parents=True)
    link = venv_bin / "python"
    link.symlink_to(system_python)
    monkeypatch.setattr(pilot.sys, "executable", str(link))
    assert pilot._guest_python() == str(system_python.resolve())


def test_guest_python_refuses_missing_system_binary_via_symlink(
    tmp_path, monkeypatch,
):
    venv_bin = tmp_path / ".venv" / "bin"
    venv_bin.mkdir(parents=True)
    link = venv_bin / "python"
    link.symlink_to("/usr/bin/python3-m0s-nonexistent")
    monkeypatch.setattr(pilot.sys, "executable", str(link))
    with pytest.raises(pilot.Refused, match="SYSTEM_PYTHON_NOT_REGULAR"):
        pilot._guest_python()


def test_no_host_wide_security_policy_install_commands_exist():
    text = Path(pilot.__file__).read_text(encoding="utf-8")
    for forbidden in (
        "systemctl ", "apparmor_parser ", "aa-exec ", "mount -",
        "subprocess.run(['sudo'", "os.killpg(",
        "PROJECT_STATE_DB_VERSION = 3",
    ):
        assert forbidden not in text


def test_expected_phase_separation_is_expressed_in_script_source():
    src = Path(pilot.__file__).read_text(encoding="utf-8")
    assert "os.setgroups([_SERVICE_WRITE_GID] if with_writer_group else [])" in src
    assert "os.setresgid(uid, uid, uid)" in src
    assert "os.setresuid(uid, uid, uid)" in src
    assert 'os.chmod(state, 0o2770' in src
    assert 'shutil.rmtree(root)' in src
    assert "NO_GO_DISPOSABLE_LAB_REFUSED" in src
