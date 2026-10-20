"""Hermetic P3b contract tests; no real OS, custody or reboot tests."""
from __future__ import annotations

import io
import json
import sys

import pytest

from scripts import p3b_trial_readiness_review as p3b


def _inventory() -> dict:
    row = {
        "position": "ancestor", "owner_is_effective_uid": False,
        "group_matches_process": False, "owner_write_bit": True,
        "group_write_bit": False, "other_write_bit": False,
        "sticky_bit": False, "acl": "ACL_XATTR_NOT_SEEN",
    }
    return {
        "schema_kind": "projectctl.m6_0.p3a.nonprivileged_inventory",
        "schema_version": 1, "classification": "UNTRUSTED_READ_ONLY_OBSERVATION",
        "decision": "P3A_INVENTORY_ONLY_NO_GO",
        "candidate": {"depth": 1, "existing_directory": True, "path_disclosed": False},
        "process": {"effective_uid": 1234, "effective_gid": 1234,
                    "supplementary_group_count": 2,
                    "effective_capabilities": "NONE_OBSERVED"},
        "platform": {"os": "Linux", "kernel_release": "6.12.0-synthetic"},
        "mount": {"filesystem_type": "tmpfs", "mount_readonly_observed": False},
        "ancestry": [row, {**row, "position": "candidate", "sticky_bit": True,
                           "group_write_bit": True, "other_write_bit": True}],
        "unknowns": sorted(p3b._UNKNOWN),
        "authorization": {key: False for key in p3b._AUTH_KEYS},
    }


def test_debian_shaped_tmpfs_is_rejected_for_durable_custody():
    r = p3b.review_inventory(_inventory())
    assert r["decision"] == "P3B_NO_GO_TRIAL_UNAUTHORIZED"
    assert r["target_assessment"] == "VOLATILE_FS_REJECT_FOR_DURABLE_CUSTODY"
    assert "STICKY_BIT_IS_NOT_CUSTODY_BOUNDARY" in r["blockers"]
    assert "SHARED_WRITABLE_CANDIDATE_OBSERVED" in r["blockers"]
    assert all(v is False for v in r["authorizations"].values())
    assert r["safe_to_retry_or_auto_promote"] is False


@pytest.mark.parametrize("fs", ["ext4", "btrfs", "xfs", "overlay", "UNKNOWN"])
def test_nonvolatile_fs_cannot_promote_to_go(fs):
    p = _inventory()
    p["mount"]["filesystem_type"] = fs
    p["ancestry"][1].update(other_write_bit=False, group_write_bit=False, sticky_bit=False)
    r = p3b.review_inventory(p)
    assert r["target_assessment"] == "PERSISTENCE_UNVERIFIED"
    assert r["decision"] == "P3B_NO_GO_TRIAL_UNAUTHORIZED"
    assert all(v is False for v in r["authorizations"].values())


@pytest.mark.parametrize("change", [
    lambda p: p.update(decision="GO_FOR_DISPOSABLE_TRIAL"),
    lambda p: p["authorization"].update(trial_with_privileges=True),
    lambda p: p["candidate"].update(path_disclosed=True),
    lambda p: p["candidate"].update(depth=True),
    lambda p: p["process"].update(effective_uid=0),
    lambda p: p["process"].update(effective_capabilities="ELEVATED"),
    lambda p: p["platform"].update(kernel_release="SECRET /home/operator"),
    lambda p: p["mount"].update(filesystem_type="tmpfs;rm"),
    lambda p: p["mount"].update(mount_readonly_observed=1),
    lambda p: p["unknowns"].pop(),
    lambda p: p["ancestry"].pop(),
    lambda p: p["ancestry"][1].update(acl="TRUSTED"),
    lambda p: p.update(secret="SHOULD_NEVER_ECHO"),
])
def test_invalid_or_unsafe_inputs_fail_closed(change):
    p = _inventory()
    change(p)
    with pytest.raises(p3b.P3bRefusal, match="^P3B_REVIEW_REFUSED$"):
        p3b.review_inventory(p)


@pytest.mark.parametrize("raw", [
    b"", b"not-json", b"{}", b"{" + b"a" * 16384 + b"}",
    b'{"schema_kind":"X","schema_kind":"Y"}',
    b'{"x":NaN}', b'\xff',
])
def test_invalid_json_is_refused_without_echo(raw):
    with pytest.raises(p3b.P3bRefusal, match="^P3B_REVIEW_REFUSED$"):
        p3b.review_inventory(p3b.parse_p3a_bytes(raw))


def test_json_roundtrip_does_not_publish_host_data():
    p = _inventory()
    raw = json.dumps(p, separators=(",", ":")).encode()
    r = p3b.review_inventory(p3b.parse_p3a_bytes(raw))
    out = json.dumps(r)
    assert "/tmp" not in out
    assert "6.12.0" not in out
    assert "1234" not in out
    assert "tmpfs" not in out


def test_unknown_capabilities_still_refuse_any_trial():
    p = _inventory()
    p["process"]["effective_capabilities"] = "UNKNOWN"
    r = p3b.review_inventory(p)
    assert "CALLER_EFFECTIVE_CAPABILITIES_NOT_ZERO_CONFIRMED" in r["blockers"]
    assert r["decision"] == "P3B_NO_GO_TRIAL_UNAUTHORIZED"


def test_main_reads_stdin_and_writes_no_files(monkeypatch, capsys):
    class FakeStdin:
        buffer = io.BytesIO(json.dumps(_inventory()).encode())
    monkeypatch.setattr(sys, "stdin", FakeStdin())
    monkeypatch.setattr(p3b.os, "getuid", lambda: 1000)
    monkeypatch.setattr(p3b.os, "geteuid", lambda: 1000)
    assert p3b.main() == 0
    cap = capsys.readouterr()
    assert not cap.err
    assert json.loads(cap.out)["decision"] == "P3B_NO_GO_TRIAL_UNAUTHORIZED"


def test_root_cli_refuses_before_stdin_read(monkeypatch, capsys):
    monkeypatch.setattr(p3b.os, "getuid", lambda: 0)
    monkeypatch.setattr(p3b.os, "geteuid", lambda: 0)
    assert p3b.main() == 2
    assert capsys.readouterr().err.strip() == "P3B_REVIEW_REFUSED"
