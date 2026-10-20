"""M6.0 P2b pure policy and restart/replay negative model.

No live project, real issuer, key, signature, durable checkpoint or OS state.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from scripts.bdiag_p2b_issuer_replay_lab import (
    LabChecksumAnchor, LabIssuerPolicy, LabReplayCheckpoint,
    P2bRefusal, P2bTransition, lab_anchor,
    model_receipt_admission, new_lab_checkpoint,
)
from scripts.bdiag_synthetic_receipt_lab import canonical_receipt_bytes

_SECRET = "SECRET_NOT_FOR_MODEL_RESULT_001"


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
    p.update(updates)
    return p


_KEYS = (
    "issuer_claim", "key_id_claim", "package_id",
    "project_id", "run_id", "task_id", "seal_sha256",
    "event_prefix_id", "seal_sequence",
)


def _expected(receipt=None):
    p = _receipt() if receipt is None else receipt
    return {key: p[key] for key in _KEYS}


def _policy(**overrides):
    values = dict(issuer_claim="synthetic-issuer-a",
                  key_id_claim="synthetic-key-a",
                  policy_epoch=4, key_generation=2, revoked=False)
    values.update(overrides)
    return LabIssuerPolicy(**values)


def _run(p=None, *, expected=None, policy=None, checkpoint=None, anchor=None):
    p = _receipt() if p is None else p
    policy = _policy() if policy is None else policy
    checkpoint = new_lab_checkpoint(policy) if checkpoint is None else checkpoint
    anchor = lab_anchor(policy, checkpoint) if anchor is None else anchor
    return model_receipt_admission(
        canonical_receipt_bytes(p), expected_claims=(
            _expected() if expected is None else expected
        ), policy=policy, checkpoint=checkpoint, expected_anchor=anchor,
    )


def test_success_is_only_a_candidate_with_every_trust_flag_false():
    candidate, state, anchor = _run()
    assert candidate.decision == "NO_GO_P2B_ISSUER_REPLAY_MODEL_ONLY"
    assert candidate.claimed_issuer_in_test_allowlist is True
    assert candidate.replay_filter_cleared_in_simulation is True
    for flag in (
        "issuer_authenticated", "source_origin_proven",
        "cross_store_epoch_proven", "independent_anchor_proven",
        "durable_replay_prevention_proven", "custody_proven",
        "authorizes_collector_or_cli", "authorizes_live_wal_reader",
        "authorizes_writer_seal", "authorizes_migration",
    ):
        assert getattr(candidate, flag) is False
    assert state.revision == 1
    assert state.last_sequence == 7
    assert state.seen_receipt_ids == frozenset({"a" * 32})
    assert state.seen_package_ids == frozenset({"b" * 32})
    assert anchor == lab_anchor(_policy(), state)
    assert _SECRET not in repr(candidate)
    assert len(candidate.receipt_sha256) == 64


def test_restarting_with_unchanged_simulated_checkpoint_refuses_replay():
    p = _receipt()
    _candidate, recovered_state, recovered_anchor = _run(p)
    with pytest.raises(P2bRefusal, match="P2B_SIMULATED_ADMISSION_REFUSED"):
        _run(p, checkpoint=recovered_state, anchor=recovered_anchor)
    newer = _receipt(receipt_id="1" * 32, package_id="2" * 32,
                     issue_sequence=8)
    candidate, next_state, _ = _run(
        newer, expected=_expected(newer),
        checkpoint=recovered_state, anchor=recovered_anchor
    )
    assert candidate.durable_replay_prevention_proven is False
    assert next_state.revision == 2
    assert next_state.last_sequence == 8


def test_candidate_is_not_committed_until_external_state_advance():
    """Pure model does NOT mutate the original input checkpoint."""
    policy = _policy()
    old = new_lab_checkpoint(policy)
    anchor = lab_anchor(policy, old)
    first = _run(checkpoint=old, anchor=anchor)
    second = _run(checkpoint=old, anchor=anchor)
    assert first == second
    assert old.revision == 0
    assert first[0].durable_replay_prevention_proven is False


def test_rollback_of_both_unprotected_checkpoint_and_anchor_reaccepts():
    """This is precisely why checksum pairs are not independent custody."""
    policy = _policy()
    old = new_lab_checkpoint(policy)
    old_anchor = lab_anchor(policy, old)
    _candidate, committed_in_memory, newer_anchor = _run(
        policy=policy, checkpoint=old, anchor=old_anchor
    )
    with pytest.raises(P2bRefusal):
        _run(policy=policy, checkpoint=committed_in_memory, anchor=newer_anchor)
    forged_restart = _run(policy=policy, checkpoint=old, anchor=old_anchor)
    assert forged_restart[0].independent_anchor_proven is False
    assert forged_restart[0].durable_replay_prevention_proven is False


def test_lost_checkpoint_or_out_of_date_anchor_fails_closed():
    policy = _policy()
    first = new_lab_checkpoint(policy)
    original = lab_anchor(policy, first)
    _candidate, second, later = _run(
        policy=policy, checkpoint=first, anchor=original
    )
    with pytest.raises(P2bRefusal):
        _run(policy=policy, checkpoint=second, anchor=original)
    with pytest.raises(P2bRefusal):
        _run(policy=policy, checkpoint=first, anchor=later)
    # An unavailable recovery state is not silently initialized as empty.
    with pytest.raises(P2bRefusal):
        model_receipt_admission(
            canonical_receipt_bytes(_receipt()),
            expected_claims=_expected(), policy=policy,
            checkpoint=None, expected_anchor=later,
        )


@pytest.mark.parametrize("changes", [
    {"issuer_claim": "other-issuer"},
    {"key_id_claim": "other-key"},
    {"project_id": "other-project"},
    {"task_id": "other-task"},
    {"package_id": "8" * 32},
    {"seal_sha256": "0" * 64},
    {"event_prefix_id": 45},
    {"seal_sequence": 9},
])
def test_policy_or_fixed_expected_identity_mismatch_refused(changes):
    p = _receipt(**changes)
    # Independently supplied reference fixture stays unchanged; tampering
    # with the receipt cannot silently redefine expected context.
    with pytest.raises(P2bRefusal, match="P2B_SIMULATED_ADMISSION_REFUSED"):
        _run(p, expected=_expected())

def test_attacker_can_forge_both_issuer_policy_and_anchor_not_authenticity():
    forged = _receipt(issuer_claim="attacker-issuer",
                      key_id_claim="attacker-key",
                      package_id="8" * 32, seal_sha256="0" * 64)
    adversarial_policy = _policy(
        issuer_claim="attacker-issuer", key_id_claim="attacker-key",
        policy_epoch=99, key_generation=87,
    )
    checkpoint = new_lab_checkpoint(adversarial_policy)
    fake_anchor = lab_anchor(adversarial_policy, checkpoint)
    observation, _, _ = _run(
        forged, expected=_expected(forged), policy=adversarial_policy,
        checkpoint=checkpoint, anchor=fake_anchor,
    )
    assert observation.claimed_issuer_in_test_allowlist is True
    assert observation.issuer_authenticated is False
    assert observation.independent_anchor_proven is False


@pytest.mark.parametrize("changed_policy", [
    {"revoked": True}, {"policy_epoch": 5},
    {"key_generation": 3}, {"key_id_claim": "rotated-key"},
    {"issuer_claim": "another-issuer"},
])
def test_revocation_policy_rotation_and_generation_need_new_external_proof(changed_policy):
    old = _policy()
    checkpoint = new_lab_checkpoint(old)
    old_anchor = lab_anchor(old, checkpoint)
    new = _policy(**changed_policy)
    with pytest.raises(P2bRefusal):
        _run(policy=new, checkpoint=checkpoint, anchor=old_anchor)


def test_revoked_issuer_refused_even_with_matching_new_checksum_anchor():
    revoked = _policy(revoked=True, policy_epoch=5)
    state = new_lab_checkpoint(revoked)
    with pytest.raises(P2bRefusal):
        _run(policy=revoked, checkpoint=state, anchor=lab_anchor(revoked, state))


@pytest.mark.parametrize(("field", "value"), [
    ("receipt_id", "a" * 32),
    ("package_id", "b" * 32),
])
def test_duplicate_identifier_refused_after_state_transfer(field, value):
    _candidate, state, anchor = _run()
    next_receipt = _receipt(receipt_id="1" * 32,
                            package_id="2" * 32,
                            issue_sequence=9)
    next_receipt[field] = value
    with pytest.raises(P2bRefusal):
        _run(next_receipt, expected=_expected(next_receipt),
             checkpoint=state, anchor=anchor)


@pytest.mark.parametrize("sequence", [0, 6, 7])
def test_nonmonotonic_sequence_refused(sequence):
    _candidate, state, anchor = _run()
    newer = _receipt(receipt_id="1" * 32,
                     package_id="2" * 32, issue_sequence=sequence)
    with pytest.raises(P2bRefusal):
        _run(newer, expected=_expected(newer),
             checkpoint=state, anchor=anchor)


@pytest.mark.parametrize("changed", [
    {"signature_state": "VERIFIED"},
    {"source_epoch_state": "PROVEN"},
    {"custody_state": "IMMUTABLE"},
    {"capture_method": "REAL_SQLITE_WAL"},
    {"asof_status": "passed"},
    {"schema_version": 2},
    {"receipt_id": True},
])
def test_unapproved_p2_receipt_claims_cannot_gain_issuer_model_trust(changed):
    p = _receipt(**changed)
    with pytest.raises(P2bRefusal):
        _run(p)


def test_bad_raw_receipt_cannot_leak_content_or_allocate_authority():
    policy = _policy()
    state = new_lab_checkpoint(policy)
    malicious = ('{"secret":"' + _SECRET + '","secret":"x"}').encode()
    with pytest.raises(P2bRefusal) as exc:
        model_receipt_admission(
            malicious, expected_claims=_expected(),
            policy=policy, checkpoint=state,
            expected_anchor=lab_anchor(policy, state),
        )
    assert str(exc.value) == "P2B_SIMULATED_ADMISSION_REFUSED"
    assert _SECRET not in repr(exc.value)


@pytest.mark.parametrize(("field", "value"), [
    ("policy_epoch", True), ("policy_epoch", 0),
    ("key_generation", -1), ("issuer_claim", "other/issuer"),
    ("key_id_claim", " forged "), ("revoked", 1),
])
def test_malformed_policy_construction_refused(field, value):
    with pytest.raises(ValueError, match="INVALID_SYNTHETIC_POLICY"):
        _policy(**{field: value})


@pytest.mark.parametrize("changes", [
    {"revision": True},
    {"last_sequence": -1},
    {"seen_receipt_ids": frozenset({"invalid"})},
    {"seen_package_ids": frozenset({"invalid"})},
    {"revision": 1},
    {"seen_receipt_ids": frozenset({"a" * 32})},
    {"policy_epoch": 0},
])
def test_malformed_or_inconsistent_checkpoint_construction_refused(changes):
    values = dict(policy_epoch=4, revision=0, last_sequence=0,
                  seen_receipt_ids=frozenset(),
                  seen_package_ids=frozenset())
    values.update(changes)
    with pytest.raises(ValueError, match="INVALID_SYNTHETIC_CHECKPOINT"):
        LabReplayCheckpoint(**values)


@pytest.mark.parametrize("bad", ["x" * 64, "a" * 63, None, True])
def test_checksum_anchor_format_refused(bad):
    with pytest.raises(ValueError, match="INVALID_SYNTHETIC_ANCHOR"):
        LabChecksumAnchor(policy_sha256=bad, checkpoint_sha256="a" * 64)


def test_same_state_and_different_untrusted_policy_anchor_hashes():
    state = new_lab_checkpoint(_policy())
    different = _policy(key_generation=99)
    assert lab_anchor(_policy(), state) != lab_anchor(different, state)
    # This is SHA correlation only, not a cryptographic signature.


def test_synthetic_capacity_boundary_refuses_next_record():
    policy = _policy()
    state = LabReplayCheckpoint(
        policy_epoch=4, revision=512, last_sequence=512,
        seen_receipt_ids=frozenset(f"{i:032x}" for i in range(512)),
        seen_package_ids=frozenset(f"{i + 512:032x}" for i in range(512)),
    )
    with pytest.raises(P2bRefusal):
        candidate = _receipt(receipt_id="f" * 32, package_id="e" * 32,
                             issue_sequence=513)
        _run(
            candidate, expected=_expected(candidate),
            policy=policy, checkpoint=state, anchor=lab_anchor(policy, state),
        )


def test_forged_checkpoint_and_matching_checksum_still_has_no_custody():
    policy = _policy()
    state = LabReplayCheckpoint(
        policy_epoch=4, revision=1, last_sequence=1,
        seen_receipt_ids=frozenset({"0" * 32}),
        seen_package_ids=frozenset({"1" * 32}),
    )
    observation, _, _ = _run(
        checkpoint=state, anchor=lab_anchor(policy, state),
    )
    assert observation.custody_proven is False
    assert observation.independent_anchor_proven is False


def test_opaque_report_cannot_set_any_authority_flag_true():
    result, _, _ = _run()
    for name in (
        "issuer_authenticated", "source_origin_proven",
        "cross_store_epoch_proven", "independent_anchor_proven",
        "durable_replay_prevention_proven", "custody_proven",
        "authorizes_collector_or_cli", "authorizes_live_wal_reader",
        "authorizes_writer_seal", "authorizes_migration",
    ):
        kwargs = result.__dict__.copy()
        kwargs[name] = True
        with pytest.raises(ValueError, match="P2B_AUTHORITY_CLAIM_FORBIDDEN"):
            P2bTransition(**kwargs)


def test_model_is_pure_no_signatures_no_sqlite_no_authority_calls():
    import scripts.bdiag_p2b_issuer_replay_lab as lab
    contents = Path(lab.__file__).read_text(encoding="utf-8")
    for forbidden in (
        "sqlite3", "os.open(", "subprocess", "private_key",
        "ed25519", "hmac.new(", "cryptography", "systemctl",
        "apparmor_parser", "RunStore", "projectctl.cli",
        "os.replace(", "os.chmod(", "os.setuid(",
    ):
        assert forbidden not in contents
    from projectctl.storage.sqlite import PROJECT_STATE_DB_VERSION
    assert PROJECT_STATE_DB_VERSION == 2
    from projectctl.cli import entry
    assert not hasattr(entry, "register_trace_export")
