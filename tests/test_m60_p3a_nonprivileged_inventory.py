"""M6.0 P3a: hermetic denial and redaction tests; no real host attestation."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from scripts import p3a_nonprivileged_inventory as inv


@pytest.fixture
def test_environment(tmp_path, monkeypatch):
    monkeypatch.setattr(inv.os, "getuid", lambda: 1000)
    monkeypatch.setattr(inv.os, "geteuid", lambda: 1000)
    monkeypatch.setattr(inv.os, "getgid", lambda: 1000)
    monkeypatch.setattr(inv.os, "getegid", lambda: 1000)
    monkeypatch.setattr(inv.os, "getgroups", lambda: [1000, 1001])
    proc = tmp_path / "synthetic-proc"
    proc.mkdir()
    (proc / "status").write_text("Name:\tprivate-secret\nCapEff:\t0000000000000000\n")
    (proc / "mountinfo").write_text(
        "20 19 0:1 / / rw,relatime - ext4 /dev/private-secret rw\n"
    )
    candidate = tmp_path / "disposable"
    candidate.mkdir()
    return candidate, proc


def test_bounded_observation_is_nonauthorizing_and_redacts_paths(test_environment):
    candidate, proc = test_environment
    result = inv.collect_inventory(str(candidate), proc_root=proc)
    assert result["decision"] == "P3A_INVENTORY_ONLY_NO_GO"
    assert result["classification"] == "UNTRUSTED_READ_ONLY_OBSERVATION"
    assert result["candidate"]["path_disclosed"] is False
    assert result["candidate"]["existing_directory"] is True
    assert result["mount"] == {"filesystem_type": "ext4", "mount_readonly_observed": False}
    assert result["process"]["effective_capabilities"] == "NONE_OBSERVED"
    assert all(v is False for v in result["authorization"].values())
    raw = json.dumps(result)
    for secret in (str(candidate), str(proc), "private-secret", "/dev/"):
        assert secret not in raw


@pytest.mark.parametrize("bad", ["relative", "/", "/tmp/../etc", "/tmp//name",
                                        "/tmp/.", "/tmp/.projectctl", "/home/u/projectctl-m0k-lab"])
def test_unsafe_paths_fail_closed_and_do_not_echo(bad, test_environment):
    _, proc = test_environment
    with pytest.raises(inv.P3aRefusal, match="^P3A_INVENTORY_REFUSED$"):
        inv.collect_inventory(bad, proc_root=proc)


def test_symlink_component_is_rejected(test_environment, tmp_path):
    candidate, proc = test_environment
    alias = tmp_path / "alias"
    alias.symlink_to(candidate, target_is_directory=True)
    with pytest.raises(inv.P3aRefusal):
        inv.collect_inventory(str(alias), proc_root=proc)


def test_root_and_setuid_are_refused_before_observing_paths(test_environment, monkeypatch):
    candidate, proc = test_environment
    monkeypatch.setattr(inv.os, "geteuid", lambda: 0)
    with pytest.raises(inv.P3aRefusal):
        inv.collect_inventory(str(candidate), proc_root=proc)
    monkeypatch.setattr(inv.os, "geteuid", lambda: 999)
    with pytest.raises(inv.P3aRefusal):
        inv.collect_inventory(str(candidate), proc_root=proc)


def test_missing_or_excessively_long_proc_fails_closed(test_environment):
    candidate, proc = test_environment
    (proc / "mountinfo").write_text("Z" * (1048576 + 1))
    with pytest.raises(inv.P3aRefusal):
        inv.collect_inventory(str(candidate), proc_root=proc)
    (proc / "mountinfo").unlink()
    with pytest.raises(inv.P3aRefusal):
        inv.collect_inventory(str(candidate), proc_root=proc)


def test_unknown_acl_and_capabilities_do_not_imply_safety(test_environment, monkeypatch):
    candidate, proc = test_environment
    (proc / "status").write_text("CapEff: invalid\n")
    monkeypatch.setattr(inv.os, "listxattr", lambda *a, **kw: (_ for _ in ()).throw(OSError()))
    r = inv.collect_inventory(str(candidate), proc_root=proc)
    assert r["process"]["effective_capabilities"] == "UNKNOWN"
    assert all(x["acl"] == "UNKNOWN" for x in r["ancestry"])
    assert r["decision"].endswith("NO_GO")


def test_no_candidate_contents_read_or_write(test_environment, monkeypatch):
    candidate, proc = test_environment
    (candidate / "private-state.sqlite").write_text("NEVER_READ")
    (candidate / "private.json").write_text("NEVER_READ")
    r = inv.collect_inventory(str(candidate), proc_root=proc)
    assert r["candidate"]["existing_directory"] is True
    assert "NEVER_READ" not in json.dumps(r)
    assert (candidate / "private-state.sqlite").read_text() == "NEVER_READ"


def test_main_outputs_json_with_no_disk_report(test_environment, monkeypatch, capsys):
    candidate, proc = test_environment
    original = inv.collect_inventory
    monkeypatch.setattr(inv, "collect_inventory", lambda c: original(c, proc_root=proc))
    assert inv.main(["--candidate-dir", str(candidate)]) == 0
    output = capsys.readouterr().out
    assert json.loads(output)["decision"] == "P3A_INVENTORY_ONLY_NO_GO"
    assert str(candidate) not in output
