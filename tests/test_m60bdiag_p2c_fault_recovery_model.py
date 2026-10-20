"""M6.0 P2c — purely in-memory crash and recovery fault-state tests.

All producer, issuer, WAL source, signature and custody authority is absent.
Tests inject hypothetical caller-supplied snapshots, NOT process kills/fsyncs.
"""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from scripts.bdiag_p2b_issuer_replay_lab import LabIssuerPolicy, lab_anchor
from scripts.bdiag_p2c_fault_state_lab import (
    LabAck, LabCommitRecord, LabRecovery, LabSlot, P2cRefusal,
    acknowledge_lab, commit_lab, empty_lab_slot, prepare_lab, restart_lab,
)
from scripts.bdiag_synthetic_receipt_lab import canonical_receipt_bytes

_SECRET = "PRIVATE_P2C_SECRET_DO_NOT_EMIT"


def _receipt(**updates):
    run = "run-bdiag-receipt"
    p = {
        "schema_kind": "projectctl.bdiag.synthetic_receipt",
        "schema_version": 1,
        "domain": "projectctl.m6.0.bdiag.p2.synthetic-only.v1",
        "issuer_claim": "synthetic-issuer-a",
        "key_id_claim": "synthetic-key-a",
        "signature_state": "UNVERIFIED_NO_SIGNATURE",
        "receipt_id": "a" * 32,
        "issue_sequence": 7,
        "package_id": "b" * 32,
        "project_id": "synthetic-project-a",
        "run_id": run,
        "task_id": "synthetic-task-a",
        "source_db_schema_version": 2,
        "asof_status": "ready_to_integrate",
        "event_prefix_id": 31,
        "seal_sequence": 2,
        "seal_sha256": "c" * 64,
        "capture_method": "UNATTESTED_SYNTHETIC",
        "source_epoch_state": "UNATTESTED",
        "custody_state": "UNPROTECTED",
        "retention_policy": "UNSPECIFIED_TEST_ONLY",
        "artifact_bindings": [
            {"path": ".projectctl/runs/" + run + "/evidence-manifest.json",
             "size": 80, "sha256": "d" * 64},
            {"path": ".projectctl/runs/" + run + "/verification-manifest.json",
             "size": 128, "sha256": "e" * 64},
            {"path": ".projectctl/state.sqlite",
             "size": 4096, "sha256": "f" * 64},
        ],
    }
    return {**p, **updates}


_EXPECTED = (
    "issuer_claim", "key_id_claim", "package_id", "project_id",
    "run_id", "task_id", "seal_sha256", "event_prefix_id", "seal_sequence",
)


def _expected(p=None):
    p = _receipt() if p is None else p
    return {k: p[k] for k in _EXPECTED}


def _policy():
    return LabIssuerPolicy(
        issuer_claim="synthetic-issuer-a",
        key_id_claim="synthetic-key-a", policy_epoch=4,
        key_generation=2,
    )


def _start(p=None, *, expected=None):
    p = _receipt() if p is None else p
    slot = empty_lab_slot(_policy())
    intent = prepare_lab(
        canonical_receipt_bytes(p),
        expected_claims=_expected() if expected is None else expected,
        slot=slot,
    )
    return slot, intent


def _assert_all_no_go(result):
    assert result.decision == "NO_GO_P2C_FAULT_STATE_MODEL_ONLY"
    for field in (
        "safe_to_retry_without_external_reconciliation",
        "issuer_authenticated", "source_origin_proven",
        "cross_store_epoch_proven", "commit_durable_proven",
        "acknowledgement_delivered_proven", "independent_anchor_proven",
        "durable_replay_prevention_proven", "custody_proven",
        "authorizes_collector_or_cli", "authorizes_live_wal_reader",
        "authorizes_writer_seal", "authorizes_migration",
    ):
        assert getattr(result, field) is False
    assert _SECRET not in repr(result)


def test_prepare_is_pure_repeatable_and_does_not_ack_or_commit():
    slot, intent = _start()
    again = prepare_lab(
        canonical_receipt_bytes(_receipt()),
        expected_claims=_expected(), slot=slot,
    )
    assert intent == again
    assert slot.checkpoint.revision == 0
    assert slot.last_commit is None
    assert intent.after.revision == 1
    assert intent.after.last_sequence == 7
    with pytest.raises(P2cRefusal):
        acknowledge_lab(slot, intent)


def test_commit_only_builds_new_value_and_ack_is_not_delivery():
    slot, intent = _start()
    new_slot = commit_lab(slot, intent)
    assert slot.checkpoint.revision == 0
    assert slot.last_commit is None
    assert new_slot.checkpoint.revision == 1
    assert new_slot.last_commit is not None
    assert new_slot.last_commit.receipt_sha256 == intent.receipt_sha256
    a = acknowledge_lab(new_slot, intent)
    assert a == acknowledge_lab(new_slot, intent)
    assert a.decision == "NO_GO_P2C_SIMULATED_ACK_ONLY"
    assert a.revision == 1
    assert new_slot.anchor == lab_anchor(new_slot.policy, new_slot.checkpoint)


@pytest.mark.parametrize(("cut", "expected_phase"), [
    ("before_prepare", "MISSING_INTENT_REFUSE"),
    ("after_prepare", "PRECOMMIT_IN_SUPPLIED_MODEL"),
    ("after_commit_before_ack", "COMMIT_VISIBLE_ACK_UNKNOWN"),
    ("after_ack_but_delivery_lost", "COMMIT_VISIBLE_ACK_UNKNOWN"),
    ("after_ack_with_caller_delivery_claim", "COMMIT_VISIBLE_ACK_CLAIMED"),
    ("slot_unavailable", "UNAVAILABLE_REFUSE"),
    ("intent_unavailable_after_commit", "MISSING_INTENT_REFUSE"),
])
def test_all_fault_cutpoints_are_non_authorizing(cut, expected_phase):
    old, intent = _start()
    fresh = commit_lab(old, intent)
    ack = acknowledge_lab(fresh, intent)
    if cut == "before_prepare":
        observation = restart_lab(old, original_intent=None)
    elif cut == "after_prepare":
        observation = restart_lab(old, original_intent=intent)
    elif cut in ("after_commit_before_ack", "after_ack_but_delivery_lost"):
        observation = restart_lab(fresh, original_intent=intent)
    elif cut == "after_ack_with_caller_delivery_claim":
        observation = restart_lab(
            fresh, original_intent=intent, claimed_delivered_ack=ack,
        )
    elif cut == "intent_unavailable_after_commit":
        observation = restart_lab(fresh, original_intent=None)
    else:
        observation = restart_lab(None, original_intent=intent)
    assert observation.observed_phase == expected_phase
    _assert_all_no_go(observation)


def test_lost_ack_requires_reconciliation_and_must_not_readmit():
    slot, intent = _start()
    committed = commit_lab(slot, intent)
    ack = acknowledge_lab(committed, intent)
    lost_ack = restart_lab(committed, original_intent=intent)
    assert lost_ack.observed_phase == "COMMIT_VISIBLE_ACK_UNKNOWN"
    _assert_all_no_go(lost_ack)
    assert ack.commit_id == committed.last_commit.commit_id
    with pytest.raises(P2cRefusal):
        prepare_lab(
            canonical_receipt_bytes(_receipt()),
            expected_claims=_expected(),
            slot=committed,
        )


def test_same_base_two_prepares_cannot_both_commit_if_new_slot_is_passed():
    old, first = _start()
    second = prepare_lab(
        canonical_receipt_bytes(_receipt(
            receipt_id="1" * 32, package_id="2" * 32,
            issue_sequence=8,
        )),
        expected_claims=_expected(_receipt(
            receipt_id="1" * 32, package_id="2" * 32,
            issue_sequence=8,
        )),
        slot=old,
    )
    assert first.before == second.before
    committed = commit_lab(old, first)
    with pytest.raises(P2cRefusal, match="P2C_MODEL_REFUSED"):
        commit_lab(committed, second)
    # An unchanged old slot can still produce another copy of a hypothetical
    # commit. This is NOT interprocess compare-and-swap or real exclusion.
    forked = commit_lab(old, second)
    assert forked.last_commit != committed.last_commit


@pytest.mark.parametrize("wrong", [
    "wrong_policy", "wrong_base_anchor", "wrong_revision",
    "wrong_sequence", "wrong_ids", "wrong_candidate_anchor",
])
def test_stale_or_forged_preparation_rejected_by_in_memory_cas(wrong):
    slot, intent = _start()
    if wrong == "wrong_policy":
        bad = replace(intent, policy=replace(intent.policy, key_generation=9))
    elif wrong == "wrong_base_anchor":
        bad = replace(
            intent, before_anchor=replace(
                intent.before_anchor, checkpoint_sha256="0" * 64,
            ),
        )
    elif wrong == "wrong_revision":
        bad = replace(
            intent, after=replace(intent.after, revision=2),
        )
    elif wrong == "wrong_sequence":
        bad = replace(intent, issue_sequence=8)
    elif wrong == "wrong_ids":
        bad = replace(intent, receipt_id="1" * 32)
    else:
        bad = replace(
            intent, after_anchor=replace(
                intent.after_anchor, checkpoint_sha256="0" * 64,
            ),
        )
    with pytest.raises(P2cRefusal):
        commit_lab(slot, bad)


def test_ack_before_commit_stale_ack_and_wrong_intent_rejected():
    slot, intent = _start()
    committed = commit_lab(slot, intent)
    for wrong_slot in (slot,):
        with pytest.raises(P2cRefusal):
            acknowledge_lab(wrong_slot, intent)
    with pytest.raises(P2cRefusal):
        acknowledge_lab(committed, replace(intent, receipt_id="1" * 32))
    with pytest.raises(P2cRefusal):
        acknowledge_lab(committed, replace(intent, receipt_sha256="0" * 64))


def test_ack_on_old_slot_is_never_treated_as_commit():
    old, intent = _start()
    committed = commit_lab(old, intent)
    caller_claim = acknowledge_lab(committed, intent)
    obs = restart_lab(old, original_intent=intent, claimed_delivered_ack=caller_claim)
    assert obs.observed_phase == "ACK_WITHOUT_COMMIT_QUARANTINE"
    _assert_all_no_go(obs)


@pytest.mark.parametrize("wrong", [
    "commit", "receipt", "revision",
])
def test_conflicting_ack_is_quarantined_instead_of_promoting_commit(wrong):
    old, intent = _start()
    committed = commit_lab(old, intent)
    good = acknowledge_lab(committed, intent)
    if wrong == "commit":
        bad = replace(good, commit_id="0" * 64)
    elif wrong == "receipt":
        bad = replace(good, receipt_sha256="0" * 64)
    else:
        bad = replace(good, revision=99)
    obs = restart_lab(committed, original_intent=intent, claimed_delivered_ack=bad)
    assert obs.observed_phase == "ACK_MISMATCH_QUARANTINE"
    _assert_all_no_go(obs)


def test_state_and_checksum_rollback_is_undetectable_without_external_witness():
    old, intent = _start()
    committed = commit_lab(old, intent)
    assert restart_lab(
        committed, original_intent=intent,
    ).observed_phase == "COMMIT_VISIBLE_ACK_UNKNOWN"
    # The same actor can roll back the whole supplied slot+checksum bundle.
    observed = restart_lab(old, original_intent=intent)
    assert observed.observed_phase == "PRECOMMIT_IN_SUPPLIED_MODEL"
    _assert_all_no_go(observed)
    # Thus the previous receipt can be prepared again against the old data;
    # this proves the missing independent rollback-resistant custodian.
    replay = prepare_lab(
        canonical_receipt_bytes(_receipt()),
        expected_claims=_expected(), slot=old,
    )
    assert replay == intent
    # If an outside caller *also* supplies its prior ack claim, the mismatch
    # becomes visible. No real trusted ack channel is implemented.
    caller_ack = acknowledge_lab(committed, intent)
    reported = restart_lab(
        old, original_intent=intent, claimed_delivered_ack=caller_ack,
    )
    assert reported.observed_phase == "ACK_WITHOUT_COMMIT_QUARANTINE"


def test_forged_committed_slot_with_recomputed_checksum_is_not_custody():
    old, intent = _start()
    real_candidate = commit_lab(old, intent)
    forged_record = replace(
        real_candidate.last_commit, commit_id="0" * 64,
    )
    forged = LabSlot(
        policy=old.policy,
        checkpoint=intent.after, anchor=lab_anchor(old.policy, intent.after),
        last_commit=forged_record,
    )
    obs = restart_lab(forged, original_intent=intent)
    assert obs.observed_phase == "AMBIGUOUS_QUARANTINE"
    _assert_all_no_go(obs)
    matching_untrusted = restart_lab(
        real_candidate, original_intent=intent,
    )
    assert matching_untrusted.commit_claim_matches_intent is True
    assert matching_untrusted.commit_durable_proven is False


def test_lost_final_record_in_model_value_is_invalid_even_if_checkpoint_exists():
    old, intent = _start()
    committed = commit_lab(old, intent)
    with pytest.raises(ValueError, match="INVALID_P2C_SLOT"):
        replace(committed, last_commit=None)
    # A missing or corrupt externally supplied recovery snapshot is
    # represented by unavailable, never silently bootstrapped as empty.
    obs = restart_lab(None, original_intent=intent)
    assert obs.observed_phase == "UNAVAILABLE_REFUSE"
    _assert_all_no_go(obs)


@pytest.mark.parametrize("source", [
    "old_unrelated", "new_unrelated", "ack_of_unrelated",
])
def test_restarted_commit_context_mismatch_must_quarantine(source):
    old, intent = _start()
    committed = commit_lab(old, intent)
    another = _receipt(
        receipt_id="1" * 32, package_id="2" * 32,
        issue_sequence=8,
    )
    different_intent = prepare_lab(
        canonical_receipt_bytes(another),
        expected_claims=_expected(another), slot=old,
    )
    if source == "old_unrelated":
        obs = restart_lab(old, original_intent=different_intent,
                          claimed_delivered_ack=acknowledge_lab(committed, intent))
        assert obs.observed_phase == "ACK_WITHOUT_COMMIT_QUARANTINE"
    elif source == "new_unrelated":
        obs = restart_lab(committed, original_intent=different_intent)
        assert obs.observed_phase == "AMBIGUOUS_QUARANTINE"
    else:
        obs = restart_lab(
            committed, original_intent=intent,
            claimed_delivered_ack=acknowledge_lab(
                commit_lab(old, different_intent), different_intent,
            ),
        )
        assert obs.observed_phase == "ACK_MISMATCH_QUARANTINE"
    _assert_all_no_go(obs)


@pytest.mark.parametrize("invalid", [True, None, 1, object()])
def test_invalid_observed_store_or_intent_does_not_reinitialize(invalid):
    old, intent = _start()
    phase = restart_lab(invalid, original_intent=intent).observed_phase
    assert phase == "UNAVAILABLE_REFUSE"
    obs = restart_lab(old, original_intent=invalid)
    assert obs.observed_phase == "MISSING_INTENT_REFUSE"


@pytest.mark.parametrize("phase", [
    "PRECOMMIT_IN_SUPPLIED_MODEL", "COMMIT_VISIBLE_ACK_UNKNOWN",
    "COMMIT_VISIBLE_ACK_CLAIMED", "UNAVAILABLE_REFUSE",
    "MISSING_INTENT_REFUSE", "ACK_WITHOUT_COMMIT_QUARANTINE",
    "ACK_MISMATCH_QUARANTINE", "AMBIGUOUS_QUARANTINE",
])
def test_no_status_can_claim_safety_or_cryptographic_proof(phase):
    result = LabRecovery(
        decision="NO_GO_P2C_FAULT_STATE_MODEL_ONLY", observed_phase=phase,
        commit_claim_matches_intent=phase in (
            "COMMIT_VISIBLE_ACK_UNKNOWN", "COMMIT_VISIBLE_ACK_CLAIMED",
        ),
    )
    _assert_all_no_go(result)


@pytest.mark.parametrize("field", [
    "safe_to_retry_without_external_reconciliation",
    "issuer_authenticated", "source_origin_proven",
    "cross_store_epoch_proven", "commit_durable_proven",
    "acknowledgement_delivered_proven", "independent_anchor_proven",
    "durable_replay_prevention_proven", "custody_proven",
    "authorizes_collector_or_cli", "authorizes_live_wal_reader",
    "authorizes_writer_seal", "authorizes_migration",
])
def test_result_invariant_prevents_any_authority_promotions(field):
    example = restart_lab(*_restart_args())
    kwargs = example.__dict__.copy()
    kwargs[field] = True
    with pytest.raises(ValueError, match="P2C_AUTHORITY_CLAIM_FORBIDDEN"):
        LabRecovery(**kwargs)


def _restart_args():
    old, intent = _start()
    return old, {"original_intent": intent}


def test_unknown_status_or_fake_commit_evidence_must_not_pass_contract():
    with pytest.raises(ValueError, match="P2C_AUTHORITY_CLAIM_FORBIDDEN"):
        LabRecovery(
            decision="NO_GO_P2C_FAULT_STATE_MODEL_ONLY",
            observed_phase="TRUSTED_COMMITTED",
        )
    with pytest.raises(ValueError, match="P2C_AUTHORITY_CLAIM_FORBIDDEN"):
        LabRecovery(
            decision="NO_GO_P2C_FAULT_STATE_MODEL_ONLY",
            observed_phase="PRECOMMIT_IN_SUPPLIED_MODEL",
            commit_claim_matches_intent=True,
        )
    with pytest.raises(ValueError, match="INVALID_P2C_COMMIT"):
        LabCommitRecord("invalid", "0" * 64, "0" * 32, "0" * 32, 1, 1)


def test_module_is_import_only_pure_model_and_db_version_stays_v2():
    import scripts.bdiag_p2c_fault_state_lab as p2c
    contents = Path(p2c.__file__).read_text(encoding="utf-8")
    for forbidden in (
        "sqlite3", "os.open(", "subprocess", "private_key",
        "ed25519", "hmac.new(", "cryptography", "systemctl ",
        "apparmor_parser", "RunStore", "projectctl.cli",
        "os.replace(", "os.chmod(", "os.setuid(", "fsync(",
    ):
        assert forbidden not in contents
    from projectctl.storage.sqlite import PROJECT_STATE_DB_VERSION
    assert PROJECT_STATE_DB_VERSION == 2
    from projectctl.cli import entry
    assert not hasattr(entry, "register_trace_export")
