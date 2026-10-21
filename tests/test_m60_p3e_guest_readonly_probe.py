"""Synthetic P3e tests; not a real VM trust, mount or credential witness."""
from __future__ import annotations

import json
import sys

import pytest
from scripts import p3e_guest_readonly_probe as p3e


def test_missing_ack_refuses_before_any_reads(monkeypatch, capsys):
    monkeypatch.setattr(p3e, "observe", lambda: pytest.fail("must not inspect"))
    assert p3e.main([]) == 2
    assert capsys.readouterr().err.strip() == "P3E_PROBE_REFUSED"


@pytest.mark.parametrize("args", [[], ["--help"], ["--i-am-on-a-separate-disposable-vm", "/tmp"], ["--candidate-dir", "/tmp"], ["--i-am-on-a-separate-disposable-vm", "--sudo"]])
def test_only_one_exact_flag_is_allowed(monkeypatch, capsys, args):
    monkeypatch.setattr(p3e, "observe", lambda: pytest.fail("unexpected inspection"))
    assert p3e.main(args) == 2
    assert capsys.readouterr().err.strip() == "P3E_PROBE_REFUSED"


@pytest.mark.parametrize("identity", [(0, 0, 0, 0), (1000, 0, 1000, 1000), (1000, 1000, 1000, 0)])
def test_root_and_setid_refused(monkeypatch, capsys, identity):
    for name, value in zip(("getuid", "geteuid", "getgid", "getegid"), identity):
        monkeypatch.setattr(p3e.os, name, lambda v=value: v)
    monkeypatch.setattr(p3e, "observe", lambda: pytest.fail("unexpected inspection"))
    assert p3e.main([p3e._ACK]) == 2
    assert capsys.readouterr().err.strip() == "P3E_PROBE_REFUSED"


@pytest.mark.parametrize("vendor,product,hint", [
    (b"QEMU", b"Standard PC (Q35 + ICH9, 2009)", "DMI_VIRTUAL_BRAND_HINT_ONLY"),
    (b"innotek GmbH", b"VirtualBox", "DMI_VIRTUAL_BRAND_HINT_ONLY"),
    (b"Acme Systems", b"Bareboard", "DMI_NO_RECOGNIZED_VIRTUAL_BRAND"),
    (None, None, "DMI_NOT_READABLE"),
])
def test_vendor_only_hint_never_proves_vm(monkeypatch, vendor, product, hint):
    samples = dict(zip(p3e._DMI_PATHS, (vendor, product)))
    monkeypatch.setattr(p3e, "_fixed_read", lambda path, limit: samples.get(path))
    assert p3e._virtual_guest_hint() == hint


@pytest.mark.parametrize("data,result", [
    (b"Name:\ttest\nCapEff:\t0000000000000000\n", "CAPABILITIES_ZERO_OBSERVED"),
    (b"CapEff:\t0000000000000001\n", "CAPABILITIES_PRESENT_OBSERVED"),
    (b"CapEff:\tgarbage\n", "CAPABILITIES_UNKNOWN"),
    (b"CapEff:\t0\nCapEff:\t0\n", "CAPABILITIES_UNKNOWN"),
    (None, "CAPABILITIES_UNKNOWN"),
])
def test_capability_hint(monkeypatch, data, result):
    monkeypatch.setattr(p3e, "_fixed_read", lambda path, limit: data)
    assert p3e._effective_caps_hint() == result


@pytest.mark.parametrize("data,expected", [
    (b"13.1\n", "DEBIAN_VERSION_FILE_OBSERVED"),
    (b"bookworm/sid\n", "DEBIAN_VERSION_FILE_OBSERVED"),
    (b"secret /home/test\n", "DEBIAN_LINEAGE_UNKNOWN"),
    (None, "DEBIAN_LINEAGE_UNKNOWN"),
])
def test_os_lineage_hint(monkeypatch, data, expected):
    monkeypatch.setattr(p3e, "_fixed_read", lambda path, limit: data)
    assert p3e._debian_hint() == expected


def test_probe_is_always_no_go_and_redacts_untrusted_hints(monkeypatch):
    monkeypatch.setattr(p3e, "_fixed_read", lambda path, limit: b"VirtualBox with SECRET /home/operator")
    monkeypatch.setattr(p3e.platform, "system", lambda: "Linux")
    out = p3e.observe()
    serialized = json.dumps(out)
    assert out["decision"] == "P3E_NO_GO_SEPARATE_VM_UNATTESTED"
    assert out["privileged_trial_authorized"] is False
    assert out["actual_p3_cases_executed"] == 0
    assert "SECRET" not in serialized
    assert "/home/operator" not in serialized
    assert out["vm_vs_container_and_isolation"] == "UNVERIFIED"


def test_nonroot_success_still_no_go(monkeypatch, capsys):
    for name in ("getuid", "geteuid", "getgid", "getegid"):
        monkeypatch.setattr(p3e.os, name, lambda: 1000)
    monkeypatch.setattr(p3e, "_fixed_read", lambda path, limit: None)
    monkeypatch.setattr(p3e.platform, "system", lambda: "Linux")
    assert p3e.main([p3e._ACK]) == 0
    cap = capsys.readouterr()
    assert cap.err == ""
    out = json.loads(cap.out)
    assert out["decision"] == "P3E_NO_GO_SEPARATE_VM_UNATTESTED"
    assert out["operator_disposable_vm_assertion"] == "UNVERIFIED_SELF_ASSERTION"


def test_fixed_path_allowlist():
    with pytest.raises(ValueError, match="P3E_INTERNAL_PATH_REFUSED"):
        p3e._fixed_read("/home/user/.ssh/id_rsa", 256)


def test_fixed_read_bounded_and_unreadable(monkeypatch):
    class FakeFile:
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def read(self, n):
            assert n == 257
            return b"X" * n
    monkeypatch.setattr(p3e.Path, "open", lambda self, mode: FakeFile())
    assert p3e._fixed_read(p3e._DMI_PATHS[0], 256) is None


def test_checked_in_decision_does_not_authorize():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    src = root / "docs/architecture/p3/p3e-disposable-guest-observation-decision.json"
    obj = json.loads(src.read_text(encoding="utf-8"))
    assert obj["decision"] == "P3E_NO_GO_SEPARATE_VM_UNATTESTED"
    assert obj["automatic_go"] is False
    assert obj["actual_p3_f01_to_f28_executed"] == 0
    assert all(x is False for x in obj["permissions"].values())
