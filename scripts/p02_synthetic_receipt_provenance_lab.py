"""P02: pure, import-only, structurally untrusted synthetic receipt parser.

This deliberately cannot establish producer authentication, source identity,
source epoch, storage immutability, or replay resistance. No I/O, signing,
SQLite, WAL, network, or ProjectCTL runtime imports.
"""
from __future__ import annotations

import json
import re


MAX_RECEIPT_BYTES = 4096
STRUCTURAL_ONLY = "P02_SYNTHETIC_RECEIPT_STRUCTURAL_ONLY"
REFUSE_FORMAT = "P02_REFUSE_MALFORMED_RECEIPT"
REFUSE_NONCANONICAL = "P02_REFUSE_NONCANONICAL_RECEIPT"
REFUSE_SCOPE = "P02_REFUSE_UNSUPPORTED_SCOPE_OR_AUTHORITY"
REFUSE_FIELDS = "P02_REFUSE_INVALID_RECEIPT_FIELDS"

_SCHEMA_KIND = "projectctl.p02.synthetic_receipt"
_FIXED = {
    "schema_kind": _SCHEMA_KIND,
    "schema_version": 1,
    "source_schema_version": 2,
    "source_origin": "UNATTESTED",
    "cross_store_epoch": "UNATTESTED",
    "issuer_auth": "ABSENT",
    "custody_protection": "UNVERIFIED",
    "run_status": "ready_to_integrate",
}
_REQUIRED = frozenset(_FIXED) | {
    "issuer_claim_id", "project_id", "run_id", "task_id",
    "as_of_epoch", "event_prefix_id", "receipt_sequence", "leaves",
}
_LEAF_REQUIRED = frozenset({"path", "byte_length", "sha256"})
_LEAF_NAMES = ("verification-manifest.json", "evidence-manifest.json")
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", re.ASCII)
_SHA = re.compile(r"[0-9a-f]{64}", re.ASCII)


def _no_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise ValueError("duplicate key")
        obj[key] = value
    return obj


def _no_constants(_constant: str) -> object:
    raise ValueError("non-JSON constant")


def _int_between(value: object, lower: int, upper: int) -> bool:
    return type(value) is int and lower <= value <= upper


def _canonical_bytes(obj: object) -> bytes:
    return (json.dumps(obj, sort_keys=True, ensure_ascii=False,
                       allow_nan=False, separators=(",", ":")) + "\n").encode("utf-8")


def inspect_untrusted_receipt(raw: bytes) -> str:
    """Parse only a synthetic receipt. Structural success is never admission.

    This parser has no source bytes and cannot verify any claimed digest,
    issuer, old-writer exclusion, epoch, signature, custody, or freshness.
    The receipt producer can fabricate a newly canonical packet at will.
    """
    if type(raw) is not bytes or not (1 <= len(raw) <= MAX_RECEIPT_BYTES):
        return REFUSE_FORMAT
    try:
        obj = json.loads(raw.decode("utf-8"), object_pairs_hook=_no_duplicate_keys,
                         parse_constant=_no_constants)
    except (ValueError, RecursionError):
        return REFUSE_FORMAT
    if type(obj) is not dict or set(obj) != _REQUIRED:
        return REFUSE_FIELDS
    if any(type(obj[k]) is not type(expected) or obj[k] != expected
           for k, expected in _FIXED.items()):
        return REFUSE_SCOPE
    if any(type(obj[k]) is not str or not _ID.fullmatch(obj[k])
           for k in ("issuer_claim_id", "project_id", "run_id", "task_id")):
        return REFUSE_FIELDS
    if (not _int_between(obj["as_of_epoch"], 1, 1_000_000)
            or not _int_between(obj["event_prefix_id"], 1, (1 << 63) - 1)
            or not _int_between(obj["receipt_sequence"], 1, 1_000_000)):
        return REFUSE_FIELDS
    leaves = obj["leaves"]
    if type(leaves) is not list or len(leaves) != len(_LEAF_NAMES):
        return REFUSE_FIELDS
    for index, leaf in enumerate(leaves):
        if (type(leaf) is not dict or set(leaf) != _LEAF_REQUIRED
                or type(leaf["path"]) is not str
                or leaf["path"] != _LEAF_NAMES[index]
                or not _int_between(leaf["byte_length"], 1, 2048)
                or type(leaf["sha256"]) is not str
                or not _SHA.fullmatch(leaf["sha256"])):
            return REFUSE_FIELDS
    if raw != _canonical_bytes(obj):
        return REFUSE_NONCANONICAL
    return STRUCTURAL_ONLY
