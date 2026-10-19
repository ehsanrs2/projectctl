"""M6.0 B-Diagnostic P2 — PURE synthetic receipt *claim* validation lab.

No cryptographic signature, trust anchor, source reads, SQL connection,
producer, custody service, persistent replay log, Collector or public CLI.
Successful parsing NEVER authenticates the claimed issuer or source epoch.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Mapping

_MAX_RECEIPT_BYTES = 4096
_MAX_INTEGER = (1 << 63) - 1
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z", re.ASCII)
_SHA = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)
_NONCE = re.compile(r"[0-9a-f]{32}\Z", re.ASCII)
_DOMAIN = "projectctl.m6.0.bdiag.p2.synthetic-only.v1"
_RUN = "run-bdiag-receipt"
_PATH_LIMITS = {
    ".projectctl/state.sqlite": 16 * 1024 * 1024,
    ".projectctl/runs/" + _RUN + "/evidence-manifest.json": 2 * 1024 * 1024,
    ".projectctl/runs/" + _RUN + "/verification-manifest.json": 2 * 1024 * 1024,
}
_PATHS = tuple(sorted(_PATH_LIMITS))
_FIELD_NAMES = frozenset({
    "schema_kind", "schema_version", "domain", "issuer_claim",
    "key_id_claim", "signature_state", "receipt_id", "issue_sequence",
    "package_id", "project_id", "run_id", "task_id",
    "source_db_schema_version", "asof_status", "event_prefix_id",
    "seal_sequence", "seal_sha256", "capture_method",
    "source_epoch_state", "custody_state", "retention_policy",
    "artifact_bindings",
})
_CONTEXT_FIELDS = frozenset({
    "issuer_claim", "key_id_claim", "package_id",
    "project_id", "run_id", "task_id", "seal_sha256",
    "event_prefix_id", "seal_sequence",
})


class SyntheticReceiptRefusal(ValueError):
    """Error code only: no raw receipt, claimed issuer or secret in error."""


def _refuse() -> None:
    raise SyntheticReceiptRefusal("SYNTHETIC_RECEIPT_REFUSED")


def _unique_fields(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            _refuse()
        result[key] = value
    return result


def _not_finite(_value: str) -> None:
    _refuse()


def canonical_receipt_bytes(payload: dict[str, object]) -> bytes:
    """Pure deterministic encoding; caller-supplied fields are NOT signed."""
    return (json.dumps(payload, sort_keys=True, separators=(",", ":"),
                       ensure_ascii=True, allow_nan=False) + "\n").encode("ascii")


def _identifier(value: object) -> bool:
    return type(value) is str and _ID.fullmatch(value) is not None


def _sha(value: object) -> bool:
    return type(value) is str and _SHA.fullmatch(value) is not None


def _nonce(value: object) -> bool:
    return type(value) is str and _NONCE.fullmatch(value) is not None


def _integer(value: object) -> bool:
    return type(value) is int and 1 <= value <= _MAX_INTEGER


def _validate_shape(p: dict[str, object]) -> None:
    if set(p) != _FIELD_NAMES:
        _refuse()
    if (p["schema_kind"] != "projectctl.bdiag.synthetic_receipt"
            or type(p["schema_version"]) is not int or p["schema_version"] != 1
            or p["domain"] != _DOMAIN
            or p["signature_state"] != "UNVERIFIED_NO_SIGNATURE"
            or p["capture_method"] != "UNATTESTED_SYNTHETIC"
            or p["source_epoch_state"] != "UNATTESTED"
            or p["custody_state"] != "UNPROTECTED"
            or p["retention_policy"] != "UNSPECIFIED_TEST_ONLY"
            or type(p["source_db_schema_version"]) is not int
            or p["source_db_schema_version"] != 2
            or p["asof_status"] != "ready_to_integrate"):
        _refuse()
    for key in ("issuer_claim", "key_id_claim", "project_id", "run_id", "task_id"):
        if not _identifier(p[key]):
            _refuse()
    if p["run_id"] != _RUN:
        _refuse()
    if not (_nonce(p["receipt_id"]) and _nonce(p["package_id"])
            and _sha(p["seal_sha256"])):
        _refuse()
    for key in ("issue_sequence", "event_prefix_id", "seal_sequence"):
        if not _integer(p[key]):
            _refuse()
    bindings = p["artifact_bindings"]
    if type(bindings) is not list or len(bindings) != len(_PATHS):
        _refuse()
    for entry, expected_path in zip(bindings, _PATHS):
        if type(entry) is not dict or set(entry) != {"path", "size", "sha256"}:
            _refuse()
        if (entry["path"] != expected_path or not _sha(entry["sha256"])
                or not _integer(entry["size"])
                or entry["size"] > _PATH_LIMITS[expected_path]):
            _refuse()


@dataclass(frozen=True)
class ReceiptLabObservation:
    """Structural matching only; the proof/authority flags MUST stay False."""

    decision: str
    receipt_sha256: str
    declared_identity_matches_test_context: bool
    caller_supplied_replay_checks_passed: bool
    issuer_authenticated: bool = False
    source_origin_proven: bool = False
    cross_store_epoch_proven: bool = False
    custody_proven: bool = False
    durable_replay_prevention_proven: bool = False
    authorizes_collector_or_cli: bool = False
    authorizes_live_wal_reader: bool = False
    authorizes_writer_seal: bool = False
    authorizes_migration: bool = False

    def __post_init__(self) -> None:
        if (self.decision != "NO_GO_P2_SYNTHETIC_RECEIPT_ONLY"
                or self.declared_identity_matches_test_context is not True
                or self.caller_supplied_replay_checks_passed is not True
                or any((
                    self.issuer_authenticated, self.source_origin_proven,
                    self.cross_store_epoch_proven, self.custody_proven,
                    self.durable_replay_prevention_proven,
                    self.authorizes_collector_or_cli,
                    self.authorizes_live_wal_reader,
                    self.authorizes_writer_seal, self.authorizes_migration,
                ))):
            raise ValueError("AUTHORITY_CLAIM_FORBIDDEN")


def inspect_synthetic_receipt(
    raw: bytes,
    *,
    expected_claims: Mapping[str, object],
    seen_receipt_ids: frozenset[str] = frozenset(),
    seen_package_ids: frozenset[str] = frozenset(),
    revoked_claimed_issuers: frozenset[str] = frozenset(),
    last_seen_sequence: int = 0,
) -> ReceiptLabObservation:
    """Pure offline syntax/claims check; external arguments are UNTRUSTED.

    Sets are caller-provided samples, not durable authorization/replay state.
    Even a passing receipt may be wholly forged with matching expected_claims.
    """
    if type(raw) is not bytes or not (0 < len(raw) <= _MAX_RECEIPT_BYTES):
        _refuse()
    if (type(expected_claims) is not dict or set(expected_claims) != _CONTEXT_FIELDS
            or type(seen_receipt_ids) is not frozenset
            or type(seen_package_ids) is not frozenset
            or type(revoked_claimed_issuers) is not frozenset
            or type(last_seen_sequence) is not int or last_seen_sequence < 0
            or last_seen_sequence > _MAX_INTEGER):
        _refuse()
    try:
        parsed = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_unique_fields, parse_constant=_not_finite,
            parse_float=lambda _v: _refuse(),
        )
        if type(parsed) is not dict:
            _refuse()
        _validate_shape(parsed)
        if canonical_receipt_bytes(parsed) != raw:
            _refuse()
    except SyntheticReceiptRefusal:
        raise
    except (TypeError, UnicodeError, ValueError, RecursionError, OverflowError):
        _refuse()
    for key in _CONTEXT_FIELDS:
        if parsed[key] != expected_claims[key] or type(parsed[key]) is not type(expected_claims[key]):
            _refuse()
    if (parsed["receipt_id"] in seen_receipt_ids
            or parsed["package_id"] in seen_package_ids
            or parsed["issuer_claim"] in revoked_claimed_issuers
            or parsed["issue_sequence"] <= last_seen_sequence):
        _refuse()
    return ReceiptLabObservation(
        decision="NO_GO_P2_SYNTHETIC_RECEIPT_ONLY",
        receipt_sha256=hashlib.sha256(raw).hexdigest(),
        declared_identity_matches_test_context=True,
        caller_supplied_replay_checks_passed=True,
    )
