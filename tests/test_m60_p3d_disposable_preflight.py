"""M6.0 P3d offline no-authority schema tests (synthetic only)."""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pytest

from scripts import p3d_disposable_preflight as p3d


def request():
    return {
        "schema_kind": "projectctl.m6_0.p3d.disposable_trial_request",
        "schema_version": 1,
        "classification": "UNTRUSTED_OWNER_REQUEST_NOT_APPROVAL",
        "decision_claim": "NO_GO_REQUEST_ONLY",
        "selected_pattern": "P3C_T1_DISPOSABLE_VM_STATIC_DUAL_PRINCIPAL_WITH_TRUSTED_ADMIN",
        "scope_claims": {k: False for k in p3d.SCOPE_FLAGS},
        "evidence_claims": {k: "MISSING" for k in p3d.EVIDENCE_KEYS},
        "prohibited_actions": {k: False for k in p3d.DENIAL_FLAGS},
        "cases": [{"id": f"P3-F{i:02d}", "status": "NOT_RUN"} for i in range(1, 29)],
        "owner_authorization": False,
        "reviewer_authorization": False,
    }


def test_baseline_unfilled_never_authorizes():
    output = p3d.review_request(request())
    assert output["decision"] == "P3D_NO_GO_TRIAL_NOT_AUTHORIZED"
    assert output["dossier_status"] == "DOSSIER_INCOMPLETE"
    assert len(output["missing_evidence_keys"]) == 10
    assert len(output["unmet_scope_keys"]) == 5
    assert output["actual_trial_cases_executed"] == 0
    assert all(x is False for x in output["authorizations"].values())


def test_all_claims_present_still_no_go():
    r = request()
    r["scope_claims"] = {k: True for k in p3d.SCOPE_FLAGS}
    r["evidence_claims"] = {k: "CLAIMED_UNVERIFIED" for k in p3d.EVIDENCE_KEYS}
    output = p3d.review_request(r)
    assert output["dossier_status"] == "HUMAN_CLAIMS_PRESENT_UNVERIFIED"
    assert output["decision"] == "P3D_NO_GO_TRIAL_NOT_AUTHORIZED"
    assert output["external_owner_review_required"] is True
    assert output["external_security_review_required"] is True
    assert all(x is False for x in output["authorizations"].values())


@pytest.mark.parametrize("mutation", [
    lambda p: p.update(schema_version=True),
    lambda p: p.update(schema_kind="wrong"),
    lambda p: p.update(decision_claim="GO"),
    lambda p: p.update(owner_authorization=True),
    lambda p: p.update(reviewer_authorization=True),
    lambda p: p.update(executable_command="sudo -n true"),
    lambda p: p["scope_claims"].update(uses_only_disposable_guest="true"),
    lambda p: p["scope_claims"].update(unrestricted=True),
    lambda p: p["evidence_claims"].update(exact_disposable_vm_isolation_and_reset="APPROVED"),
    lambda p: p["evidence_claims"].update(exact_disposable_vm_isolation_and_reset="/private/path"),
    lambda p: p["evidence_claims"].pop("independent_administrator_and_observer"),
    lambda p: p["prohibited_actions"].update(authorize_any_disposable_trial=True),
    lambda p: p["cases"].pop(),
    lambda p: p["cases"].append({"id": "P3-F29", "status": "NOT_RUN"}),
    lambda p: p["cases"][2].update(status="PASSED"),
    lambda p: p["cases"][2].update(id="P3-F02"),
    lambda p: p["cases"][2].update(note="private-path"),
    lambda p: p.update(selected_pattern="P3C_T0_SAME_UID"),
])
def test_rejects_unsafe_or_extra_claims(mutation):
    p = request()
    mutation(p)
    with pytest.raises(p3d.P3dRefusal, match="^P3D_PREFLIGHT_REFUSED$"):
        p3d.review_request(p)


@pytest.mark.parametrize("raw", [
    b"", b"not-json", b"{}", b"\xff", b"{" + b"x" * 25000 + b"}",
    b'{"schema_kind":"good","schema_kind":"evil"}',
    b'{"owner_authorization":NaN}',
])
def test_strict_parse_refusal_without_data_reflection(raw):
    with pytest.raises(p3d.P3dRefusal, match="^P3D_PREFLIGHT_REFUSED$"):
        p3d.review_request(p3d.parse_request(raw))


def test_roundtrip_output_redacts_all_input_identifiers():
    r = request()
    raw = json.dumps(r).encode()
    out = json.dumps(p3d.review_request(p3d.parse_request(raw)))
    assert "/tmp" not in out
    assert "P3-F01" not in out
    assert "P3D_NO_GO_TRIAL_NOT_AUTHORIZED" in out


def test_cli_stdin_only_no_files(monkeypatch, capsys):
    class FakeStdin:
        buffer = io.BytesIO(json.dumps(request()).encode())
    monkeypatch.setattr(sys, "stdin", FakeStdin())
    monkeypatch.setattr(p3d.os, "getuid", lambda: 1000)
    monkeypatch.setattr(p3d.os, "geteuid", lambda: 1000)
    monkeypatch.setattr(p3d.os, "getgid", lambda: 1000)
    monkeypatch.setattr(p3d.os, "getegid", lambda: 1000)
    assert p3d.main() == 0
    s = capsys.readouterr()
    assert not s.err
    assert json.loads(s.out)["decision"] == "P3D_NO_GO_TRIAL_NOT_AUTHORIZED"


def test_cli_root_refused_before_stdin_read(monkeypatch, capsys):
    monkeypatch.setattr(p3d.os, "getuid", lambda: 0)
    monkeypatch.setattr(p3d.os, "geteuid", lambda: 0)
    assert p3d.main() == 2
    assert capsys.readouterr().err.strip() == "P3D_PREFLIGHT_REFUSED"

def test_checked_in_template_is_exact_unfilled_no_go_request():
    root = Path(__file__).resolve().parents[1]
    raw = (root / "docs/architecture/p3/p3d-disposable-trial-request.template.json").read_bytes()
    assert p3d.parse_request(raw) == request()
    assert p3d.review_request(p3d.parse_request(raw))["decision"] == "P3D_NO_GO_TRIAL_NOT_AUTHORIZED"
