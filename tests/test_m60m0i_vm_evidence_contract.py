"""M6.0 M0i: disposable/offline evidence-verifier contract tests.

All results are SYNTHETIC JUnit artifacts and self-asserted environment
metadata. No kernel evidence, VM isolation, production authority or
external writer embargo is established by these unit tests.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import xml.etree.ElementTree as ET
from dataclasses import replace
from pathlib import Path

import pytest

from scripts.m0i_verify_vm_evidence import (
    EXPECTED_CASES,
    KERNEL_CASES,
    M0H_HEAD,
    M0H_MODULE,
    M0H_CLASS,
    MAX_FILE_BYTES,
    PROTOCOL,
    Review,
    review,
)


def _xml(*, skip=frozenset(), failure=frozenset(), error=frozenset(),
         omit=frozenset(), duplicate=False, wrong_class=False) -> bytes:
    cases = sorted(EXPECTED_CASES - set(omit))
    suites = ET.Element("testsuites")
    suite = ET.SubElement(
        suites, "testsuite",
        name="pytest",
        tests=str(len(cases) + int(duplicate)),
        failures=str(len(failure)),
        errors=str(len(error)),
        skipped=str(len(skip)),
    )
    for name in cases:
        case = ET.SubElement(
            suite, "testcase", name=name,
            classname="wrong.test_module" if wrong_class else M0H_CLASS,
        )
        if name in skip:
            ET.SubElement(case, "skipped", message="M0h OS namespace unshare denied")
        if name in failure:
            ET.SubElement(case, "failure", message="assertion failed")
        if name in error:
            ET.SubElement(case, "error", message="unexpected exception")
    if duplicate:
        ET.SubElement(suite, "testcase", name=cases[0], classname=M0H_CLASS)
    return ET.tostring(suites, encoding="utf-8", xml_declaration=True)


def _manifest(junit: bytes, kind="disposable_vm", **update) -> bytes:
    value = {
        "protocol": PROTOCOL,
        "m0h_commit": M0H_HEAD,
        "test_module": M0H_MODULE,
        "junit_sha256": hashlib.sha256(junit).hexdigest(),
        "environment": {
            "kind": kind,
            "kernel_release": "6.11.0-29-generic",
            "filesystem": "ext4",
            "scope_id": "disposable-vm-fixture-only",
            "userns_policy": "owner-reviewed-test-profile",
        },
    }
    value.update(update)
    return json.dumps(value, sort_keys=True).encode("utf-8")


def test_ideal_self_report_still_only_operator_lab_review():
    xml = _xml()
    result = review(_manifest(xml), xml)
    assert result == Review("LAB_REVIEW_ONLY", passed=7, skipped=0, failed=0)
    assert result.as_dict()["authorizes_migration"] is False


def test_owner_host_all_passes_still_no_operational_admission():
    xml = _xml()
    result = review(_manifest(xml, kind="owner_host"), xml)
    assert result.decision == "NO_GO_HOST_NOT_ISOLATED_VM"
    assert result.as_dict()["authorizes_migration"] is False


def test_five_actual_m0h_kernel_skips_are_refused():
    xml = _xml(skip=KERNEL_CASES)
    result = review(_manifest(xml, kind="owner_host"), xml)
    assert result == Review(
        "NO_GO_KERNEL_CASES_SKIPPED", passed=2, skipped=5, failed=0
    )
    assert result.as_dict()["authorizes_migration"] is False


@pytest.mark.parametrize("missing_skip", sorted(KERNEL_CASES))
def test_any_one_kernel_skip_blocks_a_claimed_vm(missing_skip):
    xml = _xml(skip={missing_skip})
    result = review(_manifest(xml), xml)
    assert result.decision == "NO_GO_KERNEL_CASES_SKIPPED"
    assert result.skipped == 1


@pytest.mark.parametrize("failure_kind", ["failure", "error"])
def test_any_real_test_failure_blocks(failure_kind):
    name = sorted(KERNEL_CASES)[0]
    kw = {failure_kind: {name}}
    xml = _xml(**kw)
    assert review(_manifest(xml), xml) == Review(
        "NO_GO_TEST_FAILURE_OR_ERROR", passed=6, skipped=0, failed=1
    )


def test_junit_byte_tamper_does_not_pass_digest_check():
    xml = _xml()
    assert review(_manifest(xml), xml + b" ").decision == (
        "QUARANTINE_JUNIT_DIGEST"
    )


@pytest.mark.parametrize("change", [
    {"m0h_commit": "0" * 40},
    {"test_module": "tests/test_other.py"},
    {"protocol": "projectctl-m0h-v1"},
    {"junit_sha256": "incorrect"},
    {"environment": {"kind": "disposable_vm"}},
])
def test_wrong_pin_schema_or_environment_is_quarantined(change):
    xml = _xml()
    assert review(_manifest(xml, **change), xml).decision == (
        "QUARANTINE_MANIFEST"
    )


def test_duplicate_manifest_fields_are_rejected():
    xml = _xml()
    raw = _manifest(xml)
    # Append a duplicate top-level key without changing the signed XML
    text = raw.decode().rstrip("}") + ', "protocol": "projectctl-m0i-v1"}'
    assert review(text.encode(), xml).decision == "QUARANTINE_MANIFEST"


@pytest.mark.parametrize("alteration", ["omit", "duplicate", "wrong_class", "doctype"])
def test_wrong_or_untrusted_junit_structure_is_quarantined(alteration):
    kw = {}
    if alteration == "omit":
        kw["omit"] = {sorted(EXPECTED_CASES)[0]}
    elif alteration == "duplicate":
        kw["duplicate"] = True
    elif alteration == "wrong_class":
        kw["wrong_class"] = True
    xml = _xml(**kw)
    if alteration == "doctype":
        xml = b'<!DOCTYPE testsuites [<!ENTITY x "unsafe">]>' + xml
    assert review(_manifest(xml), xml).decision == "QUARANTINE_JUNIT_CASES"


def test_huge_or_ill_formed_artifacts_do_not_become_review():
    xml = _xml()
    assert review(_manifest(xml), b"x" * (MAX_FILE_BYTES + 1)).decision == (
        "QUARANTINE_ARTIFACT_TOO_LARGE"
    )
    assert review(b"{", xml).decision == "QUARANTINE_MANIFEST"


def test_read_only_cli_emits_machine_result_and_never_migration_authority(tmp_path):
    xml = _xml(skip=KERNEL_CASES)
    junit = tmp_path / "pytest.xml"
    manifest = tmp_path / "manifest.json"
    junit.write_bytes(xml)
    manifest.write_bytes(_manifest(xml, kind="owner_host"))
    script = Path(__file__).resolve().parents[1] / "scripts" / (
        "m0i_verify_vm_evidence.py"
    )
    command = [
        sys.executable, "-B", str(script),
        "--manifest", str(manifest), "--junit", str(junit),
    ]
    denied = subprocess.run(
        command, capture_output=True, text=True, timeout=10, check=False,
    )
    assert denied.returncode == 2
    output = json.loads(denied.stdout)
    assert output["decision"] == "NO_GO_KERNEL_CASES_SKIPPED"
    assert output["authorizes_migration"] is False
    assert not denied.stderr

    manifest.write_bytes(_manifest(_xml(), kind="disposable_vm"))
    junit.write_bytes(_xml())
    lab = subprocess.run(
        command, capture_output=True, text=True, timeout=10, check=False,
    )
    assert lab.returncode == 0
    assert json.loads(lab.stdout)["decision"] == "LAB_REVIEW_ONLY"
    assert json.loads(lab.stdout)["authorizes_migration"] is False
