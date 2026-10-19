"""M6.0 P2: synthetic-only receipt claims and negative identity/replay matrix.

No signing key, verifier trust anchor, source SQLite, file reads or CLI.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from scripts.bdiag_synthetic_receipt_lab import (
    ReceiptLabObservation, SyntheticReceiptRefusal,
    canonical_receipt_bytes, inspect_synthetic_receipt,
)


_SECRET = "PRIVATE_SECRET_MUST_NOT_APPEAR_IN_RECEIPT_RESULT"


def _payload():
    run = "run-bdiag-receipt"
    return {
        "schema_kind": "projectctl.bdiag.synthetic_receipt",
        "schema_version": 1,
        "domain": "projectctl.m6.0.bdiag.p2.synthetic-only.v1",
        "issuer_claim": "lab-issuer-1",
        "key_id_claim": "lab-key-1",
        "signature_state": "UNVERIFIED_NO_SIGNATURE",
        "receipt_id": "a" * 32,
        "issue_sequence": 7,
        "package_id": "b" * 32,
        "project_id": "lab-project-1",
        "run_id": run,
        "task_id": "lab-task-1",
        "source_db_schema_version": 2,
        "asof_status": "ready_to_integrate",
        "event_prefix_id": 41,
        "seal_sequence": 3,
        "seal_sha256": "c" * 64,
        "capture_method": "UNATTESTED_SYNTHETIC",
        "source_epoch_state": "UNATTESTED",
        "custody_state": "UNPROTECTED",
        "retention_policy": "UNSPECIFIED_TEST_ONLY",
        "artifact_bindings": [
            {
                "path": ".projectctl/runs/" + run + "/evidence-manifest.json",
                "size": 220,
                "sha256": "d" * 64,
            },
            {
                "path": ".projectctl/runs/" + run + "/verification-manifest.json",
                "size": 320,
                "sha256": "e" * 64,
            },
            {
                "path": ".projectctl/state.sqlite",
                "size": 4096,
                "sha256": "f" * 64,
            },
        ],
    }


def _expected(payload=None):
    x = _payload() if payload is None else payload
    keys = (
        "issuer_claim", "key_id_claim", "package_id", "project_id",
        "run_id", "task_id", "seal_sha256", "event_prefix_id", "seal_sequence",
    )
    return {key: x[key] for key in keys}


def _check(payload=None, *, expected=None, **kwargs):
    p = _payload() if payload is None else payload
    return inspect_synthetic_receipt(
        canonical_receipt_bytes(p),
        expected_claims=_expected(p) if expected is None else expected,
        **kwargs,
    )


def _must_refuse(payload, *, expected=None, **kwargs):
    with pytest.raises(SyntheticReceiptRefusal) as exc:
        _check(payload, expected=_expected() if expected is None else expected, **kwargs)
    assert str(exc.value) == "SYNTHETIC_RECEIPT_REFUSED"
    assert _SECRET not in str(exc.value)


def test_canonical_roundtrip_and_all_authority_flags_remain_false():
    p = _payload()
    first = _check(p)
    reordered = dict(reversed(list(p.items())))
    assert canonical_receipt_bytes(reordered) == canonical_receipt_bytes(p)
    assert _check(reordered) == first
    assert first.decision == "NO_GO_P2_SYNTHETIC_RECEIPT_ONLY"
    assert first.declared_identity_matches_test_context is True
    assert first.caller_supplied_replay_checks_passed is True
    assert not any((
        first.issuer_authenticated, first.source_origin_proven,
        first.cross_store_epoch_proven, first.custody_proven,
        first.durable_replay_prevention_proven,
        first.authorizes_collector_or_cli,
        first.authorizes_live_wal_reader,
        first.authorizes_writer_seal, first.authorizes_migration,
    ))
    assert len(first.receipt_sha256) == 64
    assert _SECRET not in repr(first)
    assert b"/private" not in canonical_receipt_bytes(p)


def test_claimed_issuer_and_self_supplied_expected_context_can_be_forged():
    forged = _payload()
    forged["issuer_claim"] = "attacker-issuer"
    forged["key_id_claim"] = "attacker-key"
    forged["package_id"] = "8" * 32
    forged["seal_sha256"] = "0" * 64
    # A matching caller-provided context is NOT an independent trust anchor.
    candidate = _check(forged, expected=_expected(forged))
    assert candidate.issuer_authenticated is False
    assert candidate.source_origin_proven is False
    assert candidate.cross_store_epoch_proven is False
    assert candidate.custody_proven is False
    # The *original* expected context still rejects it.
    _must_refuse(forged)


@pytest.mark.parametrize(("field", "bad"), [
    ("schema_kind", "projectctl.verification_as_of_seal"),
    ("schema_version", 2),
    ("schema_version", True),
    ("schema_version", 1.0),
    ("domain", "projectctl.m6.0.live-v1"),
    ("signature_state", "VERIFIED"),
    ("signature_state", "SIGNED_BY_ISSUER"),
    ("capture_method", "WAL_NATIVE_APPROVED"),
    ("source_epoch_state", "PROVEN"),
    ("custody_state", "IMMUTABLE"),
    ("retention_policy", "FOREVER"),
    ("source_db_schema_version", 3),
    ("source_db_schema_version", True),
    ("asof_status", "passed"),
    ("asof_status", "verifying"),
    ("receipt_id", "x" * 32),
    ("receipt_id", "a" * 31),
    ("package_id", "A" * 32),
    ("seal_sha256", "A" * 64),
    ("seal_sha256", "0" * 63),
    ("issue_sequence", 0),
    ("issue_sequence", True),
    ("issue_sequence", 1 << 63),
    ("event_prefix_id", 0),
    ("event_prefix_id", False),
    ("seal_sequence", -1),
    ("seal_sequence", "3"),
    ("issuer_claim", " ../other "),
    ("key_id_claim", " lab-key-1 "),
    ("project_id", "new/project"),
    ("run_id", "other-run"),
    ("task_id", "wrong-task"),
])
def test_closed_schema_types_and_individual_identity_or_version_tamper(field, bad):
    p = _payload()
    p[field] = bad
    _must_refuse(p)


@pytest.mark.parametrize("field", [
    "issuer_claim", "key_id_claim", "package_id", "project_id",
    "run_id", "task_id", "seal_sha256", "event_prefix_id", "seal_sequence",
])
def test_expected_context_mismatch_is_refused_even_with_valid_shape(field):
    p = _payload()
    expected = _expected(p)
    if field in ("event_prefix_id", "seal_sequence"):
        expected[field] += 1
    elif field in ("package_id",):
        expected[field] = "0" * 32
    elif field == "seal_sha256":
        expected[field] = "1" * 64
    else:
        expected[field] = "different"
    _must_refuse(p, expected=expected)


@pytest.mark.parametrize("change", [
    "remove_field", "inject_trusted", "inject_signature", "inject_private",
    "unordered_artifacts", "duplicate_artifact", "foreign_artifact",
    "path_traversal", "incorrect_size", "bool_size", "oversized_db",
    "invalid_digest", "extra_artifact_property", "missing_artifact_property",
])
def test_exact_artifact_allowlist_and_no_authority_extra_fields(change):
    p = _payload()
    if change == "remove_field":
        del p["domain"]
    elif change == "inject_trusted":
        p["issuer_authenticated"] = True
    elif change == "inject_signature":
        p["signature"] = "fake-trusted"
    elif change == "inject_private":
        p["prompt"] = _SECRET
    elif change == "unordered_artifacts":
        p["artifact_bindings"].reverse()
    elif change == "duplicate_artifact":
        p["artifact_bindings"][0] = copy.deepcopy(p["artifact_bindings"][1])
    elif change == "foreign_artifact":
        p["artifact_bindings"][0]["path"] = "/tmp/other.sqlite"
    elif change == "path_traversal":
        p["artifact_bindings"][0]["path"] = "../../secret"
    elif change == "incorrect_size":
        p["artifact_bindings"][0]["size"] = 0
    elif change == "bool_size":
        p["artifact_bindings"][0]["size"] = True
    elif change == "oversized_db":
        p["artifact_bindings"][2]["size"] = 16 * 1024 * 1024 + 1
    elif change == "invalid_digest":
        p["artifact_bindings"][0]["sha256"] = "g" * 64
    elif change == "extra_artifact_property":
        p["artifact_bindings"][0]["proof"] = "yes"
    else:
        del p["artifact_bindings"][0]["sha256"]
    _must_refuse(p)


@pytest.mark.parametrize("raw", [
    b"", b"not-json", b"[]", b"{}", b"null",
    b"\xff", b'{"a":NaN}', b'{"a":1e309}',
    b" " + canonical_receipt_bytes(_payload()),
    canonical_receipt_bytes(_payload()).rstrip(b"\n"),
    b" " * 4097,
])
def test_malformed_noncanonical_oversized_and_nonfinite_bytes_refused(raw):
    with pytest.raises(SyntheticReceiptRefusal):
        inspect_synthetic_receipt(raw, expected_claims=_expected())


def test_escaped_duplicate_key_even_when_same_value_is_refused():
    raw = canonical_receipt_bytes(_payload())
    # Two JSON spellings of one exact key: parser must not choose the last.
    replaced = raw.replace(
        b'"project_id":"lab-project-1",',
        b'"project_id":"lab-project-1","pro\\u006aect_id":"lab-project-1",',
    )
    assert replaced != raw
    with pytest.raises(SyntheticReceiptRefusal):
        inspect_synthetic_receipt(replaced, expected_claims=_expected())


def test_caller_supplied_replay_and_revocation_checks_are_only_negative_gates():
    p = _payload()
    _must_refuse(p, seen_receipt_ids=frozenset({p["receipt_id"]}))
    _must_refuse(p, seen_package_ids=frozenset({p["package_id"]}))
    _must_refuse(p, revoked_claimed_issuers=frozenset({p["issuer_claim"]}))
    _must_refuse(p, last_seen_sequence=7)
    _must_refuse(p, last_seen_sequence=8)
    assert _check(p, last_seen_sequence=6).durable_replay_prevention_proven is False


def test_restart_with_empty_caller_history_allows_replay_but_never_certifies_it():
    raw = canonical_receipt_bytes(_payload())
    a = inspect_synthetic_receipt(raw, expected_claims=_expected())
    b = inspect_synthetic_receipt(raw, expected_claims=_expected())
    assert a == b  # No durable stored issuance registry exists.
    assert a.durable_replay_prevention_proven is False
    assert a.decision == "NO_GO_P2_SYNTHETIC_RECEIPT_ONLY"


@pytest.mark.parametrize(("keyword", "bad"), [
    ("seen_receipt_ids", set()),
    ("seen_package_ids", ["a" * 32]),
    ("revoked_claimed_issuers", {}),
    ("last_seen_sequence", True),
    ("last_seen_sequence", -1),
    ("last_seen_sequence", 1 << 63),
])
def test_untrusted_history_arguments_fail_closed(keyword, bad):
    with pytest.raises(SyntheticReceiptRefusal):
        _check(**{keyword: bad})


def test_claim_type_changes_cannot_hide_behind_python_boolean_integer_equality():
    expected = _expected()
    expected["event_prefix_id"] = True
    _must_refuse(_payload(), expected=expected)


def test_report_cannot_promote_proof_status_after_parse():
    baseline = _check()
    fields = baseline.__dict__.copy()
    for key in ("issuer_authenticated", "source_origin_proven",
                "cross_store_epoch_proven", "custody_proven",
                "durable_replay_prevention_proven",
                "authorizes_collector_or_cli", "authorizes_live_wal_reader",
                "authorizes_writer_seal", "authorizes_migration"):
        candidate = dict(fields)
        candidate[key] = True
        with pytest.raises(ValueError, match="AUTHORITY_CLAIM_FORBIDDEN"):
            ReceiptLabObservation(**candidate)


def test_pure_lab_does_not_access_project_files_or_build_a_real_signer():
    import scripts.bdiag_synthetic_receipt_lab as lab
    source = Path(lab.__file__).read_text(encoding="utf-8")
    for forbidden in ("sqlite3", "os.open(", "subprocess", "private_key",
                      "ed25519", "hmac", "cryptography", "verify_signature",
                      "projectctl.cli", "RunStore", "os.replace(", "chmod("):
        assert forbidden not in source
    from projectctl.storage.sqlite import PROJECT_STATE_DB_VERSION
    assert PROJECT_STATE_DB_VERSION == 2
    from projectctl.cli import entry
    assert not hasattr(entry, "register_trace_export")
