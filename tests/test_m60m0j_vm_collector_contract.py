"""M0j tests use synthetic JUnit and a mocked subprocess, never real mounts.

These do not prove a VM, kernel sandbox, authenticated source provenance,
or a production exclusion barrier. No owner installation is accessed.
"""
from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import m0j_collect_vm_evidence as collector
from scripts.m0i_verify_vm_evidence import EXPECTED_CASES, KERNEL_CASES, review


def _junit(*, skips=frozenset(), failures=frozenset()) -> bytes:
    root = ET.Element("testsuites")
    suite = ET.SubElement(
        root, "testsuite", name="pytest", tests="7",
        skipped=str(len(skips)), failures=str(len(failures)), errors="0",
    )
    for name in sorted(EXPECTED_CASES):
        case = ET.SubElement(
            suite, "testcase", classname=collector.M0H_MODULE.replace("/", ".")
            .removesuffix(".py"), name=name,
        )
        if name in skips:
            ET.SubElement(case, "skipped", message="namespace unshare denied")
        if name in failures:
            ET.SubElement(case, "failure", message="assertion error")
    return ET.tostring(root, encoding="utf-8")


def _ready(tmp_path: Path, monkeypatch):
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    private.chmod(0o700)
    monkeypatch.setattr(collector, "_check_checkout", lambda _path: checkout)
    monkeypatch.setattr(collector.platform, "system", lambda: "Linux")
    return checkout, private


def _fake_test(monkeypatch, xml: bytes, code: int = 0):
    calls = []

    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs))
        assert kwargs["cwd"].is_dir()
        assert kwargs["timeout"] == collector.TIMEOUT_SECONDS
        assert "PYTHONPATH" not in kwargs["env"]
        assert "PYTEST_ADDOPTS" not in kwargs["env"]
        junit_arg = next(arg for arg in argv if arg.startswith("--junitxml="))
        Path(junit_arg.split("=", 1)[1]).write_bytes(xml)
        return SimpleNamespace(returncode=code)
    monkeypatch.setattr(collector.subprocess, "run", fake_run)
    return calls


def _collect(checkout: Path, private: Path):
    return collector.collect(
        checkout, private,
        acknowledge=collector.ACK,
        scope_id="reviewed-disposable-guest-01",
        filesystem="ext4",
        userns_policy="operator-reviewed-guest-profile",
    )


def test_seven_clean_synthetic_cases_are_lab_review_only(tmp_path, monkeypatch):
    checkout, private = _ready(tmp_path, monkeypatch)
    calls = _fake_test(monkeypatch, _junit())
    outcome = _collect(checkout, private)
    assert outcome.decision == "LAB_REVIEW_ONLY"
    assert outcome.as_dict()["authorizes_migration"] is False
    assert (outcome.passed, outcome.skipped, outcome.failed) == (7, 0, 0)
    assert len(calls) == 1
    folder = Path(outcome.evidence_dir)
    assert folder.parent == private
    assert stat.S_IMODE(folder.stat().st_mode) == 0o700
    junit = folder / "m0h-junit.xml"
    manifest = folder / "manifest.json"
    assert stat.S_IMODE(junit.stat().st_mode) == 0o600
    assert stat.S_IMODE(manifest.stat().st_mode) == 0o600
    data = json.loads(manifest.read_text(encoding="utf-8"))
    assert data["m0h_commit"] == collector.M0H_HEAD
    assert data["environment"]["kind"] == "disposable_vm"
    assert data["junit_sha256"] == hashlib.sha256(junit.read_bytes()).hexdigest()
    assert review(manifest.read_bytes(), junit.read_bytes()).decision == (
        "LAB_REVIEW_ONLY"
    )
    assert collector.PROTOCOL == "projectctl-m0i-v1"


def test_actual_owner_host_skip_pattern_refused_and_retained(tmp_path, monkeypatch):
    checkout, private = _ready(tmp_path, monkeypatch)
    _fake_test(monkeypatch, _junit(skips=KERNEL_CASES))
    outcome = _collect(checkout, private)
    assert outcome.decision == "NO_GO_KERNEL_CASES_SKIPPED"
    assert (outcome.passed, outcome.skipped, outcome.failed) == (2, 5, 0)
    assert (Path(outcome.evidence_dir) / "manifest.json").is_file()


def test_pytest_nonzero_takes_priority_over_apparent_pass(tmp_path, monkeypatch):
    checkout, private = _ready(tmp_path, monkeypatch)
    _fake_test(monkeypatch, _junit(), code=5)
    outcome = _collect(checkout, private)
    assert outcome.decision == "NO_GO_PYTEST_NONZERO_EXIT"
    assert outcome.as_dict()["authorizes_migration"] is False


def test_test_failure_and_xml_failure_are_never_authorizing(tmp_path, monkeypatch):
    checkout, private = _ready(tmp_path, monkeypatch)
    _fake_test(monkeypatch, _junit(failures={next(iter(KERNEL_CASES))}))
    outcome = _collect(checkout, private)
    assert outcome.decision == "NO_GO_TEST_FAILURE_OR_ERROR"
    assert outcome.failed == 1


def test_missing_ack_does_not_create_folder_or_launch(tmp_path, monkeypatch):
    checkout, private = _ready(tmp_path, monkeypatch)

    def no_spawn(*_args, **_kwargs):
        raise AssertionError("unsafe subprocess spawned")
    monkeypatch.setattr(collector.subprocess, "run", no_spawn)
    with pytest.raises(collector.PilotRefused, match="operator_vm_review_missing"):
        collector.collect(
            checkout, private, acknowledge="not-reviewed",
            scope_id="guest-01", filesystem="ext4", userns_policy="test",
        )
    assert list(private.iterdir()) == []


def test_wrong_kernel_or_privileged_host_refused_before_spawn(
    tmp_path, monkeypatch,
):
    checkout, private = _ready(tmp_path, monkeypatch)
    monkeypatch.setattr(collector.platform, "system", lambda: "Darwin")
    with pytest.raises(collector.PilotRefused, match="non_linux_or_privileged"):
        _collect(checkout, private)
    monkeypatch.setattr(collector.platform, "system", lambda: "Linux")
    monkeypatch.setattr(collector.os, "geteuid", lambda: 0)
    with pytest.raises(collector.PilotRefused, match="non_linux_or_privileged"):
        _collect(checkout, private)
    assert list(private.iterdir()) == []


@pytest.mark.parametrize("problem", [
    "world_readable", "symlink", "missing",
])
def test_private_evidence_parent_is_mandatory(tmp_path, monkeypatch, problem):
    checkout, private = _ready(tmp_path, monkeypatch)
    if problem == "world_readable":
        private.chmod(0o755)
        selected = private
    elif problem == "symlink":
        selected = tmp_path / "alias"
        selected.symlink_to(private, target_is_directory=True)
    else:
        selected = tmp_path / "missing"
    with pytest.raises(collector.PilotRefused):
        _collect(checkout, selected)
    assert list(private.iterdir()) == []


def test_git_checkout_requires_pinned_clean_root(tmp_path, monkeypatch):
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    entries = {
        ("rev-parse", "--show-toplevel"): str(checkout),
        ("rev-parse", "HEAD"): collector.M0H_HEAD,
        ("status", "--porcelain", "--untracked-files=all"): "",
        ("ls-files", "--error-unmatch", collector.M0H_MODULE):
            collector.M0H_MODULE,
    }
    monkeypatch.setattr(
        collector, "_git",
        lambda _checkout, *argv: entries[argv],
    )
    assert collector._check_checkout(checkout) == checkout
    entries[("rev-parse", "HEAD")] = "0" * 40
    with pytest.raises(collector.PilotRefused, match="m0h_commit_not_pinned"):
        collector._check_checkout(checkout)
    entries[("rev-parse", "HEAD")] = collector.M0H_HEAD
    entries[("status", "--porcelain", "--untracked-files=all")] = " M tests/file.py"
    with pytest.raises(collector.PilotRefused, match="checkout_dirty"):
        collector._check_checkout(checkout)
    alias = tmp_path / "symlink"
    alias.symlink_to(checkout, target_is_directory=True)
    with pytest.raises(collector.PilotRefused, match="checkout_missing_or_symlinked"):
        collector._check_checkout(alias)


def test_malformed_vm_metadata_does_not_execute(tmp_path, monkeypatch):
    checkout, private = _ready(tmp_path, monkeypatch)
    for scope in ("", "../escape", "spaces not allowed"):
        with pytest.raises(collector.PilotRefused, match="invalid_scope_id"):
            collector.collect(
                checkout, private, acknowledge=collector.ACK,
                scope_id=scope, filesystem="ext4", userns_policy="reviewed",
            )
    assert list(private.iterdir()) == []


def test_vm_runner_timeout_fails_closed_without_manifest(tmp_path, monkeypatch):
    checkout, private = _ready(tmp_path, monkeypatch)

    def timeout(argv, **_kwargs):
        raise subprocess.TimeoutExpired(argv, 180)
    monkeypatch.setattr(collector.subprocess, "run", timeout)
    outcome = _collect(checkout, private)
    assert outcome.decision == "NO_GO_TEST_TIMEOUT"
    assert outcome.evidence_dir
    assert not (Path(outcome.evidence_dir) / "manifest.json").exists()


def test_inspect_does_not_collect_or_claim_vm(capsys, tmp_path, monkeypatch):
    checkout, private = _ready(tmp_path, monkeypatch)
    status = collector.main(["--checkout", str(checkout), "--inspect"])
    printed = json.loads(capsys.readouterr().out)
    assert status == 0
    assert printed["decision"] == "CHECKOUT_PINNED_REVIEW_VM_SEPARATELY"
    assert printed["authorizes_migration"] is False
    assert printed["evidence_dir"] is None
    assert list(private.iterdir()) == []


def test_collect_cli_demands_explicit_operator_vm_fields(capsys, tmp_path, monkeypatch):
    checkout, private = _ready(tmp_path, monkeypatch)
    status = collector.main([
        "--checkout", str(checkout), "--collect",
        "--output-parent", str(private),
    ])
    result = json.loads(capsys.readouterr().out)
    assert status == 2
    assert result["decision"] == "NO_GO_MISSING_EXPLICIT_VM_OR_EVIDENCE_ARGUMENTS"
    assert not list(private.iterdir())
