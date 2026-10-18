"""M0m safety contract tests: no privileged operation, no real guest mutation.

A root-only optional guest probe is explicitly out of CI; these tests
prove only parser/decision and refusal properties, not kernel enforcement.
"""
from __future__ import annotations

import json
from dataclasses import fields, replace

import pytest

from scripts import m0m_vm_dac_embargo_pilot as lab


def _all_observed() -> lab.Observations:
    return lab.Observations(**{
        f.name: True for f in fields(lab.Observations)
    })


def test_even_complete_dac_evidence_requires_no_go_due_to_preopened_fd():
    assert lab.decide(_all_observed()) == (
        "NO_GO_PREOPENED_FD_REMAINS_WRITABLE"
    )
    assert len(fields(lab.Observations)) == 8


@pytest.mark.parametrize("field_name", [f.name for f in fields(lab.Observations)])
@pytest.mark.parametrize("unverified", [False, None, 1, "true", "false"])
def test_missing_or_truthy_claims_never_satisfy_literal_kernel_observation(
    field_name, unverified,
):
    value = replace(_all_observed(), **{field_name: unverified})
    assert lab.decide(value) == "NO_GO_UNVERIFIED_" + field_name.upper()


def test_invalid_observation_types_refused():
    for value in ({}, None, True, "ok"):
        assert lab.decide(value) == "NO_GO_UNVERIFIED_LAB_OBSERVATIONS"


def test_unreviewed_vm_or_wrong_ack_refuses_before_any_root_op(monkeypatch):
    monkeypatch.setattr(lab, "_virt", lambda: "unknown")
    monkeypatch.setattr(lab, "_filesystem", lambda: "ext4")
    with pytest.raises(lab.LabRefused, match="NOT_A_REVIEWED_KVM"):
        lab._preflight(lab._ACK)

    monkeypatch.setattr(lab, "_virt", lambda: "kvm")
    with pytest.raises(lab.LabRefused, match="EXPLICIT_DISPOSABLE"):
        lab._preflight(None)


def test_non_ext4_var_tmp_refuses_before_any_root_op(monkeypatch):
    monkeypatch.setattr(lab, "_virt", lambda: "kvm")
    monkeypatch.setattr(lab, "_filesystem", lambda: "tmpfs")
    with pytest.raises(lab.LabRefused, match="VAR_TMP_NOT_GUEST_LOCAL_EXT4"):
        lab._preflight(lab._ACK)


def test_inspect_is_non_authorizing_and_does_not_require_root(
    monkeypatch, capsys,
):
    monkeypatch.setattr(lab, "_virt", lambda: "kvm")
    monkeypatch.setattr(lab, "_filesystem", lambda: "ext4")
    assert lab.main(["--inspect"]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["decision"] == "OWNER_MUST_REVIEW_DISPOSABLE_GUEST"
    assert output["authorizes_migration"] is False
    assert output["var_tmp_fstype"] == "ext4"


def test_run_without_guest_refuses_without_touching_fixture(
    monkeypatch, capsys,
):
    monkeypatch.setattr(lab, "_virt", lambda: "unknown")
    monkeypatch.setattr(lab, "_filesystem", lambda: "ext4")
    assert lab.main(["--run", "--acknowledge", lab._ACK]) == 1
    output = json.loads(capsys.readouterr().out)
    assert output["decision"] == "NO_GO_LAB_REFUSED"
    assert output["authorizes_migration"] is False


def test_scope_mutation_refuses_arbitrary_project_root(tmp_path):
    project_state = tmp_path / ".projectctl"
    project_state.mkdir()
    with pytest.raises(lab.LabRefused, match="NOT_PRIVATE_M0M_FIXTURE"):
        lab._scoped_tree_ownership(project_state, 12345, 12345)
