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
    independent = model.TestOracleWitness(
        source_admitted=True, legacy_start_routes_excluded=True,
        preopened_writable_fds_excluded=True, source_epoch_observed=True,
        project_id=cap.project_id, run_id=cap.run_id, task_id=cap.task_id,
        source_schema_version=2, epoch=epoch,
        run_status=cap.run_status, event_prefix_id=cap.event_prefix_id,
        verification_sha256=_sha(verification), evidence_sha256=_sha(evidence),
    )
    return cap, independent


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


def test_complete_old_epoch_replayed_against_new_independent_witness():
    cap, old = _fixture(epoch=1)
    _, current = _fixture(epoch=2)
    # All of the stale package's own bytes and hashes still agree.
    assert model.classify(cap, oracle=old) == model.MODEL_ONLY
    assert model.classify(cap, oracle=current) == model.REFUSE_EPOCH


def test_modification_with_recomputed_self_hash_is_not_witnessed():
    cap, oracle = _fixture()
    substitute = b'{"kind":"verification","epoch":1,"tampered":true}\n'
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
