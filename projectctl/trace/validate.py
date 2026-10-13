"""M6.0 B1b: pure versioned artifact inspection and conservative trace assembly.

No filesystem, SQLite, worker or CLI IO happens in this module. The caller
must obtain source snapshots through the separately audited B1a reader.
Pydantic validation proves structure/identity only, NOT parent digest
lineage, independent verification, or delivery.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping

from pydantic import BaseModel, ValidationError

from projectctl.schemas.delivery import PublicationManifest, ReviewReceipt
from projectctl.schemas.evidence import EvidenceManifest, EvidenceManifestV1
from projectctl.schemas.execution import WorkerResult
from projectctl.schemas.execution_input import (
    ClaimTransitionEvidence,
    ExecutionInputManifest,
    ExecutionInputManifestV1,
)
from projectctl.schemas.integration import (
    IntegrationManifest,
    IntegrationManifestV1,
    IntegrationManifestV2,
)
from projectctl.schemas.run import (
    ContextManifest,
    ContextManifestV1,
    ContextManifestV2,
)
from projectctl.schemas.trace import (
    ExecutionTraceBundle,
    TraceFinding,
    TraceSourceDescriptor,
)
from projectctl.schemas.verification import VerificationManifest, VerificationManifestV1
from projectctl.trace.snapshot import (
    MAX_ARTIFACT_BYTES,
    TraceDbSnapshot,
    TraceFileSnapshot,
)

# The schema-kind versions are deliberately explicit. No "current-model"
# fallback for historical artifacts, no trusted interpretation of unknown vN.
_PARSERS: dict[str, dict[int, type[BaseModel]]] = {
    "claim_transition_evidence": {1: ClaimTransitionEvidence},
    "context_manifest": {
        1: ContextManifestV1,
        2: ContextManifestV2,
        3: ContextManifest,
    },
    "evidence_manifest": {1: EvidenceManifestV1, 2: EvidenceManifest},
    "execution_input_manifest": {
        1: ExecutionInputManifestV1,
        2: ExecutionInputManifest,
    },
    "integration_manifest": {
        1: IntegrationManifestV1,
        2: IntegrationManifestV2,
        3: IntegrationManifest,
    },
    "publication_manifest": {1: PublicationManifest},
    "review_receipt": {1: ReviewReceipt},
    "verification_manifest": {
        1: VerificationManifestV1,
        2: VerificationManifest,
    },
    "worker_result": {1: WorkerResult},
}


class _InvalidJson(ValueError):
    pass


def _object_no_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for name, value in pairs:
        if name in result:
            raise _InvalidJson("duplicate field")
        result[name] = value
    return result


def _safe_problem(kind: str, reason: str, version: int | None = None,
                  sha256: str | None = None) -> TraceSourceDescriptor:
    # Never propagate raw Pydantic/JSON error strings; they may leak secrets.
    return TraceSourceDescriptor(
        source_kind=kind,
        validation_state="invalid",
        schema_version=version,
        content_sha256=sha256,
        reason_code=reason,
    )


def inspect_artifact_snapshot(
    snapshot: TraceFileSnapshot | None,
    *,
    source_kind: str,
    run_id: str,
    task_id: str,
    project_id: str,
) -> TraceSourceDescriptor:
    """Return safe public metadata for a single previously captured artifact.

    'present' indicates schema + available identity fields matched, not
    independently proven semantic digest or parent verification lineage.
    ContextManifest and ExecutionInputManifest have no run_id: their task
    identity can be compared but run binding remains a later Collector gate.
    """
    if source_kind not in _PARSERS:
        raise ValueError("Source kind is not a versioned run artifact.")
    if snapshot is None:
        return TraceSourceDescriptor(
            source_kind=source_kind,
            validation_state="missing",
            reason_code="missing_source",
        )
    if snapshot.source_kind != source_kind:
        return _safe_problem(source_kind, "identity_mismatch")
    raw = snapshot.raw_bytes
    if not isinstance(raw, bytes) or len(raw) > MAX_ARTIFACT_BYTES:
        return _safe_problem(source_kind, "invalid_content")
    calculated = hashlib.sha256(raw).hexdigest()
    if calculated != snapshot.content_sha256:
        return TraceSourceDescriptor(
            source_kind=source_kind,
            validation_state="stale",
            reason_code="content_digest_mismatch",
        )
    try:
        payload = json.loads(
            raw,
            object_pairs_hook=_object_no_duplicates,
            parse_constant=lambda _value: (_ for _ in ()).throw(_InvalidJson()),
        )
    except (ValueError, UnicodeError, TypeError, RecursionError):
        return _safe_problem(source_kind, "invalid_content", sha256=calculated)
    if not isinstance(payload, dict) or payload.get("schema_kind") != (
        "projectctl." + source_kind
    ):
        return _safe_problem(source_kind, "invalid_content", sha256=calculated)
    version = payload.get("schema_version", 1)  # historical implicit-v1
    if type(version) is not int or version < 1:
        return _safe_problem(source_kind, "invalid_content", sha256=calculated)
    klass = _PARSERS[source_kind].get(version)
    if klass is None:
        return TraceSourceDescriptor(
            source_kind=source_kind,
            validation_state="unsupported",
            schema_version=version,
            content_sha256=calculated,
            reason_code="unsupported_schema",
        )
    try:
        model = klass.model_validate(payload)
    except (ValidationError, ValueError, TypeError, RecursionError):
        return _safe_problem(
            source_kind, "invalid_content", version=version, sha256=calculated
        )
    # Pydantic's historical base schema strips surrounding whitespace from
    # strings. Compare the ORIGINAL decoded identity bytes too, so a file
    # containing " task-1 " cannot silently impersonate "task-1".
    if (
        getattr(model, "task_id", None) != task_id
        or payload.get("task_id") != task_id
    ):
        return _safe_problem(
            source_kind, "identity_mismatch", version=version, sha256=calculated
        )
    model_run_id = getattr(model, "run_id", None)
    if model_run_id is not None and (
        model_run_id != run_id or payload.get("run_id") != run_id
    ):
        return _safe_problem(
            source_kind, "identity_mismatch", version=version, sha256=calculated
        )
    model_project_id = getattr(model, "project_id", None)
    if model_project_id is not None and (
        model_project_id != project_id
        or payload.get("project_id") != project_id
    ):
        return _safe_problem(
            source_kind, "cross_project_reference",
            version=version, sha256=calculated,
        )
    return TraceSourceDescriptor(
        source_kind=source_kind,
        validation_state="present",
        schema_version=version,
        content_sha256=calculated,
    )


def conservative_trace_from_snapshots(
    *,
    project_id: str,
    db_snapshot: TraceDbSnapshot,
    file_sources: Mapping[str, TraceSourceDescriptor],
) -> ExecutionTraceBundle:
    """Build an incomplete, non-authoritative v1 trace from private snapshots.

    A public exporter MUST NOT call this on a live run before revalidating a
    consistent DB+file snapshot, safe config project identity and WAL policy.
    The result is always incomplete/inconsistent with ZERO assessments.
    """
    expected = set(_PARSERS)
    if not set(file_sources) <= expected:
        raise ValueError("Unexpected source kind.")
    if any(kind != value.source_kind for kind, value in file_sources.items()):
        raise ValueError("Source-kind binding mismatch.")
    core = [
        TraceSourceDescriptor(
            source_kind="run_record",
            validation_state="present",
            content_sha256=db_snapshot.run_record_sha256,
        ),
        TraceSourceDescriptor(
            source_kind="run_manifest",
            validation_state="present",
            schema_version=db_snapshot.run_manifest_version,
            content_sha256=db_snapshot.run_manifest_sha256,
        ),
        TraceSourceDescriptor(
            source_kind="run_event_stream",
            validation_state="present",
            content_sha256=db_snapshot.event_stream_sha256,
        ),
    ]
    sources = sorted([*core, *file_sources.values()], key=lambda x: x.source_kind)
    findings = sorted(
        (
            TraceFinding(reason_code=item.reason_code, source_kind=item.source_kind)
            for item in file_sources.values()
            if item.validation_state != "present" and item.reason_code is not None
        ),
        key=lambda x: (x.reason_code, x.source_kind or ""),
    )
    inconsistent = any(
        item.validation_state in {"invalid", "stale"}
        for item in file_sources.values()
    )
    # Do not infer "complete" even if every optional source parses. Parent
    # digest lineage and a cross-database/filesystem snapshot are unproven.
    return ExecutionTraceBundle(
        project_id=project_id,
        run_id=db_snapshot.run_id,
        observed_run_status=db_snapshot.observed_status,
        completeness="inconsistent" if inconsistent else "incomplete",
        sources=sources,
        events=list(db_snapshot.events),
        findings=findings,
        assessments=[],
    )
