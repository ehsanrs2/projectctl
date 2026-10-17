"""M6.0 M0i: offline, read-only M0h JUnit evidence triage.

This script only reads a small owner-provided JSON manifest and a matching
JUnit XML document; it executes no probes, changes no system settings,
reads no live project SQLite/WAL, and authorizes NO migrations.

Hash equality and a claimed git SHA do NOT authenticate who produced
the evidence. Even seven passing cases only yield LAB_REVIEW_ONLY.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

PROTOCOL = "projectctl-m0i-v1"
M0H_HEAD = "4c0b28ebe3b05a3c550b8ccd10b419ab4d3dd6fe"
M0H_MODULE = "tests/test_m60m0h_mount_namespace_access_pilot.py"
M0H_CLASS = "tests.test_m60m0h_mount_namespace_access_pilot"
MAX_FILE_BYTES = 1_048_576

# The seven *actual* parameterized cases of the still-unmerged PR #78.
EXPECTED_CASES = frozenset({
    "test_kernel_readonly_bind_view_blocks_new_legacy_writes[view_db]",
    "test_kernel_readonly_bind_view_blocks_new_legacy_writes[view_json]",
    "test_same_inode_writable_via_unrestricted_source_alias[alias_db]",
    "test_same_inode_writable_via_unrestricted_source_alias[alias_json]",
    "test_preopened_writable_fd_is_not_revoked_by_mount_view",
    "test_independent_legacy_writer_outside_mount_namespace_can_write",
    "test_all_external_gates_mandatory_but_never_production_go",
})
KERNEL_CASES = frozenset({
    "test_kernel_readonly_bind_view_blocks_new_legacy_writes[view_db]",
    "test_kernel_readonly_bind_view_blocks_new_legacy_writes[view_json]",
    "test_same_inode_writable_via_unrestricted_source_alias[alias_db]",
    "test_same_inode_writable_via_unrestricted_source_alias[alias_json]",
    "test_preopened_writable_fd_is_not_revoked_by_mount_view",
})


class EvidenceRefused(ValueError):
    """Malformed or unverifiable evidence cannot create trusted authority."""


@dataclass(frozen=True)
class Review:
    decision: str
    passed: int = 0
    skipped: int = 0
    failed: int = 0

    def as_dict(self) -> dict[str, object]:
        return {
            "protocol": PROTOCOL,
            "decision": self.decision,
            "passed": self.passed,
            "skipped": self.skipped,
            "failed": self.failed,
            "authorizes_migration": False,
        }


def _read_bounded(path: Path) -> bytes:
    # Only reads explicit operator-selected paths. Never follows result
    # references embedded inside XML, and never writes or unshares.
    with path.open("rb") as stream:
        blob = stream.read(MAX_FILE_BYTES + 1)
    if len(blob) > MAX_FILE_BYTES:
        raise EvidenceRefused("artifact_too_large")
    return blob


def _unique_keys(pairs):
    data = {}
    for key, value in pairs:
        if key in data:
            raise EvidenceRefused("duplicate_manifest_key")
        data[key] = value
    return data


def _manifest(blob: bytes) -> dict:
    try:
        obj = json.loads(blob.decode("utf-8"), object_pairs_hook=_unique_keys)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise EvidenceRefused("invalid_manifest_json") from error
    if type(obj) is not dict or set(obj) != {
        "protocol", "m0h_commit", "test_module", "junit_sha256", "environment"
    }:
        raise EvidenceRefused("invalid_manifest_schema")
    if obj["protocol"] != PROTOCOL:
        raise EvidenceRefused("protocol_mismatch")
    if obj["m0h_commit"] != M0H_HEAD or obj["test_module"] != M0H_MODULE:
        raise EvidenceRefused("wrong_pinned_test_source")
    digest = obj["junit_sha256"]
    if (type(digest) is not str or len(digest) != 64
            or any(char not in "0123456789abcdef" for char in digest)):
        raise EvidenceRefused("invalid_digest")
    env = obj["environment"]
    if type(env) is not dict or set(env) != {
        "kind", "kernel_release", "filesystem", "scope_id", "userns_policy"
    }:
        raise EvidenceRefused("invalid_environment_schema")
    if env["kind"] not in ("disposable_vm", "owner_host"):
        raise EvidenceRefused("unsupported_environment_kind")
    for field in ("kernel_release", "filesystem", "scope_id", "userns_policy"):
        value = env[field]
        if (type(value) is not str or not 1 <= len(value) <= 128
                or any(ord(c) < 32 or ord(c) == 127 for c in value)):
            raise EvidenceRefused("invalid_environment_field")
    return obj


def _cases(blob: bytes) -> dict[str, str]:
    # ElementTree does not resolve network references. Explicitly reject
    # DTD and ENTITY declarations; this is data, never executable config.
    if b"<!DOCTYPE" in blob.upper() or b"<!ENTITY" in blob.upper():
        raise EvidenceRefused("xml_dtd_not_allowed")
    try:
        root = ET.fromstring(blob)
    except ET.ParseError as error:
        raise EvidenceRefused("invalid_junit_xml") from error
    if root.tag not in ("testsuites", "testsuite"):
        raise EvidenceRefused("wrong_junit_root")
    cases = root.findall(".//testcase")
    if len(cases) != len(EXPECTED_CASES):
        raise EvidenceRefused("wrong_case_count")
    seen: dict[str, str] = {}
    for case in cases:
        name = case.get("name")
        if (case.get("classname") != M0H_CLASS
                or name not in EXPECTED_CASES or name in seen):
            raise EvidenceRefused("unexpected_or_duplicate_case")
        states = [
            element.tag for element in case
            if element.tag in ("skipped", "failure", "error")
        ]
        if len(states) > 1:
            raise EvidenceRefused("conflicting_case_outcome")
        seen[name] = states[0] if states else "passed"
    if set(seen) != EXPECTED_CASES:
        raise EvidenceRefused("missing_required_case")
    return seen


def review(manifest_bytes: bytes, junit_bytes: bytes) -> Review:
    """Pure evidence triage; never return an operational GO."""
    if len(manifest_bytes) > MAX_FILE_BYTES or len(junit_bytes) > MAX_FILE_BYTES:
        return Review("QUARANTINE_ARTIFACT_TOO_LARGE")
    try:
        manifest = _manifest(manifest_bytes)
    except EvidenceRefused:
        return Review("QUARANTINE_MANIFEST")
    if hashlib.sha256(junit_bytes).hexdigest() != manifest["junit_sha256"]:
        return Review("QUARANTINE_JUNIT_DIGEST")
    try:
        cases = _cases(junit_bytes)
    except EvidenceRefused:
        return Review("QUARANTINE_JUNIT_CASES")
    passed = sum(status == "passed" for status in cases.values())
    skipped = sum(status == "skipped" for status in cases.values())
    failed = len(cases) - passed - skipped
    counts = dict(passed=passed, skipped=skipped, failed=failed)
    if failed:
        return Review("NO_GO_TEST_FAILURE_OR_ERROR", **counts)
    if any(cases[name] == "skipped" for name in KERNEL_CASES):
        return Review("NO_GO_KERNEL_CASES_SKIPPED", **counts)
    if skipped:
        return Review("NO_GO_INCOMPLETE_EVIDENCE", **counts)
    if manifest["environment"]["kind"] != "disposable_vm":
        return Review("NO_GO_HOST_NOT_ISOLATED_VM", **counts)
    # A digest plus self-reported provenance is still untrusted; even
    # observed kernel-view success does not constrain original aliases,
    # preopened fds, independent legacy writers or service restarts.
    return Review("LAB_REVIEW_ONLY", **counts)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Read-only M0h JUnit/manifest review; never grants migration."
    )
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--junit", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        output = review(_read_bounded(args.manifest), _read_bounded(args.junit))
    except (OSError, EvidenceRefused):
        output = Review("QUARANTINE_UNREADABLE_ARTIFACT")
    print(json.dumps(output.as_dict(), sort_keys=True))
    return 0 if output.decision == "LAB_REVIEW_ONLY" else 2


if __name__ == "__main__":
    sys.exit(main())
