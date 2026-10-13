from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

import pytest

from projectctl.core.enums import RunStatus, TaskStatus, WorkerResultStatus
from projectctl.schemas.execution import WorkerResult
from projectctl.schemas.execution_input import (
    ExecutionInputManifestV1,
    ExecutionTaskInput,
)
from projectctl.schemas.run import ContextManifestV1, ContextManifestV2
from projectctl.schemas.task import NormalizedTask, TaskSource
from projectctl.schemas.trace import TraceSourceDescriptor, _SUPPORTED_VERSIONS
from projectctl.trace.format import canonical_trace_json_bytes
from projectctl.trace.snapshot import TraceDbSnapshot, TraceFileSnapshot
from projectctl.trace.validate import (
    conservative_trace_from_snapshots,
    inspect_artifact_snapshot,
    _PARSERS,
    _finite_json_float,
    _InvalidJson,
)

NOW = datetime(2026, 10, 13, 8, tzinfo=timezone.utc)


def _file(kind: str, data: bytes) -> TraceFileSnapshot:
    return TraceFileSnapshot(
        source_kind=kind,
        content_sha256=hashlib.sha256(data).hexdigest(),
        raw_bytes=data,
    )


def _context(version: int = 1, task_id: str = "task-1") -> TraceFileSnapshot:
    if version == 1:
        model = ContextManifestV1(task_id=task_id, git_commit="deadbeef")
    else:
        model = ContextManifestV2(
            task_id=task_id, git_commit="deadbeef",
            task_snapshot_digest="snapshot", project_state_digest="state",
        )
    return _file(
        "context_manifest",
        json.dumps(model.model_dump(mode="json"), sort_keys=True).encode(),
    )


def _inspect(file: TraceFileSnapshot | None, kind: str = "context_manifest"):
    return inspect_artifact_snapshot(
        file,
        source_kind=kind,
        run_id="run-1",
        task_id="task-1",
        project_id="project-1",
    )


def _db(status=RunStatus.PLANNED):
    return TraceDbSnapshot(
        run_id="run-1",
        task_id="task-1",
        observed_status=status,
        run_record_sha256="a" * 64,
        run_manifest_sha256="b" * 64,
        run_manifest_version=2,
        event_stream_sha256="c" * 64,
        events=(),
    )


@pytest.mark.parametrize("version", [1, 2])
def test_historical_context_is_versioned_and_verified_without_raw_content(version):
    descriptor = _inspect(_context(version))
    assert descriptor.validation_state == "present"
    assert descriptor.schema_version == version
    assert descriptor.source_kind == "context_manifest"
    assert descriptor.content_sha256 is not None
    assert "deadbeef" not in repr(descriptor)


def test_missing_and_unsupported_are_distinct_not_present():
    missing = _inspect(None)
    assert missing.validation_state == "missing"
    assert missing.reason_code == "missing_source"
    assert missing.content_sha256 is None

    doc = ContextManifestV1(task_id="task-1", git_commit="deadbeef").model_dump(
        mode="json"
    )
    doc["schema_version"] = 99
    unknown = _inspect(_file("context_manifest", json.dumps(doc).encode()))
    assert unknown.validation_state == "unsupported"
    assert unknown.schema_version == 99
    assert unknown.reason_code == "unsupported_schema"


@pytest.mark.parametrize("data", [
    b"not-json",
    b'{"schema_kind":"projectctl.context_manifest",'
    b'"schema_kind":"projectctl.context_manifest","schema_version":1}',
    b'{"schema_kind":"projectctl.context_manifest","schema_version":true}',
    b'{"schema_kind":"projectctl.context_manifest","schema_version":0}',
    b'{"schema_kind":"projectctl.worker_result","schema_version":1}',
    b'{"schema_kind":"projectctl.context_manifest","schema_version":1,'
    b'"task_id":"task-1","git_commit":"secret_value","unexpected":"private"}',
])
def test_invalid_or_ambiguous_documents_never_become_present(data):
    descriptor = _inspect(_file("context_manifest", data))
    assert descriptor.validation_state == "invalid"
    assert descriptor.reason_code == "invalid_content"
    assert data.decode("utf-8", errors="ignore") not in repr(descriptor)


def test_task_and_source_kind_mismatch_cannot_claim_validity():
    mismatch = _inspect(_context(task_id="another-task"))
    assert mismatch.validation_state == "invalid"
    assert mismatch.reason_code == "identity_mismatch"

    swapped = _inspect(
        TraceFileSnapshot(
            source_kind="worker_result",
            content_sha256=_context().content_sha256,
            raw_bytes=_context().raw_bytes,
        )
    )
    assert swapped.validation_state == "invalid"
    assert swapped.reason_code == "identity_mismatch"


def test_raw_task_identity_cannot_be_normalized_into_a_valid_match():
    original = ContextManifestV1(
        task_id="task-1", git_commit="deadbeef"
    ).model_dump(mode="json")
    original["task_id"] = " task-1 "
    result = _inspect(_file("context_manifest", json.dumps(original).encode()))
    assert result.validation_state == "invalid"
    assert result.reason_code == "identity_mismatch"


def test_tampered_snapshotted_bytes_are_stale_and_not_reused():
    original = _context()
    forged = TraceFileSnapshot(
        source_kind="context_manifest",
        content_sha256="a" * 64,
        raw_bytes=original.raw_bytes,
    )
    result = _inspect(forged)
    assert result.validation_state == "stale"
    assert result.reason_code == "content_digest_mismatch"
    assert result.content_sha256 is None


def _execution_input() -> ExecutionInputManifestV1:
    task = NormalizedTask(
        id="task-1", title="No-op",
        source=TaskSource(provider="beads", external_id="task-1"),
        status=TaskStatus.READY,
    )
    return ExecutionInputManifestV1(
        input_id="input-1", project_id="project-1", task_id="task-1",
        integration_target_ref="main", base_commit="deadbeef",
        project_state_digest="state", scheduler_task_snapshot_digest="snapshot",
        task_scope_digest="scope", task_scope_ids=["scope-1"],
        task_inputs=[ExecutionTaskInput(task_id="task-1", digest="task-digest", task=task)],
        references_digest="refs", created_at=NOW,
    )


def test_cross_project_execution_input_is_rejected_with_safe_reason():
    model = _execution_input()
    valid = _file(
        "execution_input_manifest",
        json.dumps(model.model_dump(mode="json")).encode(),
    )
    assert _inspect(valid, "execution_input_manifest").validation_state == "present"

    data = model.model_dump(mode="json")
    data["project_id"] = "another-project"
    changed = _file("execution_input_manifest", json.dumps(data).encode())
    result = _inspect(changed, "execution_input_manifest")
    assert result.validation_state == "invalid"
    assert result.reason_code == "cross_project_reference"


def test_conservative_bundle_never_claims_completion_or_verification():
    valid_context = _inspect(_context())
    trace = conservative_trace_from_snapshots(
        project_id="project-1",
        db_snapshot=_db(RunStatus.PASSED),
        file_sources={"context_manifest": valid_context},
    )
    assert trace.observed_run_status == RunStatus.PASSED
    assert trace.completeness == "incomplete"
    assert trace.assessments == []
    assert [s.source_kind for s in trace.sources] == sorted(
        [s.source_kind for s in trace.sources]
    )
    assert len(trace.sources) == 4
    assert trace.findings == []
    first = canonical_trace_json_bytes(trace)
    again = canonical_trace_json_bytes(trace)
    assert first == again
    assert b"deadbeef" not in first
    assert b"task-1" not in first
    assert b"supported" not in first


def test_missing_invalid_and_unsupported_evidence_stay_explicit():
    missing = _inspect(None)
    invalid = _inspect(_context(task_id="another-task"))
    unknown_doc = ContextManifestV1(
        task_id="task-1", git_commit="deadbeef"
    ).model_dump(mode="json")
    unknown_doc["schema_version"] = 99
    unsupported = _inspect(_file("context_manifest", json.dumps(unknown_doc).encode()))

    for desc, expected_state in [
        (missing, "incomplete"),
        (invalid, "inconsistent"),
        (unsupported, "incomplete"),
    ]:
        result = conservative_trace_from_snapshots(
            project_id="project-1", db_snapshot=_db(RunStatus.PASSED),
            file_sources={"context_manifest": desc},
        )
        assert result.completeness == expected_state
        assert result.assessments == []
        assert len(result.findings) == 1
        assert result.findings[0].source_kind == "context_manifest"
        assert b"another-task" not in canonical_trace_json_bytes(result)


def test_pure_builder_rejects_forged_kind_binding():
    descriptor = _inspect(_context())
    with pytest.raises(ValueError, match="Source-kind binding mismatch"):
        conservative_trace_from_snapshots(
            project_id="project-1", db_snapshot=_db(),
            file_sources={"worker_result": descriptor},
        )
    with pytest.raises(ValueError, match="Unexpected source kind"):
        conservative_trace_from_snapshots(
            project_id="project-1", db_snapshot=_db(),
            file_sources={"../../../secret": descriptor},
        )


def test_malformed_project_identity_rejected_by_public_contract():
    with pytest.raises(ValueError):
        conservative_trace_from_snapshots(
            project_id="../private", db_snapshot=_db(), file_sources={},
        )


def test_all_nine_artifact_parsers_match_the_public_known_version_contract():
    assert set(_PARSERS) == set(_SUPPORTED_VERSIONS) - {
        "run_record", "run_event_stream", "run_manifest"
    }
    for source_kind, versions in _PARSERS.items():
        assert set(versions) == _SUPPORTED_VERSIONS[source_kind]
        for version, parser in versions.items():
            fields = parser.model_fields
            assert "task_id" in fields
            assert fields["schema_version"].default == version
            assert fields["schema_kind"].default == "projectctl." + source_kind


@pytest.mark.parametrize("number", ["1e309", "-1e309", "4.5e9999"])
def test_json_exponent_overflow_is_rejected_before_model_coercion(number):
    with pytest.raises(_InvalidJson):
        _finite_json_float(number)
    doc = (
        '{"schema_kind":"projectctl.context_manifest",'
        '"schema_version":1,"task_id":"task-1","git_commit":"deadbeef",'
        '"untrusted_metric":' + number + "}"
    ).encode()
    invalid = _inspect(_file("context_manifest", doc))
    assert invalid.validation_state == "invalid"
    assert invalid.reason_code == "invalid_content"


def test_finite_numeric_json_does_not_trigger_false_overflow_alarm():
    assert _finite_json_float("0.5") == 0.5
    assert _finite_json_float("1e3") == 1000.0


def test_worker_result_secret_summary_never_appears_in_public_descriptor():
    model = WorkerResult(
        run_id="run-1", task_id="task-1",
        status=WorkerResultStatus.IMPLEMENTED,
        summary="CREDENTIAL_CANARY_123_IN_WORKER_SUMMARY",
        completed_at=NOW,
    )
    raw = json.dumps(model.model_dump(mode="json")).encode()
    result = _inspect(_file("worker_result", raw), "worker_result")
    assert result.validation_state == "present"
    dumped = json.dumps(result.model_dump(mode="json"))
    assert "CREDENTIAL_CANARY" not in dumped
    assert "CREDENTIAL_CANARY" not in repr(result)


def test_worker_result_raw_run_identity_not_authorized_by_pydantic_trimming():
    model = WorkerResult(
        run_id="run-1", task_id="task-1",
        status=WorkerResultStatus.IMPLEMENTED,
        summary="ok", completed_at=NOW,
    )
    doc = model.model_dump(mode="json")
    doc["run_id"] = " run-1 "
    result = _inspect(_file("worker_result", json.dumps(doc).encode()), "worker_result")
    assert result.validation_state == "invalid"
    assert result.reason_code == "identity_mismatch"


def test_raw_execution_input_project_identity_not_authorized_by_trimming():
    doc = _execution_input().model_dump(mode="json")
    doc["project_id"] = " project-1 "
    result = _inspect(
        _file("execution_input_manifest", json.dumps(doc).encode()),
        "execution_input_manifest",
    )
    assert result.validation_state == "invalid"
    assert result.reason_code == "cross_project_reference"


def test_implicit_historical_v1_is_parsed_only_by_historical_model():
    doc = ContextManifestV1(
        task_id="task-1", git_commit="deadbeef"
    ).model_dump(mode="json")
    doc.pop("schema_version")
    result = _inspect(_file("context_manifest", json.dumps(doc).encode()))
    assert result.validation_state == "present"
    assert result.schema_version == 1


def test_pure_trace_keeps_mixed_error_reasons_without_verified_assessments():
    present = _inspect(_context())
    missing = inspect_artifact_snapshot(
        None, source_kind="verification_manifest",
        run_id="run-1", task_id="task-1", project_id="project-1",
    )
    invalid = _inspect(_context(task_id="wrong-task"))
    result = conservative_trace_from_snapshots(
        project_id="project-1", db_snapshot=_db(RunStatus.PASSED),
        file_sources={
            "context_manifest": present,
            "verification_manifest": missing,
            "worker_result": TraceSourceDescriptor(
                source_kind="worker_result", validation_state="invalid",
                reason_code="invalid_content",
            ),
        },
    )
    assert result.completeness == "inconsistent"
    assert result.assessments == []
    assert [(x.reason_code, x.source_kind) for x in result.findings] == [
        ("invalid_content", "worker_result"),
        ("missing_source", "verification_manifest"),
    ]
    assert b"supported" not in canonical_trace_json_bytes(result)
