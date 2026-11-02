"""M6.0 P01: negative-only source/epoch admission modeling, no real input."""
from __future__ import annotations

from dataclasses import replace
import hashlib
import importlib.util
from pathlib import Path
import sqlite3

import pytest


ROOT = Path(__file__).resolve().parents[1]
MODEL = ROOT / "scripts/p01_synthetic_epoch_admission_model.py"
spec = importlib.util.spec_from_file_location("p01_synthetic_epoch_admission_model", MODEL)
assert spec is not None and spec.loader is not None
import sys
model = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = model
spec.loader.exec_module(model)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _oracle(epoch=1):
    # Authored separately from Capture; never derive a reference from the candidate.
    observed = {
        1: (b'{"kind":"verification","epoch":1}\n', b'{"kind":"evidence","epoch":1}\n'),
        2: (b'{"kind":"verification","epoch":2}\n', b'{"kind":"evidence","epoch":2}\n'),
    }
    verification, evidence = observed[epoch]
    return model.TestOracleWitness(
        source_admitted=True, legacy_start_routes_excluded=True,
        preopened_writable_fds_excluded=True, source_epoch_observed=True,
        project_id="p01-project", run_id="p01-run", task_id="p01-task",
        source_schema_version=2, epoch=epoch,
        run_status="ready_to_integrate", event_prefix_id=7,
        verification_sha256=_sha(verification), evidence_sha256=_sha(evidence),
    )


def _fixture(epoch=1):
    verification = f'{{"kind":"verification","epoch":{epoch}}}\n'.encode()
    evidence = f'{{"kind":"evidence","epoch":{epoch}}}\n'.encode()
    cap = model.Capture(
        project_id="p01-project", run_id="p01-run", task_id="p01-task",
        source_schema_version=2, db_epoch=epoch,
        run_status="ready_to_integrate", event_prefix_id=7,
        verification_epoch=epoch, evidence_epoch=epoch,
        verification_bytes=verification, evidence_bytes=evidence,
        inventory_verification_sha256=_sha(verification),
        inventory_evidence_sha256=_sha(evidence),
    )
    return cap, _oracle(epoch)


def test_consistent_fixture_is_not_production_admission():
    capture, witness = _fixture()
    assert model.classify(capture, oracle=witness) == model.MODEL_ONLY
    assert "NOT_ATTESTED" in model.MODEL_ONLY


def test_absent_external_witness_fails_even_when_caller_claims_success():
    capture, _ = _fixture()
    capture = replace(capture, caller_claims_epoch_proven=True)
    assert model.classify(capture, oracle=None) == model.REFUSE_NO_WITNESS
    assert model.classify(capture, oracle="SELF_SIGNED") == model.REFUSE_NO_WITNESS


@pytest.mark.parametrize("field", [
    "source_admitted", "legacy_start_routes_excluded",
    "preopened_writable_fds_excluded", "source_epoch_observed",
])
def test_p0_requires_independent_positive_scope(field):
    capture, witness = _fixture()
    assert model.classify(capture, oracle=replace(witness, **{field: False})) == model.REFUSE_ADMISSION


@pytest.mark.parametrize("field", ["project_id", "run_id", "task_id"])
def test_p0_identity_rejects_cross_project_run_or_task(field):
    capture, witness = _fixture()
    assert model.classify(replace(capture, **{field: "other"}), oracle=witness) == model.REFUSE_IDENTITY


@pytest.mark.parametrize("version", [1, 3, True])
def test_unknown_or_coerced_db_version_refused(version):
    capture, witness = _fixture()
    assert model.classify(replace(capture, source_schema_version=version), oracle=witness) == model.REFUSE_IDENTITY


def test_mixed_db_and_json_epochs_rejected_even_with_matching_local_hashes():
    cap, oracle = _fixture(epoch=1)
    newer = b'{"kind":"verification","epoch":2}\n'
    hybrid = replace(cap, verification_epoch=2, verification_bytes=newer,
                     inventory_verification_sha256=_sha(newer),
                     caller_claims_epoch_proven=True)
    assert _sha(hybrid.verification_bytes) == hybrid.inventory_verification_sha256
    assert model.classify(hybrid, oracle=oracle) == model.REFUSE_EPOCH


def test_mismatched_two_json_epochs_refused():
    cap, oracle = _fixture(epoch=1)
    assert model.classify(replace(cap, evidence_epoch=2), oracle=oracle) == model.REFUSE_EPOCH


def test_historical_as_of_is_distinct_from_false_current_claim():
    cap, old = _fixture(epoch=1)
    # Exact historical bytes remain available even though the latest epoch advanced.
    old = replace(old, latest_epoch=2)
    assert model.classify(cap, oracle=old) == model.MODEL_ONLY
    assert model.classify(replace(cap, observation_claim="current"), oracle=old) == model.REFUSE_CURRENT
    assert model.classify(cap, oracle=_oracle(2)) == model.REFUSE_EPOCH


def test_modification_with_recomputed_self_hash_is_not_witnessed():
    cap, oracle = _fixture()
    substitute = b'{ "kind":"verification","epoch":1}\n'
    modified = replace(cap, verification_bytes=substitute,
                       inventory_verification_sha256=_sha(substitute))
    assert model.classify(modified, oracle=oracle) == model.REFUSE_BYTES


@pytest.mark.parametrize("field", ["verification_bytes", "evidence_bytes"])
def test_inventory_hash_mismatch_refused(field):
    cap, oracle = _fixture()
    assert model.classify(replace(cap, **{field: b"ALTERED"}), oracle=oracle) == model.REFUSE_INTEGRITY


@pytest.mark.parametrize("status", ["verifying", "passed", "failed"])
def test_only_narrow_verification_status_is_modeled(status):
    cap, oracle = _fixture()
    assert model.classify(replace(cap, run_status=status), oracle=oracle) == model.REFUSE_BOUNDARY


@pytest.mark.parametrize("event_id", [0, 8, True])
def test_event_prefix_mismatch_is_refused(event_id):
    cap, oracle = _fixture()
    assert model.classify(replace(cap, event_prefix_id=event_id), oracle=oracle) == model.REFUSE_BOUNDARY


def test_model_performs_no_filesystem_or_sqlite_source_reads(monkeypatch):
    cap, oracle = _fixture()
    def forbidden(*_args, **_kwargs):
        raise AssertionError("P01 model cannot open source or database")
    monkeypatch.setattr(Path, "open", forbidden)
    monkeypatch.setattr(sqlite3, "connect", forbidden)
    assert model.classify(cap, oracle=oracle) == model.MODEL_ONLY


def test_no_authoritative_projectctl_runtime_imports():
    source = MODEL.read_text(encoding="utf-8")
    for unsafe in ("from projectctl", "import projectctl", "sqlite3", "subprocess", "socket", "Path("):
        assert unsafe not in source


def test_forged_matching_oracle_cannot_attest_tampered_capture():
    cap, independent = _fixture()
    substitute = b'{ "kind":"verification","epoch":1}\n'
    tampered = replace(cap, event_prefix_id=8, verification_bytes=substitute,
                       inventory_verification_sha256=_sha(substitute),
                       caller_claims_epoch_proven=True)
    assert model.classify(tampered, oracle=independent) == model.REFUSE_BOUNDARY
    # Deliberately circular attacker construction: consistency cannot prove origin.
    forged = replace(independent, event_prefix_id=tampered.event_prefix_id,
                     verification_sha256=tampered.inventory_verification_sha256)
    result = model.classify(tampered, oracle=forged)
    assert result == "SYNTHETIC_CONSISTENT_NOT_ATTESTED"


@pytest.mark.parametrize("kind", ["verification", "evidence"])
def test_json_epoch_mismatch_with_all_hashes_recomputed(kind):
    cap, oracle = _fixture()
    raw = f'{{"kind":"{kind}","epoch":2}}\n'.encode()
    cap = replace(cap, **{f"{kind}_bytes": raw, f"inventory_{kind}_sha256": _sha(raw)})
    # Even a matching oracle digest cannot conceal metadata epoch 1 vs JSON epoch 2.
    oracle = replace(oracle, **{f"{kind}_sha256": _sha(raw)})
    assert model.classify(cap, oracle=oracle) == model.REFUSE_EPOCH


@pytest.mark.parametrize("latest, expected", [
    (None, model.REFUSE_CURRENT), (1, model.MODEL_ONLY), (2, model.REFUSE_CURRENT),
])
def test_current_requires_separate_latest_epoch_observation(latest, expected):
    cap, oracle = _fixture()
    assert model.classify(replace(cap, observation_claim="current"),
                          oracle=replace(oracle, latest_epoch=latest)) == expected


def test_latest_historical_epoch_is_consistent_for_either_claim():
    cap, oracle = _fixture(2)
    oracle = replace(oracle, latest_epoch=2)
    assert model.classify(cap, oracle=oracle) == model.MODEL_ONLY
    assert model.classify(replace(cap, observation_claim="current"), oracle=oracle) == model.MODEL_ONLY


@pytest.mark.parametrize("claim", ["", "latest", "AS_OF", None, True, 1, []])
def test_invalid_observation_claim_refused(claim):
    cap, oracle = _fixture()
    assert model.classify(replace(cap, observation_claim=claim), oracle=oracle) == model.REFUSE_CURRENT


@pytest.mark.parametrize("latest", [True, False, 0, -1, 1.0, "1", 1_000_001, []])
def test_invalid_latest_observation_refused_for_both_claims(latest):
    cap, oracle = _fixture()
    oracle = replace(oracle, latest_epoch=latest)
    for claim in ("as_of", "current"):
        assert model.classify(replace(cap, observation_claim=claim), oracle=oracle) == model.REFUSE_CURRENT


def test_latest_observation_cannot_precede_historical_epoch():
    cap, oracle = _fixture(2)
    assert model.classify(cap, oracle=replace(oracle, latest_epoch=1)) == model.REFUSE_CURRENT


@pytest.mark.parametrize("kind", ["verification", "evidence"])
@pytest.mark.parametrize("raw", [
    b"", b"{", b"\xff", b"\xef\xbb\xbf{}", b"[]", b"null", b"1", b'"text"',
    b'{"kind":"verification","epoch":1} trailing',
    b'{"kind":"verification","epoch":1,"epoch":1}',
    b'{"kind":"verification","epoch":1,"ep\\u006fch":1}',
    b'{"kind":"verification","kind":"verification","epoch":1}',
    b'{"kind":"verification","epoch":true}',
    b'{"kind":"verification","epoch":1.0}',
    b'{"kind":"verification","epoch":"1"}',
    b'{"kind":"verification","epoch":0}',
    b'{"kind":"verification","epoch":-1}',
    b'{"kind":"verification","epoch":1000001}',
    b'{"kind":"verification","epoch":NaN}',
    b'{"kind":"verification","epoch":Infinity}',
    b'{"kind":"verification","epoch":-Infinity}',
    b'{"kind":"verification","epoch":null}',
    b'{"kind":"verification","epoch":[]}',
    b'{"kind":"verification"}', b'{"epoch":1}',
    b'{"kind":"unknown","epoch":1}',
    b'{"kind":"verification","epoch":1,"extra":true}',
    b"[" * 1000 + b"]" * 1000, b" " * 2049,
    bytearray(b'{"kind":"verification","epoch":1}'), None,
])
def test_invalid_synthetic_json_refused_even_with_matching_hashes(kind, raw):
    cap, oracle = _fixture()
    digest = _sha(raw) if isinstance(raw, (bytes, bytearray)) else "0" * 64
    cap = replace(cap, **{f"{kind}_bytes": raw, f"inventory_{kind}_sha256": digest})
    oracle = replace(oracle, **{f"{kind}_sha256": digest})
    assert model.classify(cap, oracle=oracle) == model.REFUSE_INTEGRITY


@pytest.mark.parametrize("kind", ["verification", "evidence"])
def test_swapped_synthetic_artifact_kind_refused(kind):
    cap, oracle = _fixture()
    other = "evidence" if kind == "verification" else "verification"
    raw = f'{{"kind":"{other}","epoch":1}}'.encode()
    cap = replace(cap, **{f"{kind}_bytes": raw, f"inventory_{kind}_sha256": _sha(raw)})
    oracle = replace(oracle, **{f"{kind}_sha256": _sha(raw)})
    assert model.classify(cap, oracle=oracle) == model.REFUSE_INTEGRITY


@pytest.mark.parametrize("field", ["project_id", "run_id", "task_id"])
@pytest.mark.parametrize("value", ["", " leading", "trailing ", "a/b", "a\\b", "..", ".hidden",
                                  "a\n", "a\x00b", "شناسه", "a" * 129, None, True, 1, []])
def test_matching_invalid_identities_still_refused(field, value):
    cap, oracle = _fixture()
    assert model.classify(replace(cap, **{field: value}),
                          oracle=replace(oracle, **{field: value})) == model.REFUSE_IDENTITY


@pytest.mark.parametrize("field", ["db_epoch", "verification_epoch", "evidence_epoch", "epoch"])
@pytest.mark.parametrize("value", [True, False, 0, -1, 1.0, "1", None, [], 1_000_001])
def test_invalid_metadata_epochs_refused(field, value):
    cap, oracle = _fixture()
    if field == "epoch":
        oracle = replace(oracle, epoch=value)
    else:
        cap = replace(cap, **{field: value})
    assert model.classify(cap, oracle=oracle) == model.REFUSE_EPOCH


@pytest.mark.parametrize("side", ["capture", "oracle"])
@pytest.mark.parametrize("value", [True, 0, -1, 1.0, "7", None, [], 1 << 63])
def test_invalid_event_boundary_values_refused(side, value):
    cap, oracle = _fixture()
    if side == "capture":
        cap = replace(cap, event_prefix_id=value)
    else:
        oracle = replace(oracle, event_prefix_id=value)
    assert model.classify(cap, oracle=oracle) == model.REFUSE_BOUNDARY


@pytest.mark.parametrize("field", ["verification_sha256", "evidence_sha256"])
@pytest.mark.parametrize("value", [None, True, [], "", "A" * 64, "g" * 64, "0" * 63, "0" * 65])
def test_invalid_oracle_digest_refused(field, value):
    cap, oracle = _fixture()
    assert model.classify(cap, oracle=replace(oracle, **{field: value})) == model.REFUSE_INTEGRITY


def test_invalid_capture_type_refused():
    assert model.classify(None, oracle=_oracle()) == model.REFUSE_IDENTITY
