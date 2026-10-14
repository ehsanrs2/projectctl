"""M6.0 B3a1 pure contract tests; no production DB migration or writer hooks."""
from __future__ import annotations

import hashlib
import json
import sqlite3

import pytest
from pydantic import ValidationError

from projectctl.trace.seal_contract import (
    VerificationAsOfSealV1,
    canonical_private_seal_json_bytes,
    private_seal_sha256,
    parse_private_seal_json_bytes,
    _InvalidSealJson,
)


def _payload(**overrides):
    data = {
        "schema_kind": "projectctl.verification_as_of_seal",
        "schema_version": 1,
        "seal_protocol_version": 1,
        "artifact_digest_algorithm": "sha256",
        "project_id": "projectctl",
        "run_id": "run-42",
        "task_id": "task-99",
        "seal_sequence": 1,
        "observed_status": "ready_to_integrate",
        "event_prefix_id": 183,
        "run_manifest_schema_version": 2,
        "run_manifest_raw_sha256": "a" * 64,
        "run_record_projection_sha256": "b" * 64,
        "verification_manifest_raw_sha256": "c" * 64,
        "evidence_manifest_raw_sha256": "d" * 64,
    }
    return {**data, **overrides}


def test_private_seal_v1_exact_roundtrip_and_fingerprint():
    seal = VerificationAsOfSealV1.model_validate(_payload())
    encoded = canonical_private_seal_json_bytes(seal)
    assert encoded.endswith(b"\n")
    assert encoded.count(b"\n") == 1
    assert encoded == (
        json.dumps(_payload(), sort_keys=True, ensure_ascii=False,
                   allow_nan=False, separators=(",", ":")) + "\n"
    ).encode()
    assert VerificationAsOfSealV1.model_validate_json(encoded) == seal
    assert parse_private_seal_json_bytes(encoded) == seal
    assert private_seal_sha256(seal) == hashlib.sha256(encoded).hexdigest()


def test_fingerprint_and_serialization_ignore_mapping_insertion_order():
    first = _payload()
    second = dict(reversed(list(first.items())))
    a = VerificationAsOfSealV1.model_validate(first)
    b = VerificationAsOfSealV1.model_validate(second)
    assert canonical_private_seal_json_bytes(a) == canonical_private_seal_json_bytes(b)
    assert private_seal_sha256(a) == private_seal_sha256(b)


@pytest.mark.parametrize(("field", "bad"), [
    ("schema_kind", "projectctl.worker_result"),
    ("schema_version", 2),
    ("schema_version", True),
    ("seal_protocol_version", 2),
    ("seal_protocol_version", True),
    ("artifact_digest_algorithm", "sha1"),
    ("observed_status", "passed"),
    ("observed_status", "verifying"),
    ("run_manifest_schema_version", 1),
    ("run_manifest_schema_version", 3),
])
def test_schema_scope_and_historical_versions_are_closed(field, bad):
    with pytest.raises(ValidationError):
        VerificationAsOfSealV1.model_validate(_payload(**{field: bad}))


@pytest.mark.parametrize("field", ["project_id", "run_id", "task_id"])
@pytest.mark.parametrize("bad", [
    " run-42 ", "run/42", "run\\42", "../run", "run\n42",
    "é", "", "x" * 129, 23, None,
])
def test_raw_identity_never_authorized_by_string_normalization(field, bad):
    with pytest.raises(ValidationError):
        VerificationAsOfSealV1.model_validate(_payload(**{field: bad}))


@pytest.mark.parametrize("field", [
    "run_manifest_raw_sha256",
    "run_record_projection_sha256",
    "verification_manifest_raw_sha256",
    "evidence_manifest_raw_sha256",
])
@pytest.mark.parametrize("bad", [
    "A" * 64, "a" * 63, "a" * 65, " " + "a" * 64,
    "a" * 64 + " ", "g" * 64, 9, None,
])
def test_raw_sha256_requires_lowercase_exact_64_hex_bytes(field, bad):
    with pytest.raises(ValidationError):
        VerificationAsOfSealV1.model_validate(_payload(**{field: bad}))


@pytest.mark.parametrize("field", ["seal_sequence", "event_prefix_id"])
@pytest.mark.parametrize("bad", [0, -1, True, "1", 1.0, (1 << 63), None])
def test_monotonic_sqlite_ids_require_positive_strict_64bit_int(field, bad):
    with pytest.raises(ValidationError):
        VerificationAsOfSealV1.model_validate(_payload(**{field: bad}))


def test_unknown_public_or_authority_fields_cannot_be_smuggled_into_seal():
    for field in ("raw_event_payload", "worker_prompt", "provider_token",
                  "review_url", "delivery_complete", "verified"):
        with pytest.raises(ValidationError):
            VerificationAsOfSealV1.model_validate(_payload(**{field: "SECRET_CANARY"}))


def test_missing_essential_digest_or_identity_fails():
    for field in ("project_id", "run_id", "task_id", "event_prefix_id",
                  "evidence_manifest_raw_sha256"):
        data = _payload()
        data.pop(field)
        with pytest.raises(ValidationError):
            VerificationAsOfSealV1.model_validate(data)


def test_boundary_identity_128_ascii_chars_is_allowed():
    seal = VerificationAsOfSealV1.model_validate(
        _payload(run_id="r" + "x" * 127)
    )
    assert len(seal.run_id) == 128


def test_seal_digest_is_not_semantic_provenance_or_authentication():
    a = VerificationAsOfSealV1.model_validate(_payload())
    b = VerificationAsOfSealV1.model_validate(
        _payload(evidence_manifest_raw_sha256="e" * 64)
    )
    assert private_seal_sha256(a) != private_seal_sha256(b)
    # The model cannot access source bytes, so neither accepted digest is
    # independently proven here. That remains a separate trusted writer gate.


def test_pure_contract_does_not_open_sqlite_or_files(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("private contract must not perform I/O")

    monkeypatch.setattr(sqlite3, "connect", forbidden)
    seal = VerificationAsOfSealV1.model_validate(_payload())
    assert len(canonical_private_seal_json_bytes(seal)) < 2048
    assert len(private_seal_sha256(seal)) == 64


@pytest.mark.parametrize("field", [
    "schema_kind", "schema_version", "seal_protocol_version",
    "observed_status", "run_manifest_schema_version",
    "artifact_digest_algorithm",
])
def test_missing_discriminator_must_fail_closed(field):
    data = _payload()
    data.pop(field)
    with pytest.raises(ValidationError):
        VerificationAsOfSealV1.model_validate(data)


def test_no_schema_file_hashing_or_worker_execution_dependencies():
    # Defensive contract boundary: this module remains pure, no imports of
    # mutable RunStore, writers or a filesystem-based collector.
    from projectctl.trace import seal_contract
    source = seal_contract.__dict__
    assert "sqlite3" not in source
    assert "subprocess" not in source
    assert "RunStore" not in source
    assert "read_run_artifact" not in source


@pytest.mark.parametrize("raw", [
    b"",
    b"not-json",
    b"[]",
    b"null",
    b'{"schema_kind":"projectctl.verification_as_of_seal",'
    b'"schema_kind":"projectctl.verification_as_of_seal"}',
    b'{"x": NaN}',
    b'{"x": Infinity}',
    b" " * 4097,
])
def test_strict_private_seal_parser_rejects_malformed_ambiguous_or_large_bytes(raw):
    with pytest.raises(_InvalidSealJson):
        parse_private_seal_json_bytes(raw)


def test_strict_decoder_rejects_escaped_duplicate_key_even_if_values_equal():
    raw = canonical_private_seal_json_bytes(
        VerificationAsOfSealV1.model_validate(_payload())
    ).rstrip(b"\n")
    tampered = raw[:-1] + b',"\\u0072un_id":"run-42"}'
    with pytest.raises(_InvalidSealJson):
        parse_private_seal_json_bytes(tampered)


def test_parser_roundtrip_preserves_exact_private_digest_data():
    model = VerificationAsOfSealV1.model_validate(_payload())
    encoded = canonical_private_seal_json_bytes(model)
    assert parse_private_seal_json_bytes(encoded) == model
    assert len(encoded) < 4096


@pytest.mark.parametrize("wrong", [None, "", "{}", 123, [], b"x" * 4097])
def test_parser_wrong_input_type_and_bounded_size_refused(wrong):
    with pytest.raises(_InvalidSealJson):
        parse_private_seal_json_bytes(wrong)
