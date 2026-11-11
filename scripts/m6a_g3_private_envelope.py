"""M6a G3: private, non-authorizing presentation of G2's supplied-byte Trace.

Research-only interface. Neither this wrapper nor G2 reads a source path,
writes output, registers a CLI, asserts a real source epoch or grants
verification/retry/Worker authority. This is NOT a public schema.
"""
from __future__ import annotations

import json
from collections.abc import Mapping

from pydantic import ValidationError

from projectctl.schemas.trace import ExecutionTraceBundle
from projectctl.trace.format import canonical_trace_json_bytes
from scripts.m6a_g2_private_byte_diagnostic import (
    G2Diagnostic,
    inspect_untrusted_supplied_bytes,
)

_DECISION = "M6A_OFFLINE_DIAGNOSTIC_INCOMPLETE_ONLY"
_MAX_TRACE_BYTES = 256 * 1024
_MAX_ENVELOPE_BYTES = 288 * 1024

# All provenance/status claims are fixed constants; no caller/provider text
# can override them, including "authoritative", "current", or "verified".
_PRIVATE_LABELS = {
    "private_format": "projectctl.m6a-g3-private-envelope-v0",
    "decision": _DECISION,
    "source_origin": "UNATTESTED",
    "cross_store_epoch": "UNATTESTED",
    "source_current": "UNKNOWN",
    "source_capture_nonmutation": "UNPROVEN",
    "authenticated_custody": "UNPROVEN",
    "assessment_authority": "NONE",
    "trace_observation_scope": "CALLER_SUPPLIED_BYTES_ONLY",
    "identity_disclosure": "LOCAL_CORRELATABLE_NOT_ANONYMOUS",
    "output_destination": "PRIVATE_RETURN_VALUE_ONLY",
    "authorizes_export_cli": False,
    "authorizes_retry": False,
}


class G3Refused(ValueError):
    """Fixed error code, with no path, payload, token or exception details."""


def _unique_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_key")
        result[key] = value
    return result


def wrap_private_g2_diagnostic(diagnostic: G2Diagnostic) -> bytes:
    """Return deterministic private envelope; never a bare public Trace.

    Incoming Trace must already be canonical v1, incomplete/inconsistent,
    assessment-free and explicitly unauthorized. A fabricated or modified
    G2 result is REFUSED, not silently relabelled as a current Run.
    """
    if type(diagnostic) is not G2Diagnostic:
        raise G3Refused("UNSUPPORTED_DIAGNOSTIC")
    if (diagnostic.decision != _DECISION or
            diagnostic.completeness not in ("incomplete", "inconsistent") or
            any((
                diagnostic.source_origin_proven,
                diagnostic.cross_store_epoch_proven,
                diagnostic.source_capture_nonmutation_proven,
                diagnostic.authenticated_custody_proven,
                diagnostic.current_state_proven,
                diagnostic.authorizes_export_cli,
                diagnostic.authorizes_retry,
            ))):
        raise G3Refused("UNSAFE_AUTHORITY_ASSERTION")
    raw = diagnostic.canonical_trace
    if (type(raw) is not bytes or len(raw) < 1
            or len(raw) > _MAX_TRACE_BYTES):
        raise G3Refused("INVALID_OR_UNBOUNDED_TRACE")
    try:
        decoded = json.loads(raw, object_pairs_hook=_unique_pairs,
                             parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        trace = ExecutionTraceBundle.model_validate(decoded)
        if (canonical_trace_json_bytes(trace) != raw or
                trace.completeness != diagnostic.completeness or
                trace.completeness not in ("incomplete", "inconsistent") or
                trace.assessments):
            raise G3Refused("UNSAFE_OR_NONCANONICAL_TRACE")
    except G3Refused:
        raise
    except (ValueError, UnicodeError, TypeError, RecursionError, ValidationError):
        raise G3Refused("INVALID_TRACE") from None
    # Preserve the canonical v1 trace unchanged and embed it in an expressly
    # non-authorizing private wrapper. "present" and "observed_run_status"
    # describe caller-supplied bytes only, never current source truth.
    envelope: dict[str, object] = {**_PRIVATE_LABELS, "trace": decoded}
    encoded = (
        json.dumps(envelope, sort_keys=True, ensure_ascii=False,
                   separators=(",", ":"), allow_nan=False) + "\n"
    ).encode("utf-8")
    if len(encoded) > _MAX_ENVELOPE_BYTES:
        raise G3Refused("UNBOUNDED_ENVELOPE")
    return encoded


def private_envelope_from_supplied_bytes(
    *, db_bytes: bytes, run_id: str, project_id: str,
    artifact_bytes: dict[str, bytes | None],
) -> bytes:
    """PRIVATE test/research composition. No paths, stdout or file output."""
    return wrap_private_g2_diagnostic(inspect_untrusted_supplied_bytes(
        db_bytes=db_bytes, run_id=run_id, project_id=project_id,
        artifact_bytes=artifact_bytes,
    ))
