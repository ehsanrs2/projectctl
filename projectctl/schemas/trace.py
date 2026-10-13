"""M6.0 Slice A: proposed read-only trace export *data* contract.

This module defines allowable output fields only. It deliberately contains no
collector, filesystem access, worker execution, mutable store or CLI commands.
A structurally valid trace is NOT proof that its sources were verified: the
future collector must independently check bytes, identity and lineage.
"""
from __future__ import annotations

from datetime import timezone
from typing import Literal

from pydantic import AwareDatetime, Field, field_validator, model_validator

from projectctl.core.enums import RunStatus
from projectctl.schemas.base import ProjectCtlModel


TraceSourceKind = Literal[
    "claim_transition_evidence",
    "context_manifest",
    "evidence_manifest",
    "execution_input_manifest",
    "integration_manifest",
    "publication_manifest",
    "review_receipt",
    "run_event_stream",
    "run_manifest",
    "run_record",
    "verification_manifest",
    "worker_result",
]
TraceSourceState = Literal["present", "missing", "invalid", "unsupported", "stale"]
TraceReasonCode = Literal[
    "content_digest_mismatch",
    "cross_project_reference",
    "identity_mismatch",
    "inconsistent_snapshot",
    "invalid_content",
    "missing_source",
    "parent_digest_mismatch",
    "redacted_reference",
    "source_changed",
    "source_unreadable",
    "unsupported_schema",
    "unsafe_source_path",
]
TraceEventCategory = Literal[
    "claim",
    "delivery",
    "integration",
    "lifecycle",
    "recovery",
    "verification",
    "unclassified",
]
TraceAssessmentKind = Literal[
    "artifact_completeness",
    "delivery_lineage",
    "verification_lineage",
]
TraceSupportLevel = Literal["supported", "unavailable", "indeterminate"]
TraceCompleteness = Literal["complete", "incomplete", "inconsistent"]

_IDENTIFIER = r"^[a-zA-Z0-9][a-zA-Z0-9_.:-]{0,127}$"
_DIGEST = r"^[0-9a-f]{64}$"

# Only these kinds have a versioned persisted Pydantic public schema.
_UNVERSIONED = frozenset({"run_record", "run_event_stream"})
# Source model versions already shipped in ProjectCTL. A future collector may
# interpret a historical schema only via its matching reader, not by casting it
# to the current model or declaring an unknown version "present".
_SUPPORTED_VERSIONS: dict[str, frozenset[int]] = {
    "claim_transition_evidence": frozenset({1}),
    "context_manifest": frozenset({1, 2, 3}),
    "evidence_manifest": frozenset({1, 2}),
    "execution_input_manifest": frozenset({1, 2}),
    "integration_manifest": frozenset({1, 2, 3}),
    "publication_manifest": frozenset({1}),
    "review_receipt": frozenset({1}),
    "run_manifest": frozenset({1, 2}),
    "verification_manifest": frozenset({1, 2}),
    "worker_result": frozenset({1}),
}
_VERIFICATION_ANCHORS = frozenset({"verification_manifest", "evidence_manifest"})
_DELIVERY_ANCHORS = frozenset({
    "integration_manifest", "publication_manifest", "review_receipt",
})


class TraceSourceDescriptor(ProjectCtlModel):
    """Byte/source presence, *not* independent verification or authority."""

    source_kind: TraceSourceKind
    validation_state: TraceSourceState
    schema_version: int | None = Field(default=None, ge=1)
    content_sha256: str | None = Field(default=None, pattern=_DIGEST)
    reason_code: TraceReasonCode | None = None

    @model_validator(mode="after")
    def validate_snapshot(self):
        if self.source_kind in _UNVERSIONED and self.schema_version is not None:
            raise ValueError("Unversioned trace source cannot declare schema_version.")
        if self.validation_state == "present":
            if self.content_sha256 is None or self.reason_code is not None:
                raise ValueError("Present trace source requires SHA-256 and no error reason.")
            if self.source_kind not in _UNVERSIONED:
                if self.schema_version is None:
                    raise ValueError("Present versioned trace source requires schema_version.")
                if self.schema_version not in _SUPPORTED_VERSIONS[self.source_kind]:
                    raise ValueError(
                        "Unknown source schema version cannot be marked present; "
                        "record it as unsupported instead."
                    )
        else:
            if self.reason_code is None:
                raise ValueError("Unavailable trace source requires a typed reason_code.")
            if self.validation_state == "missing":
                if self.content_sha256 is not None or self.reason_code != "missing_source":
                    raise ValueError("Missing source cannot claim bytes or another reason.")
            elif self.validation_state == "unsupported":
                if self.reason_code != "unsupported_schema" or self.schema_version is None:
                    raise ValueError("Unsupported source must identify its schema version.")
                if self.source_kind in _UNVERSIONED:
                    raise ValueError("Unversioned source cannot be an unsupported schema.")
        return self


class TraceEventSummary(ProjectCtlModel):
    """Only allowlisted event metadata; no raw type, payload, actor or logs."""

    sequence: int = Field(ge=1)
    occurred_at: AwareDatetime
    category: TraceEventCategory

    @field_validator("occurred_at")
    @classmethod
    def normalize_utc(cls, value):
        return value.astimezone(timezone.utc)


class TraceFinding(ProjectCtlModel):
    """Reason codes only: error strings/paths may contain private information."""

    reason_code: TraceReasonCode
    source_kind: TraceSourceKind | None = None


class TraceAssessment(ProjectCtlModel):
    """A claim of evidence support, not a worker-provided success flag.

    A future collector must establish cross-artifact lineage before emitting
    'supported'. Schema checks only enforce a minimum set of structural anchors.
    """

    assessment_kind: TraceAssessmentKind
    support: TraceSupportLevel
    supporting_sources: list[TraceSourceKind] = Field(default_factory=list)

    @model_validator(mode="after")
    def structural_proof(self):
        if self.support == "supported":
            if not self.supporting_sources:
                raise ValueError("Supported assessment requires evidence anchors.")
            sources = set(self.supporting_sources)
            if self.assessment_kind == "verification_lineage":
                if not _VERIFICATION_ANCHORS <= sources:
                    raise ValueError(
                        "Verification lineage needs independent verification "
                        "and evidence manifests."
                    )
            elif self.assessment_kind == "delivery_lineage":
                if not sources.intersection(_DELIVERY_ANCHORS):
                    raise ValueError("Delivery lineage requires a delivery/integration receipt.")
            elif self.assessment_kind == "artifact_completeness":
                if "run_record" not in sources or "run_manifest" not in sources:
                    raise ValueError("Completeness requires run record and run manifest.")
        elif self.supporting_sources:
            raise ValueError("Unavailable/indeterminate assessment cannot claim support.")
        if self.supporting_sources != sorted(set(self.supporting_sources)):
            raise ValueError("Assessment source anchors must be sorted and unique.")
        return self


class ExecutionTraceBundle(ProjectCtlModel):
    """Non-authoritative, allowlisted, deterministic derived run trace v1.

    There are deliberately no arbitrary text, paths, dictionaries, payloads,
    secret-bearing provider IDs, stdout/stderr or export-time timestamps.
    """

    schema_kind: Literal["projectctl.execution_trace_bundle"] = (
        "projectctl.execution_trace_bundle"
    )
    schema_version: Literal[1] = 1
    project_id: str = Field(min_length=1, max_length=128, pattern=_IDENTIFIER)
    run_id: str = Field(min_length=1, max_length=128, pattern=_IDENTIFIER)
    observed_run_status: RunStatus | None = None
    completeness: TraceCompleteness
    sources: list[TraceSourceDescriptor] = Field(default_factory=list)
    events: list[TraceEventSummary] = Field(default_factory=list)
    findings: list[TraceFinding] = Field(default_factory=list)
    assessments: list[TraceAssessment] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_deterministic_derived_trace(self):
        kinds = [s.source_kind for s in self.sources]
        if kinds != sorted(set(kinds)):
            raise ValueError("Trace sources must be sorted by kind and unique.")
        seq = [e.sequence for e in self.events]
        if seq != sorted(set(seq)):
            raise ValueError("Trace events must be ordered by unique record sequence.")
        finding_keys = [(f.reason_code, f.source_kind or "") for f in self.findings]
        if finding_keys != sorted(set(finding_keys)):
            raise ValueError("Trace findings must be sorted and unique.")
        names = [a.assessment_kind for a in self.assessments]
        if names != sorted(set(names)):
            raise ValueError("Trace assessments must be sorted and unique.")

        present = {s.source_kind for s in self.sources if s.validation_state == "present"}
        if self.observed_run_status is not None and "run_record" not in present:
            raise ValueError("Observed run status requires a present run record.")

        for assessment in self.assessments:
            if assessment.support == "supported":
                if not set(assessment.supporting_sources) <= present:
                    raise ValueError("Supported assessment references unavailable sources.")

        if self.completeness == "complete":
            if self.findings or any(s.validation_state != "present" for s in self.sources):
                raise ValueError("Complete trace cannot contain findings or unavailable sources.")
            if not {"run_record", "run_manifest"} <= present:
                raise ValueError("Complete trace requires run record and run manifest.")
            if self.observed_run_status is None:
                raise ValueError("Complete trace requires an observed run status.")
            if self.observed_run_status == RunStatus.PASSED:
                if not _VERIFICATION_ANCHORS <= present:
                    raise ValueError(
                        "Passed run cannot claim complete trace without independent "
                        "verification and evidence sources."
                    )
        if self.completeness == "inconsistent" and not self.findings:
            raise ValueError("Inconsistent trace must expose a typed finding.")
        return self
