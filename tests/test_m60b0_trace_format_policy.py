from __future__ import annotations

import hashlib
import json

import pytest

from projectctl.core.enums import RunStatus
from projectctl.schemas.trace import ExecutionTraceBundle, TraceSourceDescriptor
from projectctl.trace.format import canonical_trace_json_bytes, trace_event_category


def _bundle() -> ExecutionTraceBundle:
    return ExecutionTraceBundle(
        project_id="demo-project",
        run_id="run-1",
        observed_run_status=RunStatus.RUNNING,
        completeness="incomplete",
        sources=[
            TraceSourceDescriptor(
                source_kind="run_record",
                validation_state="present",
                content_sha256=hashlib.sha256(b"run-row").hexdigest(),
            ),
        ],
    )


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("run.created", "lifecycle"),
        ("task.claim.transition_validated", "claim"),
        ("task.claim.unresolved", "claim"),
        ("publication.requested", "delivery"),
        ("review.requested", "delivery"),
        ("run.secret", "unclassified"),
        ("run.created.payload=SECRET", "unclassified"),
        ("", "unclassified"),
        ("SECRET_TOKEN_123", "unclassified"),
        ("worker.payload", "unclassified"),
    ],
)
def test_event_category_is_exact_allowlist_not_raw_event_echo(raw, expected):
    result = trace_event_category(raw)
    assert result == expected
    assert "SECRET" not in result


def test_trace_serialization_is_stable_and_lossless_for_allowed_fields():
    trace = _bundle()
    first = canonical_trace_json_bytes(trace)
    second = canonical_trace_json_bytes(trace)
    assert first == second
    assert first.endswith(b"\n") and not first.endswith(b"\n\n")
    assert first.count(b"\n") == 1
    assert json.loads(first) == trace.model_dump(mode="json")
    assert first == canonical_trace_json_bytes(
        ExecutionTraceBundle.model_validate_json(first)
    )


def test_trusted_output_shape_not_an_arbitrary_dict():
    with pytest.raises(TypeError, match="validated ExecutionTraceBundle"):
        canonical_trace_json_bytes({
            "run_id": "demo", "prompt": "API_TOKEN_SECRET"
        })  # type: ignore[arg-type]


def test_serialization_does_not_append_secrets_or_machine_fields():
    output = canonical_trace_json_bytes(_bundle())
    for blocked in (
        b"prompt", b"stdout", b"stderr", b"lease_owner", b"worktree_path",
        b"provider_payload", b"worker_thread_id", b"generated_at",
        b"actor", b"event_type", b"payload_json",
    ):
        assert blocked not in output
    assert output.startswith(b'{"assessments":')
    assert output.endswith(b"\n")


def test_bundle_outside_privacy_allowlist_remains_unrepresentable():
    value = _bundle().model_dump(mode="json")
    value["raw_event"] = "AKIA_NOT_A_REAL_KEY"
    with pytest.raises(Exception):
        ExecutionTraceBundle.model_validate(value)
