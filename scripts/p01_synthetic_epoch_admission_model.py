"""M6.0 P01: in-memory falsification model for source/epoch admission.

Import-only disposable laboratory. The independent witness is a *test-supplied
oracle*, not a real authenticated source, Seal, reader, signer or P0/P1 proof.
No file, SQLite, WAL, network, or privileged operation exists in this module.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re


@dataclass(frozen=True)
class Capture:
    project_id: str
    run_id: str
    task_id: str
    source_schema_version: int
    db_epoch: int
    run_status: str
    event_prefix_id: int
    verification_epoch: int
    evidence_epoch: int
    verification_bytes: bytes
    evidence_bytes: bytes
    inventory_verification_sha256: str
    inventory_evidence_sha256: str
    # Attacker-supplied assertions are deliberately NOT consulted by the gate.
    caller_claims_epoch_proven: bool = False
    observation_claim: str = "as_of"


@dataclass(frozen=True)
class TestOracleWitness:
    """Only a separately constructed lab fixture; never pass caller claims here."""

    source_admitted: bool
    legacy_start_routes_excluded: bool
    preopened_writable_fds_excluded: bool
    source_epoch_observed: bool
    project_id: str
    run_id: str
    task_id: str
    source_schema_version: int
    epoch: int
    run_status: str
    event_prefix_id: int
    verification_sha256: str
    evidence_sha256: str
    # Separate hypothetical observation of latest state, required only for current.
    latest_epoch: int | None = None


REFUSE_NO_WITNESS = "REFUSE_P0_WITNESS_ABSENT"
REFUSE_ADMISSION = "REFUSE_P0_ADMISSION_UNPROVEN"
REFUSE_IDENTITY = "REFUSE_P0_IDENTITY_OR_SCHEMA"
REFUSE_INTEGRITY = "REFUSE_P1_INTERNAL_INTEGRITY"
REFUSE_EPOCH = "REFUSE_P1_MIXED_EPOCH"
REFUSE_CURRENT = "REFUSE_P1_CURRENT_UNPROVEN"
REFUSE_BOUNDARY = "REFUSE_P1_STATUS_OR_EVENT_BOUNDARY"
REFUSE_BYTES = "REFUSE_P1_UNWITNESSED_BYTES"
MODEL_ONLY = "SYNTHETIC_CONSISTENT_NOT_ATTESTED"

_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", re.ASCII)
_SHA256 = re.compile(r"[0-9a-f]{64}", re.ASCII)


def _valid_epoch(value: object) -> bool:
    return type(value) is int and 1 <= value <= 1_000_000


def _unique_fields(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate synthetic field")
        result[key] = value
    return result


def _reject_constant(_value: str) -> object:
    raise ValueError("non-JSON constant")


def _synthetic_epoch(raw: bytes, kind: str) -> int:
    # This exact two-field format belongs ONLY to this disposable fixture.
    # Real ProjectCTL manifests do not promise a direct epoch field.
    obj = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_fields,
                     parse_constant=_reject_constant)
    if (type(obj) is not dict or set(obj) != {"kind", "epoch"}
            or type(obj["kind"]) is not str or obj["kind"] != kind
            or not _valid_epoch(obj["epoch"])):
        raise ValueError("invalid synthetic artifact")
    return obj["epoch"]


def _digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def classify(capture: Capture, *, oracle: TestOracleWitness | None) -> str:
    """Compare hypothetical independent observations; never establish trust.

    All inputs are assembled in tests. Merely constructing oracle from the
    same caller's candidate would make its truth assumptions circular.
    """
    if oracle is None or not isinstance(oracle, TestOracleWitness):
        return REFUSE_NO_WITNESS
    if not isinstance(capture, Capture):
        return REFUSE_IDENTITY
    if not all((oracle.source_admitted is True,
                oracle.legacy_start_routes_excluded is True,
                oracle.preopened_writable_fds_excluded is True,
                oracle.source_epoch_observed is True)):
        return REFUSE_ADMISSION

    identities = (capture.project_id, capture.run_id, capture.task_id)
    reference = (oracle.project_id, oracle.run_id, oracle.task_id)
    if (identities != reference
            or any(type(x) is not str or not _IDENTIFIER.fullmatch(x)
                   for x in identities + reference)
            or type(capture.source_schema_version) is not int
            or capture.source_schema_version != 2
            or type(oracle.source_schema_version) is not int
            or oracle.source_schema_version != 2):
        return REFUSE_IDENTITY

    fields = ((capture.verification_bytes, capture.inventory_verification_sha256),
              (capture.evidence_bytes, capture.inventory_evidence_sha256))
    if any(type(data) is not bytes or not data or len(data) > 2048
           or type(digest) is not str or digest != _digest(data)
           for data, digest in fields):
        return REFUSE_INTEGRITY
    if any(type(digest) is not str or not _SHA256.fullmatch(digest)
           for digest in (oracle.verification_sha256, oracle.evidence_sha256)):
        return REFUSE_INTEGRITY
    try:
        json_epochs = (_synthetic_epoch(capture.verification_bytes, "verification"),
                       _synthetic_epoch(capture.evidence_bytes, "evidence"))
    except (ValueError, RecursionError):
        return REFUSE_INTEGRITY

    epochs = (capture.db_epoch, capture.verification_epoch,
              capture.evidence_epoch, oracle.epoch) + json_epochs
    if any(not _valid_epoch(x) for x in epochs) or len(set(epochs)) != 1:
        return REFUSE_EPOCH

    if (type(capture.observation_claim) is not str
            or capture.observation_claim not in ("as_of", "current")
            or (oracle.latest_epoch is not None
                and (not _valid_epoch(oracle.latest_epoch)
                     or oracle.latest_epoch < oracle.epoch))
            or (capture.observation_claim == "current"
                and oracle.latest_epoch != capture.db_epoch)):
        return REFUSE_CURRENT

    if (type(capture.run_status) is not str or capture.run_status != "ready_to_integrate"
            or type(oracle.run_status) is not str or oracle.run_status != "ready_to_integrate"
            or type(capture.event_prefix_id) is not int
            or type(oracle.event_prefix_id) is not int
            or not (1 <= capture.event_prefix_id <= (1 << 63) - 1)
            or capture.event_prefix_id != oracle.event_prefix_id):
        return REFUSE_BOUNDARY

    if (capture.inventory_verification_sha256 != oracle.verification_sha256
            or capture.inventory_evidence_sha256 != oracle.evidence_sha256):
        return REFUSE_BYTES
    return MODEL_ONLY
