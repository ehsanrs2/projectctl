"""M6.0 P2c: PURE synthetic prepare/commit/ack/restart fault-state model.

This code simulates atomicity inside immutable Python values only. It neither
persists nor recovers any real data, reads ProjectCTL sources, authenticates
an issuer, emits a public receipt, nor authorizes an operational action.
Caller-supplied 'committed' values/checksums are NOT custody proof.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Literal

from scripts.bdiag_p2b_issuer_replay_lab import (
    LabChecksumAnchor, LabIssuerPolicy, LabReplayCheckpoint, P2bRefusal,
    lab_anchor, model_receipt_admission, new_lab_checkpoint,
)

_HEX32 = re.compile(r"[0-9a-f]{32}\Z", re.ASCII)
_HEX64 = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)
_MAX_INT = (1 << 63) - 1
_DECISION = "NO_GO_P2C_FAULT_STATE_MODEL_ONLY"
_STATUS = (
    "UNAVAILABLE_REFUSE",
    "MISSING_INTENT_REFUSE",
    "PRECOMMIT_IN_SUPPLIED_MODEL",
    "COMMIT_VISIBLE_ACK_UNKNOWN",
    "COMMIT_VISIBLE_ACK_CLAIMED",
    "ACK_WITHOUT_COMMIT_QUARANTINE",
    "ACK_MISMATCH_QUARANTINE",
    "AMBIGUOUS_QUARANTINE",
)


class P2cRefusal(ValueError):
    """Fixed non-sensitive refusal; input content never in error message."""


def _refuse() -> None:
    raise P2cRefusal("P2C_MODEL_REFUSED")


def _hex32(value: object) -> bool:
    return type(value) is str and bool(_HEX32.fullmatch(value))


def _hex64(value: object) -> bool:
    return type(value) is str and bool(_HEX64.fullmatch(value))


def _positive(value: object, *, zero: bool = False) -> bool:
    return type(value) is int and (0 if zero else 1) <= value <= _MAX_INT


@dataclass(frozen=True)
class LabCommitRecord:
    """Claimed last commit only; a same-UID caller can forge this entirely."""

    commit_id: str
    receipt_sha256: str
    receipt_id: str
    package_id: str
    issue_sequence: int
    revision: int

    def __post_init__(self) -> None:
        if not (_hex64(self.commit_id) and _hex64(self.receipt_sha256)
                and _hex32(self.receipt_id) and _hex32(self.package_id)
                and _positive(self.issue_sequence) and _positive(self.revision)):
            raise ValueError("INVALID_P2C_COMMIT")


@dataclass(frozen=True)
class LabSlot:
    """A hypothetical all-or-nothing cell, NOT an on-disk atomic store."""

    policy: LabIssuerPolicy
    checkpoint: LabReplayCheckpoint
    anchor: LabChecksumAnchor
    last_commit: LabCommitRecord | None = None

    def __post_init__(self) -> None:
        if (type(self.policy) is not LabIssuerPolicy
                or type(self.checkpoint) is not LabReplayCheckpoint
                or type(self.anchor) is not LabChecksumAnchor
                or self.policy.policy_epoch != self.checkpoint.policy_epoch
                or lab_anchor(self.policy, self.checkpoint) != self.anchor):
            raise ValueError("INVALID_P2C_SLOT")
        c = self.last_commit
        if c is None:
            if self.checkpoint.revision != 0:
                raise ValueError("INVALID_P2C_SLOT")
        elif (type(c) is not LabCommitRecord
              or c.revision != self.checkpoint.revision
              or c.issue_sequence != self.checkpoint.last_sequence
              or c.receipt_id not in self.checkpoint.seen_receipt_ids
              or c.package_id not in self.checkpoint.seen_package_ids):
            raise ValueError("INVALID_P2C_SLOT")


@dataclass(frozen=True)
class LabIntent:
    """In-memory prepare result. Computing it commits and acknowledges nothing."""

    policy: LabIssuerPolicy
    before: LabReplayCheckpoint
    before_anchor: LabChecksumAnchor
    after: LabReplayCheckpoint
    after_anchor: LabChecksumAnchor
    receipt_sha256: str
    receipt_id: str
    package_id: str
    issue_sequence: int

    def __post_init__(self) -> None:
        if (type(self.policy) is not LabIssuerPolicy
                or type(self.before) is not LabReplayCheckpoint
                or type(self.after) is not LabReplayCheckpoint
                or type(self.before_anchor) is not LabChecksumAnchor
                or type(self.after_anchor) is not LabChecksumAnchor
                or not _hex64(self.receipt_sha256)
                or not _hex32(self.receipt_id)
                or not _hex32(self.package_id)
                or not _positive(self.issue_sequence)):
            raise ValueError("INVALID_P2C_INTENT")


@dataclass(frozen=True)
class LabAck:
    """Hypothetical in-memory response bytes, not delivery evidence."""

    commit_id: str
    receipt_sha256: str
    revision: int
    decision: Literal["NO_GO_P2C_SIMULATED_ACK_ONLY"] = (
        "NO_GO_P2C_SIMULATED_ACK_ONLY"
    )

    def __post_init__(self) -> None:
        if (not _hex64(self.commit_id) or not _hex64(self.receipt_sha256)
                or not _positive(self.revision)
                or self.decision != "NO_GO_P2C_SIMULATED_ACK_ONLY"):
            raise ValueError("INVALID_P2C_ACK")


@dataclass(frozen=True)
class LabRecovery:
    """A bounded observation, never advice that it is safe to reissue."""

    decision: str
    observed_phase: str
    commit_claim_matches_intent: bool = False
    safe_to_retry_without_external_reconciliation: bool = False
    issuer_authenticated: bool = False
    source_origin_proven: bool = False
    cross_store_epoch_proven: bool = False
    commit_durable_proven: bool = False
    acknowledgement_delivered_proven: bool = False
    independent_anchor_proven: bool = False
    durable_replay_prevention_proven: bool = False
    custody_proven: bool = False
    authorizes_collector_or_cli: bool = False
    authorizes_live_wal_reader: bool = False
    authorizes_writer_seal: bool = False
    authorizes_migration: bool = False

    def __post_init__(self) -> None:
        if (self.decision != _DECISION or self.observed_phase not in _STATUS
                or type(self.commit_claim_matches_intent) is not bool
                or (self.commit_claim_matches_intent is True and
                    self.observed_phase not in (
                        "COMMIT_VISIBLE_ACK_UNKNOWN",
                        "COMMIT_VISIBLE_ACK_CLAIMED",
                    ))
                or any((
                    self.safe_to_retry_without_external_reconciliation,
                    self.issuer_authenticated, self.source_origin_proven,
                    self.cross_store_epoch_proven, self.commit_durable_proven,
                    self.acknowledgement_delivered_proven,
                    self.independent_anchor_proven,
                    self.durable_replay_prevention_proven,
                    self.custody_proven, self.authorizes_collector_or_cli,
                    self.authorizes_live_wal_reader,
                    self.authorizes_writer_seal, self.authorizes_migration,
                ))):
            raise ValueError("P2C_AUTHORITY_CLAIM_FORBIDDEN")


def empty_lab_slot(policy: LabIssuerPolicy) -> LabSlot:
    if type(policy) is not LabIssuerPolicy:
        _refuse()
    cp = new_lab_checkpoint(policy)
    return LabSlot(policy, cp, lab_anchor(policy, cp))


def prepare_lab(
    raw_receipt: bytes, *,
    expected_claims: dict[str, object], slot: LabSlot,
) -> LabIntent:
    """Pure PREPARE: validate P2b claims and return an uncommitted candidate."""
    if type(slot) is not LabSlot:
        _refuse()
    try:
        candidate, next_cp, next_anchor = model_receipt_admission(
            raw_receipt,
            expected_claims=expected_claims,
            policy=slot.policy,
            checkpoint=slot.checkpoint,
            expected_anchor=slot.anchor,
        )
        # The P2b decoder already rejected duplicate/noncanonical JSON.
        values = json.loads(raw_receipt)
        return LabIntent(
            policy=slot.policy,
            before=slot.checkpoint, before_anchor=slot.anchor,
            after=next_cp, after_anchor=next_anchor,
            receipt_sha256=candidate.receipt_sha256,
            receipt_id=values["receipt_id"], package_id=values["package_id"],
            issue_sequence=values["issue_sequence"],
        )
    except (P2bRefusal, TypeError, ValueError, KeyError, RecursionError):
        _refuse()


def _record(intent: LabIntent) -> LabCommitRecord:
    identity = {
        "domain": "projectctl.m6.0.p2c.memory-only-commit-v1",
        "policy_epoch": intent.policy.policy_epoch,
        "base_revision": intent.before.revision,
        "base_anchor_sha256": intent.before_anchor.checkpoint_sha256,
        "after_anchor_sha256": intent.after_anchor.checkpoint_sha256,
        "receipt_sha256": intent.receipt_sha256,
        "receipt_id": intent.receipt_id,
        "package_id": intent.package_id,
        "issue_sequence": intent.issue_sequence,
    }
    raw = json.dumps(identity, sort_keys=True, separators=(",", ":"),
                     ensure_ascii=True, allow_nan=False).encode("ascii")
    return LabCommitRecord(
        commit_id=hashlib.sha256(raw).hexdigest(),
        receipt_sha256=intent.receipt_sha256,
        receipt_id=intent.receipt_id, package_id=intent.package_id,
        issue_sequence=intent.issue_sequence, revision=intent.after.revision,
    )


def commit_lab(slot: LabSlot, intent: LabIntent) -> LabSlot:
    """Pure hypothetical CAS: returns a new value, NEVER a durable commit."""
    if type(slot) is not LabSlot or type(intent) is not LabIntent:
        _refuse()
    if (slot.policy != intent.policy
            or slot.checkpoint != intent.before
            or slot.anchor != intent.before_anchor
            or slot.checkpoint.revision >= 512
            or intent.after.policy_epoch != intent.policy.policy_epoch
            or intent.after.revision != intent.before.revision + 1
            or intent.after.last_sequence != intent.issue_sequence
            or intent.after.seen_receipt_ids != (
                intent.before.seen_receipt_ids | {intent.receipt_id}
            )
            or intent.after.seen_package_ids != (
                intent.before.seen_package_ids | {intent.package_id}
            )
            or lab_anchor(intent.policy, intent.after) != intent.after_anchor):
        _refuse()
    return LabSlot(
        policy=slot.policy, checkpoint=intent.after,
        anchor=intent.after_anchor, last_commit=_record(intent),
    )


def acknowledge_lab(slot: LabSlot, intent: LabIntent) -> LabAck:
    """Model ACK only if supplied slot has matching last commit record."""
    if (type(slot) is not LabSlot or type(intent) is not LabIntent
            or slot.last_commit is None or slot.policy != intent.policy
            or slot.last_commit != _record(intent)
            or slot.checkpoint != intent.after
            or slot.anchor != intent.after_anchor):
        _refuse()
    return LabAck(
        commit_id=slot.last_commit.commit_id,
        receipt_sha256=slot.last_commit.receipt_sha256,
        revision=slot.last_commit.revision,
    )


def restart_lab(
    observed_slot: LabSlot | None, *,
    original_intent: LabIntent | None,
    claimed_delivered_ack: LabAck | None = None,
) -> LabRecovery:
    """Classify *supplied* restart witness; cannot query durable custody.

    A lost/rolled-back slot is NOT automatically reinitialized. A forged old
    slot plus matching checksum can fool this model; PRECOMMIT is only an
    observation about caller data, not permission to replay or retry.
    """
    phase: str
    if type(observed_slot) is not LabSlot:
        phase = "UNAVAILABLE_REFUSE"
    elif type(original_intent) is not LabIntent:
        phase = "MISSING_INTENT_REFUSE"
    elif (type(claimed_delivered_ack) not in (LabAck, type(None))
          or observed_slot.policy != original_intent.policy):
        phase = "AMBIGUOUS_QUARANTINE"
    elif (observed_slot.checkpoint == original_intent.before
          and observed_slot.anchor == original_intent.before_anchor):
        phase = (
            "ACK_WITHOUT_COMMIT_QUARANTINE"
            if claimed_delivered_ack is not None
            else "PRECOMMIT_IN_SUPPLIED_MODEL"
        )
    elif (observed_slot.checkpoint == original_intent.after
          and observed_slot.anchor == original_intent.after_anchor
          and observed_slot.last_commit == _record(original_intent)):
        if claimed_delivered_ack is None:
            phase = "COMMIT_VISIBLE_ACK_UNKNOWN"
        elif claimed_delivered_ack == LabAck(
            commit_id=observed_slot.last_commit.commit_id,
            receipt_sha256=observed_slot.last_commit.receipt_sha256,
            revision=observed_slot.last_commit.revision,
        ):
            phase = "COMMIT_VISIBLE_ACK_CLAIMED"
        else:
            phase = "ACK_MISMATCH_QUARANTINE"
    else:
        phase = "AMBIGUOUS_QUARANTINE"
    return LabRecovery(
        decision=_DECISION,
        observed_phase=phase,
        commit_claim_matches_intent=phase in (
            "COMMIT_VISIBLE_ACK_UNKNOWN", "COMMIT_VISIBLE_ACK_CLAIMED",
        ),
    )
