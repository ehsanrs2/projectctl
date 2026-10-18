"""M0p bounded contract and VM root opt-in guard tests (NEVER sudo in CI).

CI does not execute --run, create users, modify credentials, inspect arbitrary
PIDs, alter systemd, or attest all-writer closure. Only the operator may run
the executable guest experiment after a separate review/merge.
"""
from __future__ import annotations

import json
from dataclasses import fields, replace
from pathlib import Path

import pytest

from scripts import m0p_guest_dual_uid_handoff_lab as guest
from scripts.m0p_guest_handoff_contract import (
    LabDecision, LabObservations, review,
)


def _all_true() -> LabObservations:
    return LabObservations(**{
        entry.name: True for entry in fields(LabObservations)
    })


def test_all_bounded_true_observations_still_never_grant_migration():
    result = review(_all_true())
    assert result == LabDecision(
        "NO_GO_UNTRUSTED_CANDIDATE_EXECUTION_IDENTITY",
        authorizes_migration=False,
    )
    assert len(fields(LabObservations)) == 10


@pytest.mark.parametrize(
    "field_name", [entry.name for entry in fields(LabObservations)]
)
@pytest.mark.parametrize("unverified", [False, None, 0, 1, "yes", "true"])
def test_every_missing_nonliteral_true_observation_fails_closed(
    field_name, unverified,
):
    sample = replace(_all_true(), **{field_name: unverified})
    result = review(sample)
    assert result.decision == "NO_GO_UNVERIFIED_" + field_name.upper()
    assert result.authorizes_migration is False


def test_invalid_observation_types_are_no_go():
    for payload in (None, {}, True, "passed", [], 1):
        result = review(payload)
        assert result == LabDecision("NO_GO_INVALID_LAB_OBSERVATIONS")


def test_vm_inspect_is_non_authorizing_and_does_not_run_root_trial(
    monkeypatch, capsys,
):
    monkeypatch.setattr(guest, "_virtualization", lambda: "kvm")
    monkeypatch.setattr(guest, "_filesystem", lambda: "ext4")

    def forbid_trial():
        raise AssertionError("must not execute privileged trial in inspect")

    monkeypatch.setattr(guest, "_trial", forbid_trial)
    assert guest.main(["--inspect"]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["decision"] == "OWNER_REVIEW_REQUIRED"
    assert output["authorizes_migration"] is False
    assert output["guest_virt"] == "kvm"
    assert output["guest_fs"] == "ext4"


def test_non_kvm_run_refuses_before_any_actor_or_fixture(
    monkeypatch, capsys,
):
    monkeypatch.setattr(guest, "_virtualization", lambda: "unknown")
    monkeypatch.setattr(guest, "_filesystem", lambda: "ext4")
    monkeypatch.setattr(
        guest, "_trial", lambda: pytest.fail("trial must not run"),
    )
    assert guest.main([
        "--run", "--acknowledge", guest._ACK,
    ]) == 1
    output = json.loads(capsys.readouterr().out)
    assert output["decision"] == "NO_GO_LAB_REFUSED"
    assert output["reason"] == "NOT_A_KVM_QEMU_LINUX_GUEST"
    assert output["authorizes_migration"] is False


def test_ack_and_ext4_and_root_required_before_mutation(monkeypatch):
    monkeypatch.setattr(guest, "_virtualization", lambda: "kvm")
    monkeypatch.setattr(guest, "_filesystem", lambda: "ext4")
    with pytest.raises(guest.GuestLabRefused, match="ACK_MISSING"):
        guest._preflight(None)
    monkeypatch.setattr(guest, "_filesystem", lambda: "tmpfs")
    with pytest.raises(guest.GuestLabRefused, match="VAR_TMP_NOT"):
        guest._preflight(guest._ACK)
    monkeypatch.setattr(guest, "_filesystem", lambda: "ext4")
    monkeypatch.setattr(guest.os, "getuid", lambda: 1000)
    monkeypatch.setattr(guest.os, "geteuid", lambda: 1000)
    with pytest.raises(guest.GuestLabRefused, match="ROOT_WITHIN_GUEST"):
        guest._preflight(guest._ACK)


def test_root_invoker_requires_sudo_nonroot_credentials(monkeypatch):
    monkeypatch.setattr(guest, "_virtualization", lambda: "kvm")
    monkeypatch.setattr(guest, "_filesystem", lambda: "ext4")
    monkeypatch.setattr(guest.os, "getuid", lambda: 0)
    monkeypatch.setattr(guest.os, "geteuid", lambda: 0)
    for key in ("SUDO_UID", "SUDO_GID", "SUDO_USER"):
        monkeypatch.delenv(key, raising=False)
    with pytest.raises(guest.GuestLabRefused, match="SUDO_NONROOT_INVOKER"):
        guest._preflight(guest._ACK)


def test_disposable_mutator_refuses_arbitrary_path_and_never_reaches_chown(
    tmp_path, monkeypatch,
):
    outsider = tmp_path / "real-project"
    outsider.mkdir()
    (outsider / ".projectctl").mkdir()
    monkeypatch.setattr(
        guest.os, "chown",
        lambda *args, **kwargs: pytest.fail("must not call chown"),
    )
    with pytest.raises(
        guest.GuestLabRefused, match="NOT_A_SCRIPT_OWNED_DISPOSABLE_ROOT"
    ):
        guest._controlled_tree_ownership(outsider, 0)


def test_denial_checks_require_actual_permission_denial():
    assert guest._open_denied({"status": "denied", "errno": 13})
    assert guest._open_denied({"status": "denied", "errno": 1})
    assert not guest._open_denied({"status": "denied", "errno": 2})
    assert not guest._open_denied({"status": "wrote", "errno": 13})
    assert not guest._denied({"status": "wrote"})


def test_actor_command_cannot_resolve_private_venv_as_unprivileged_binary(
    monkeypatch,
):
    monkeypatch.setattr(guest.sys, "executable", "/home/example/.venv/python")
    with pytest.raises(guest.GuestLabRefused, match="GUEST_SYSTEM_PYTHON"):
        guest._command(Path("/var/tmp/projectctl-m0p-example"), "db", "test")


def test_source_code_does_not_use_sudo_or_services_to_change_machine():
    file_text = Path(guest.__file__).read_text(encoding="utf-8")
    # Only source inspection: not an adversarial production safety attestation.
    assert "systemctl " not in file_text
    assert "os.system(" not in file_text
    assert "os.killpg(" not in file_text
    assert "PROJECT_STATE_DB_VERSION != 2" in file_text
