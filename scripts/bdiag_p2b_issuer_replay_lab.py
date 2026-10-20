"""M6.0 P2b: PURE synthetic issuer-allowlist and replay-checkpoint model.

This module deliberately authenticates NOTHING. The policy and checksum
anchor are ordinary caller-supplied objects; anyone may forge both.
No issuer signature, key, filesystem, SQLite, durable registry or CLI exists.
A successful model transition grants NO operational ProjectCTL authority.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass

from scripts.bdiag_synthetic_receipt_lab import (
    SyntheticReceiptRefusal,
    inspect_synthetic_receipt,
)

_MAX_INTEGER = (1 << 63) - 1
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z", re.ASCII)
_NONCE = re.compile(r"[0-9a-f]{32}\Z", re.ASCII)
_SHA256 = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)
_FAILURE = "P2B_SIMULATED_ADMISSION_REFUSED"
_DECISION = "NO_GO_P2B_ISSUER_REPLAY_MODEL_ONLY"


class P2bRefusal(ValueError):
    """Fixed nonsensitive reason; no untrusted input reflected in errors."""


def _refuse() -> None:
    raise P2bRefusal(_FAILURE)


def _identifier(value: object) -> bool:
    return type(value) is str and bool(_ID.fullmatch(value))


def _integer(value: object, *, allow_zero: bool = False) -> bool:
    return (type(value) is int and (0 if allow_zero else 1) <= value
            <= _MAX_INTEGER)


def _nonce(value: object) -> bool:
    return type(value) is str and bool(_NONCE.fullmatch(value))


def _sha(value: object) -> bool:
    return type(value) is str and bool(_SHA256.fullmatch(value))


def _safe_set(value: object) -> bool:
    return (type(value) is frozenset
            and len(value) <= 512 and all(_nonce(x) for x in value))


@dataclass(frozen=True)
class LabIssuerPolicy:
    """Claim allowlist injected by a test harness; NOT a verified trust root."""

    issuer_claim: str
    key_id_claim: str
    policy_epoch: int
    key_generation: int
    revoked: bool = False

    def __post_init__(self) -> None:
        if not (_identifier(self.issuer_claim)
                and _identifier(self.key_id_claim)
                and _integer(self.policy_epoch)
                and _integer(self.key_generation)
                and type(self.revoked) is bool):
            raise ValueError("INVALID_SYNTHETIC_POLICY")


@dataclass(frozen=True)
class LabReplayCheckpoint:
    """Memory-only sample; neither stored durably nor protected independently."""

    policy_epoch: int
    revision: int
    last_sequence: int
    seen_receipt_ids: frozenset[str]
    seen_package_ids: frozenset[str]

    def __post_init__(self) -> None:
        if not (_integer(self.policy_epoch)
                and _integer(self.revision, allow_zero=True)
                and _integer(self.last_sequence, allow_zero=True)
                and _safe_set(self.seen_receipt_ids)
                and _safe_set(self.seen_package_ids)
                and len(self.seen_receipt_ids) == len(self.seen_package_ids)
                and len(self.seen_receipt_ids) == self.revision):
            raise ValueError("INVALID_SYNTHETIC_CHECKPOINT")


@dataclass(frozen=True)
class LabChecksumAnchor:
    """SHA digests of caller-supplied model state, NOT custody authentication."""

    policy_sha256: str
    checkpoint_sha256: str

    def __post_init__(self) -> None:
        if not (_sha(self.policy_sha256) and _sha(self.checkpoint_sha256)):
            raise ValueError("INVALID_SYNTHETIC_ANCHOR")


@dataclass(frozen=True)
class P2bTransition:
    """Only a model candidate, never a publication/verification decision."""

    decision: str
    receipt_sha256: str
    claimed_issuer_in_test_allowlist: bool
    replay_filter_cleared_in_simulation: bool
    issuer_authenticated: bool = False
    source_origin_proven: bool = False
    cross_store_epoch_proven: bool = False
    independent_anchor_proven: bool = False
    durable_replay_prevention_proven: bool = False
    custody_proven: bool = False
    authorizes_collector_or_cli: bool = False
    authorizes_live_wal_reader: bool = False
    authorizes_writer_seal: bool = False
    authorizes_migration: bool = False

    def __post_init__(self) -> None:
        if (self.decision != _DECISION
                or self.claimed_issuer_in_test_allowlist is not True
                or self.replay_filter_cleared_in_simulation is not True
                or not _sha(self.receipt_sha256)
                or any((
                    self.issuer_authenticated, self.source_origin_proven,
                    self.cross_store_epoch_proven, self.independent_anchor_proven,
                    self.durable_replay_prevention_proven, self.custody_proven,
                    self.authorizes_collector_or_cli,
                    self.authorizes_live_wal_reader,
                    self.authorizes_writer_seal, self.authorizes_migration,
                ))):
            raise ValueError("P2B_AUTHORITY_CLAIM_FORBIDDEN")


def new_lab_checkpoint(policy: LabIssuerPolicy) -> LabReplayCheckpoint:
    if type(policy) is not LabIssuerPolicy:
        _refuse()
    return LabReplayCheckpoint(
        policy_epoch=policy.policy_epoch,
        revision=0,
        last_sequence=0,
        seen_receipt_ids=frozenset(),
        seen_package_ids=frozenset(),
    )


def _digest(value: dict[str, object]) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"),
                     ensure_ascii=True, allow_nan=False).encode("ascii")
    return hashlib.sha256(raw).hexdigest()


def lab_anchor(
    policy: LabIssuerPolicy, checkpoint: LabReplayCheckpoint,
) -> LabChecksumAnchor:
    """Public SHA binding; anyone can re-create this pair for forged inputs."""
    if type(policy) is not LabIssuerPolicy or type(checkpoint) is not LabReplayCheckpoint:
        _refuse()
    return LabChecksumAnchor(
        policy_sha256=_digest({
            "issuer": policy.issuer_claim,
            "key": policy.key_id_claim,
            "policy_epoch": policy.policy_epoch,
            "key_generation": policy.key_generation,
            "revoked": policy.revoked,
        }),
        checkpoint_sha256=_digest({
            "policy_epoch": checkpoint.policy_epoch,
            "revision": checkpoint.revision,
            "last_sequence": checkpoint.last_sequence,
            "receipts": sorted(checkpoint.seen_receipt_ids),
            "packages": sorted(checkpoint.seen_package_ids),
        }),
    )


def model_receipt_admission(
    raw: bytes,
    *,
    expected_claims: dict[str, object],
    policy: LabIssuerPolicy,
    checkpoint: LabReplayCheckpoint,
    expected_anchor: LabChecksumAnchor,
) -> tuple[P2bTransition, LabReplayCheckpoint, LabChecksumAnchor]:
    """Return a SIMULATED candidate and next state; never commit/acknowledge.

    Caller supplies both state and anchor. Unknown/missing/changed anchor
    refuses, but a forged state together with its recomputed anchor is still
    undetectable: the caller is NOT an independent custody authority.

    A caller may store/lose the returned objects outside this pure module;
    such an action is not a durable authenticated transaction.
    """
    if (type(policy) is not LabIssuerPolicy
            or type(checkpoint) is not LabReplayCheckpoint
            or type(expected_anchor) is not LabChecksumAnchor
            or type(expected_claims) is not dict
            or checkpoint.policy_epoch != policy.policy_epoch
            or checkpoint.revision == 512
            or lab_anchor(policy, checkpoint) != expected_anchor
            or policy.revoked):
        _refuse()
    try:
        # P2 parser provides shape/canonical checks and a deliberately
        # *caller supplied* negative replay filter, NOT a real signature.
        structural = inspect_synthetic_receipt(
            raw,
            expected_claims=expected_claims,
            seen_receipt_ids=checkpoint.seen_receipt_ids,
            seen_package_ids=checkpoint.seen_package_ids,
            revoked_claimed_issuers=(
                frozenset({policy.issuer_claim}) if policy.revoked
                else frozenset()
            ),
            last_seen_sequence=checkpoint.last_sequence,
        )
        receipt = json.loads(raw)
    except (SyntheticReceiptRefusal, TypeError, ValueError, RecursionError):
        _refuse()
    if (receipt["issuer_claim"] != policy.issuer_claim
            or receipt["key_id_claim"] != policy.key_id_claim
            or not _nonce(receipt["receipt_id"])
            or not _nonce(receipt["package_id"])
            or not _integer(receipt["issue_sequence"])
            or receipt["issue_sequence"] <= checkpoint.last_sequence):
        _refuse()
    next_checkpoint = LabReplayCheckpoint(
        policy_epoch=policy.policy_epoch,
        revision=checkpoint.revision + 1,
        last_sequence=receipt["issue_sequence"],
        seen_receipt_ids=checkpoint.seen_receipt_ids | {receipt["receipt_id"]},
        seen_package_ids=checkpoint.seen_package_ids | {receipt["package_id"]},
    )
    observation = P2bTransition(
        decision=_DECISION,
        receipt_sha256=structural.receipt_sha256,
        claimed_issuer_in_test_allowlist=True,
        replay_filter_cleared_in_simulation=True,
    )
    return observation, next_checkpoint, lab_anchor(policy, next_checkpoint)
