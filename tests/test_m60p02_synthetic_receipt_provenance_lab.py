"""P02 structural-only provenance counterexamples for untrusted receipts."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3
import sys

import pytest


MODEL_PATH = Path(__file__).resolve().parents[1] / "scripts/p02_synthetic_receipt_provenance_lab.py"
SPEC = importlib.util.spec_from_file_location("p02_synthetic_receipt_provenance_lab", MODEL_PATH)
assert SPEC is not None and SPEC.loader is not None
m = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = m
SPEC.loader.exec_module(m)


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _packet() -> dict:
    verification = b'{"kind":"verification","epoch":1}\n'
    evidence = b'{"kind":"evidence","epoch":1}\n'
    return {
        "schema_kind": "projectctl.p02.synthetic_receipt",
        "schema_version": 1,
        "source_schema_version": 2,
        "source_origin": "UNATTESTED",
        "cross_store_epoch": "UNATTESTED",
        "issuer_auth": "ABSENT",
        "custody_protection": "UNVERIFIED",
        "issuer_claim_id": "claimed-producer",
        "project_id": "p02-project",
        "run_id": "p02-run",
        "task_id": "p02-task",
        "as_of_epoch": 1,
        "run_status": "ready_to_integrate",
        "event_prefix_id": 7,
        "receipt_sequence": 1,
        "leaves": [
            {"path": "verification-manifest.json",
             "byte_length": len(verification), "sha256": _sha(verification)},
            {"path": "evidence-manifest.json",
             "byte_length": len(evidence), "sha256": _sha(evidence)},
        ],
    }


def _encode(obj) -> bytes:
    return (json.dumps(obj, sort_keys=True, ensure_ascii=False,
                       allow_nan=False, separators=(",", ":")) + "\n").encode("utf-8")


def test_exact_receipt_is_structural_only_and_not_trusted():
    raw = _encode(_packet())
    assert m.inspect_untrusted_receipt(raw) == m.STRUCTURAL_ONLY
    assert m.STRUCTURAL_ONLY == "P02_SYNTHETIC_RECEIPT_STRUCTURAL_ONLY"
    assert "TRUSTED" not in m.STRUCTURAL_ONLY
    assert "ATTESTED" not in m.STRUCTURAL_ONLY


def test_replayed_byte_identical_receipt_is_still_only_structural():
    raw = _encode(_packet())
    assert m.inspect_untrusted_receipt(raw) == m.STRUCTURAL_ONLY
    assert m.inspect_untrusted_receipt(raw) == m.STRUCTURAL_ONLY
    # A stateless parser cannot detect replay: no anti-replay guarantee exists.


def test_self_declared_new_epoch_is_equally_unauthenticated():
    receipt = _packet()
    receipt["as_of_epoch"] = 2
    receipt["receipt_sequence"] = 2
    assert m.inspect_untrusted_receipt(_encode(receipt)) == m.STRUCTURAL_ONLY
    # No independently held high-water or current-source witness was queried.


def test_mixed_epoch_raw_leaf_hashes_remain_structurally_acceptable():
    receipt = _packet()
    newer = b'{"kind":"evidence","epoch":2}\n'
    receipt["leaves"][1]["byte_length"] = len(newer)
    receipt["leaves"][1]["sha256"] = _sha(newer)
    assert m.inspect_untrusted_receipt(_encode(receipt)) == m.STRUCTURAL_ONLY
    # This is the P01 gap: P02 deliberately lacks source bytes/source epoch.


def test_self_resigned_payload_is_still_unattested():
    receipt = _packet()
    receipt["leaves"][0]["sha256"] = "e" * 64
    assert m.inspect_untrusted_receipt(_encode(receipt)) == m.STRUCTURAL_ONLY


@pytest.mark.parametrize(("field", "value"), [
    ("source_origin", "PROVEN"),
    ("cross_store_epoch", "PROVEN"),
    ("issuer_auth", "SIGNED"),
    ("custody_protection", "IMMUTABLE"),
    ("run_status", "passed"),
    ("schema_kind", "projectctl.production.receipt"),
    ("schema_version", 2),
    ("schema_version", True),
    ("source_schema_version", 3),
    ("source_schema_version", True),
])
def test_promotion_or_non_pilot_scope_is_refused(field, value):
    receipt = _packet()
    receipt[field] = value
    assert m.inspect_untrusted_receipt(_encode(receipt)) == m.REFUSE_SCOPE


@pytest.mark.parametrize("field", [
    "trusted", "signature", "signature_verified",
    "publisher_authorized", "source_epoch_proven", "current",
    "real_source_path", "private_key", "source_snapshot_proven",
])
def test_extra_authority_fields_cannot_be_smuggled(field):
    receipt = _packet()
    receipt[field] = True
    assert m.inspect_untrusted_receipt(_encode(receipt)) == m.REFUSE_FIELDS


@pytest.mark.parametrize("field", [
    "project_id", "run_id", "task_id", "issuer_claim_id",
    "leaves", "as_of_epoch", "receipt_sequence", "event_prefix_id",
])
def test_required_field_absent_fails(field):
    receipt = _packet()
    receipt.pop(field)
    assert m.inspect_untrusted_receipt(_encode(receipt)) == m.REFUSE_FIELDS


@pytest.mark.parametrize("field", ["project_id", "run_id", "task_id", "issuer_claim_id"])
@pytest.mark.parametrize("bad", [
    "", ".", "..", " bad", "bad ", "a/b", "a\\b", "a\nb",
    "a\x00b", "شناسه", "a" * 129, 4, None, True, [],
])
def test_invalid_ids_refused(field, bad):
    receipt = _packet()
    receipt[field] = bad
    assert m.inspect_untrusted_receipt(_encode(receipt)) == m.REFUSE_FIELDS


@pytest.mark.parametrize("field", ["as_of_epoch", "receipt_sequence", "event_prefix_id"])
@pytest.mark.parametrize("bad", [0, -1, True, False, 1.0, "1", None, [], 1 << 63])
def test_invalid_numbers_refused(field, bad):
    receipt = _packet()
    receipt[field] = bad
    assert m.inspect_untrusted_receipt(_encode(receipt)) == m.REFUSE_FIELDS


@pytest.mark.parametrize("bad", [[], {}, None, True, "two", [1], [1, 2, 3]])
def test_wrong_leaf_collection_refused(bad):
    receipt = _packet()
    receipt["leaves"] = bad
    assert m.inspect_untrusted_receipt(_encode(receipt)) == m.REFUSE_FIELDS


@pytest.mark.parametrize("kind", ["missing", "extra", "wrong_path", "swap", "bad_size",
                                  "bad_digest", "uppercase_digest", "symlink_path"])
def test_invalid_leaf_contract_refused(kind):
    receipt = _packet()
    leaves = receipt["leaves"]
    if kind == "missing":
        leaves[0].pop("byte_length")
    elif kind == "extra":
        leaves[0]["issuer_auth"] = "SIGNED"
    elif kind == "wrong_path":
        leaves[0]["path"] = "worker-result.json"
    elif kind == "swap":
        leaves[:] = list(reversed(leaves))
    elif kind == "bad_size":
        leaves[0]["byte_length"] = True
    elif kind == "bad_digest":
        leaves[0]["sha256"] = "0" * 63
    elif kind == "uppercase_digest":
        leaves[0]["sha256"] = "A" * 64
    else:
        leaves[0]["path"] = "../verification-manifest.json"
    assert m.inspect_untrusted_receipt(_encode(receipt)) == m.REFUSE_FIELDS


@pytest.mark.parametrize("raw", [
    b"", b"trailing", b"\xff",
    b"{", b"[" * 2048, b" " * 4097, None, "text", bytearray(b"{}"),
    b'{"a":NaN}', b'{"a":Infinity}', b'\xef\xbb\xbf{}',
])
def test_invalid_json_or_unbounded_bytes_refused(raw):
    assert m.inspect_untrusted_receipt(raw) == m.REFUSE_FORMAT


@pytest.mark.parametrize("raw", [b"{}", b"[]", b"null", b"1"])
def test_valid_json_but_invalid_receipt_shape_refused(raw):
    assert m.inspect_untrusted_receipt(raw) == m.REFUSE_FIELDS


def test_duplicate_keys_top_level_and_nested_and_escaped_alias_refused():
    raw = _encode(_packet())
    assert b'"schema_kind":' in raw
    top = raw.replace(b'"schema_kind":', b'"schema_kind":"projectctl.p02.synthetic_receipt","schema_kind":', 1)
    assert m.inspect_untrusted_receipt(top) == m.REFUSE_FORMAT
    nested = raw.replace(b'"path":', b'"pa\\u0074h":"verification-manifest.json","path":', 1)
    assert m.inspect_untrusted_receipt(nested) == m.REFUSE_FORMAT


def test_noncanonical_but_valid_json_refused():
    receipt = _packet()
    raw = json.dumps(receipt, indent=2).encode("utf-8")
    assert m.inspect_untrusted_receipt(raw) == m.REFUSE_NONCANONICAL
    assert m.inspect_untrusted_receipt(_encode(receipt).rstrip(b"\n")) == m.REFUSE_NONCANONICAL


def test_no_projectctl_source_or_sqlite_io(monkeypatch):
    raw = _encode(_packet())

    def forbidden(*_args, **_kwargs):
        raise AssertionError("pure P02 contract must not read a source")

    monkeypatch.setattr(Path, "open", forbidden)
    monkeypatch.setattr(sqlite3, "connect", forbidden)
    assert m.inspect_untrusted_receipt(raw) == m.STRUCTURAL_ONLY


def test_module_cannot_import_runtime_or_signer():
    source = MODEL_PATH.read_text(encoding="utf-8")
    for forbidden in ("from projectctl", "import projectctl", "sqlite3",
                      "subprocess", "cryptography", "socket", "Path("):
        assert forbidden not in source
