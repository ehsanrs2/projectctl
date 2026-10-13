from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from projectctl.core.enums import RunStatus
from projectctl.schema_export import PUBLIC_SCHEMAS, export_json_schemas
from projectctl.schemas.trace import (
    ExecutionTraceBundle,
    TraceAssessment,
    TraceEventSummary,
    TraceFinding,
    TraceSourceDescriptor,
)


def source(kind: str, version: int | None = None):
    return TraceSourceDescriptor(
        source_kind=kind,
        validation_state="present",
        schema_version=version,
        content_sha256=hashlib.sha256(kind.encode("ascii")).hexdigest(),
    )


def bundle():
    return ExecutionTraceBundle(
        project_id="demo",
        run_id="run-001",
        observed_run_status=RunStatus.PLANNED,
        completeness="complete",
        sources=[
            source("run_manifest", 2),
            source("run_record"),
        ],
        events=[
            TraceEventSummary(
                sequence=1,
                occurred_at=datetime(2026, 10, 13, 4, tzinfo=timezone.utc),
                category="lifecycle",
            )
        ],
    )


def test_trace_contract_is_strict_versioned_and_read_only_data_only(tmp_path):
    original = bundle()
    assert original.schema_kind == "projectctl.execution_trace_bundle"
    assert original.schema_version == 1
    assert original.assessments == []

    raw = original.model_dump(mode="json")
    assert ExecutionTraceBundle.model_validate_json(
        json.dumps(raw, sort_keys=True)
    ) == original
    assert PUBLIC_SCHEMAS["execution-trace-bundle.v1.schema.json"] is ExecutionTraceBundle
    written = export_json_schemas(tmp_path)
    path = tmp_path / "execution-trace-bundle.v1.schema.json"
    assert path in written
    exported = json.loads(path.read_text(encoding="utf-8"))
    assert exported["properties"]["schema_kind"]["default"] == (
        "projectctl.execution_trace_bundle"
    )
    assert exported["properties"]["schema_version"]["default"] == 1
    assert exported["additionalProperties"] is False


@pytest.mark.parametrize("illegal_field", [
    "worker_message",
    "raw_stdout",
    "stderr",
    "prompt",
    "environment",
    "absolute_worktree_path",
    "provider_payload",
    "lease_owner",
    "secrets",
    "arbitrary_metadata",
])
def test_bundle_rejects_private_freeform_fields(illegal_field):
    payload = bundle().model_dump(mode="json")
    payload[illegal_field] = "sensitive text from provider"
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        ExecutionTraceBundle.model_validate(payload)


@pytest.mark.parametrize("field", [
    "provider_payload", "raw_path", "error_detail", "raw_bytes", "raw_stdout",
])
def test_nested_sources_cannot_carry_private_content(field):
    raw = source("run_manifest", 2).model_dump()
    raw[field] = "secret or absolute path"
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        TraceSourceDescriptor.model_validate(raw)


def test_source_status_and_digest_constraints_are_fail_closed():
    digest = hashlib.sha256(b"x").hexdigest()

    with pytest.raises(ValidationError, match="requires SHA-256"):
        TraceSourceDescriptor(source_kind="run_manifest", schema_version=2,
                              validation_state="present")
    with pytest.raises(ValidationError, match="requires schema_version"):
        TraceSourceDescriptor(source_kind="run_manifest",
                              validation_state="present", content_sha256=digest)
    with pytest.raises(ValidationError, match="cannot declare schema_version"):
        TraceSourceDescriptor(source_kind="run_record", schema_version=1,
                              validation_state="present", content_sha256=digest)
    with pytest.raises(ValidationError, match="cannot claim bytes"):
        TraceSourceDescriptor(source_kind="run_manifest", schema_version=2,
                              validation_state="missing", content_sha256=digest,
                              reason_code="missing_source")
    with pytest.raises(ValidationError, match="requires a typed reason"):
        TraceSourceDescriptor(source_kind="verification_manifest",
                              validation_state="invalid")
    with pytest.raises(ValidationError, match="identify its schema version"):
        TraceSourceDescriptor(source_kind="run_manifest",
                              validation_state="unsupported",
                              reason_code="unsupported_schema")
    with pytest.raises(ValidationError, match="cannot be marked present"):
        TraceSourceDescriptor(source_kind="run_manifest", schema_version=99,
                              validation_state="present", content_sha256=digest)
    unknown = TraceSourceDescriptor(source_kind="run_manifest",
                                    validation_state="unsupported",
                                    schema_version=99,
                                    content_sha256=digest,
                                    reason_code="unsupported_schema")
    assert unknown.schema_version == 99
    missing = TraceSourceDescriptor(source_kind="worker_result",
                                    validation_state="missing",
                                    reason_code="missing_source")
    assert missing.content_sha256 is None
    with pytest.raises(ValidationError):
        TraceSourceDescriptor(source_kind="unknown_provider_dump",
                              validation_state="missing",
                              reason_code="missing_source")
    with pytest.raises(ValidationError):
        TraceSourceDescriptor(source_kind="run_manifest", schema_version=2,
                              validation_state="present",
                              content_sha256="NOT_SHA256")


def test_trace_cannot_claim_complete_when_sources_or_findings_missing():
    payload = bundle().model_dump()
    payload["sources"] = [source("run_record")]
    with pytest.raises(ValidationError, match="requires run record and run manifest"):
        ExecutionTraceBundle.model_validate(payload)

    payload = bundle().model_dump()
    payload["sources"].append(TraceSourceDescriptor(
        source_kind="worker_result", validation_state="missing",
        reason_code="missing_source",
    ))
    with pytest.raises(ValidationError, match="Complete trace cannot"):
        ExecutionTraceBundle.model_validate(payload)

    payload = bundle().model_dump()
    payload["findings"] = [TraceFinding(reason_code="identity_mismatch")]
    with pytest.raises(ValidationError, match="Complete trace cannot"):
        ExecutionTraceBundle.model_validate(payload)

    with pytest.raises(ValidationError, match="must expose a typed finding"):
        ExecutionTraceBundle(project_id="demo", run_id="run-x",
                             completeness="inconsistent")


def test_claimed_run_status_requires_present_run_record():
    with pytest.raises(ValidationError, match="requires a present run record"):
        ExecutionTraceBundle(
            project_id="demo", run_id="run-x", completeness="incomplete",
            observed_run_status=RunStatus.PASSED,
            sources=[source("run_manifest", 2)],
        )
    partial = ExecutionTraceBundle(
        project_id="demo", run_id="run-x", completeness="incomplete",
        sources=[
            TraceSourceDescriptor(
                source_kind="run_manifest", validation_state="unsupported",
                schema_version=99, reason_code="unsupported_schema",
            )
        ],
        findings=[TraceFinding(reason_code="unsupported_schema",
                               source_kind="run_manifest")],
    )
    assert partial.observed_run_status is None
    assert partial.completeness == "incomplete"


def test_order_and_uniqueness_rules_are_deterministic():
    old = bundle()
    payload = old.model_dump()
    payload["sources"] = list(reversed(payload["sources"]))
    with pytest.raises(ValidationError, match="sorted by kind"):
        ExecutionTraceBundle.model_validate(payload)

    payload = old.model_dump()
    payload["sources"].append(source("run_record"))
    with pytest.raises(ValidationError, match="sorted by kind"):
        ExecutionTraceBundle.model_validate(payload)

    payload = old.model_dump()
    payload["events"] *= 2
    with pytest.raises(ValidationError, match="unique record sequence"):
        ExecutionTraceBundle.model_validate(payload)

    payload = old.model_dump()
    payload["findings"] = [
        TraceFinding(reason_code="missing_source"),
        TraceFinding(reason_code="identity_mismatch"),
    ]
    payload["completeness"] = "inconsistent"
    with pytest.raises(ValidationError, match="sorted and unique"):
        ExecutionTraceBundle.model_validate(payload)


def test_assessment_cannot_claim_verification_from_worker_only():
    with pytest.raises(ValidationError, match="independent verification"):
        TraceAssessment(
            assessment_kind="verification_lineage",
            support="supported",
            supporting_sources=["worker_result"],
        )

    assessment = TraceAssessment(
        assessment_kind="verification_lineage",
        support="supported",
        supporting_sources=["evidence_manifest", "verification_manifest"],
    )
    payload = bundle().model_dump()
    payload["completeness"] = "incomplete"
    payload["assessments"] = [assessment]
    with pytest.raises(ValidationError, match="references unavailable sources"):
        ExecutionTraceBundle.model_validate(payload)

    payload["sources"] = [
        source("evidence_manifest", 2),
        source("run_manifest", 2),
        source("run_record"),
        source("verification_manifest", 2),
    ]
    valid = ExecutionTraceBundle.model_validate(payload)
    assert valid.assessments[0].support == "supported"
    # Structural anchors are not proof of cross-artifact identity. No collector
    # exists in Slice A that is allowed to emit this claim from real evidence.


def test_unavailable_assessment_cannot_claim_supporting_evidence():
    with pytest.raises(ValidationError, match="cannot claim support"):
        TraceAssessment(assessment_kind="verification_lineage",
                        support="indeterminate",
                        supporting_sources=["verification_manifest"])

    with pytest.raises(ValidationError, match="sorted and unique"):
        TraceAssessment(assessment_kind="delivery_lineage", support="supported",
                        supporting_sources=["review_receipt", "integration_manifest"])


@pytest.mark.parametrize("identifier", [
    "/home/user/project", "../repo", "foo/bar", "user@example.com",
    "secret\nVALUE", ".hidden",
])
def test_trace_identifiers_reject_paths_and_mail_like_strings(identifier):
    payload = bundle().model_dump()
    payload["project_id"] = identifier
    with pytest.raises(ValidationError):
        ExecutionTraceBundle.model_validate(payload)


def test_event_timestamps_normalize_to_utc_for_stable_json():
    instant = datetime(2026, 10, 13, 6, tzinfo=timezone.utc)
    offset = timezone(timedelta(hours=3, minutes=30))
    same = instant.astimezone(offset)
    left = TraceEventSummary(sequence=1, occurred_at=instant, category="lifecycle")
    right = TraceEventSummary(sequence=1, occurred_at=same, category="lifecycle")
    assert left.model_dump(mode="json") == right.model_dump(mode="json")

    # Identical normalized source snapshots must serialize identically;
    # there is no generated_at, host path or export timestamp field.
    before = bundle().model_dump(mode="json")
    after = bundle().model_dump(mode="json")
    assert json.dumps(before, sort_keys=True, separators=(",", ":")) == (
        json.dumps(after, sort_keys=True, separators=(",", ":"))
    )


def test_passed_run_requires_independent_artifact_sources_to_claim_complete():
    candidate = bundle().model_dump()
    candidate["observed_run_status"] = RunStatus.PASSED
    with pytest.raises(ValidationError, match="Passed run cannot claim complete"):
        ExecutionTraceBundle.model_validate(candidate)

    candidate["sources"] = [
        source("evidence_manifest", 2),
        source("run_manifest", 2),
        source("run_record"),
        source("verification_manifest", 2),
    ]
    assert ExecutionTraceBundle.model_validate(candidate).completeness == "complete"


def test_run_status_alone_cannot_create_verified_assessment():
    example = ExecutionTraceBundle(
        project_id="demo", run_id="run-unproven",
        completeness="incomplete",
        observed_run_status=RunStatus.PASSED,
        sources=[source("run_record")],
    )
    assert example.assessments == []
    assert example.completeness == "incomplete"
    with pytest.raises(ValidationError):
        ExecutionTraceBundle.model_validate({
            **example.model_dump(mode="json"),
            "assessments": [{
                "assessment_kind": "verification_lineage",
                "support": "supported",
                "supporting_sources": ["worker_result"],
            }],
        })
