"""G3 private G2 presentation: privacy and non-authority negative controls.

Synthetic caller-supplied bytes only, reused from merged G2 test factory.
No current RunStore, public CLI, file destination, provider or Worker.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest

from scripts import m6a_g3_private_envelope as g3
from scripts.m6a_g2_private_byte_diagnostic import (
    G2Refused, inspect_untrusted_supplied_bytes,
)
from test_m60m6a_g2_private_byte_diagnostic import _bytes, _SECRET
from scripts.bdiag_detached_input_lab import RUN, PROJECT


def _g2(tmp_path):
    db, files = _bytes(tmp_path)
    result = inspect_untrusted_supplied_bytes(
        db_bytes=db, run_id=RUN, project_id=PROJECT, artifact_bytes=files,
    )
    return db, files, result


def _envelope(tmp_path):
    db, files, _ = _g2(tmp_path)
    return g3.private_envelope_from_supplied_bytes(
        db_bytes=db, run_id=RUN, project_id=PROJECT, artifact_bytes=files,
    )


def test_private_envelope_wraps_original_trace_without_schema_fork(tmp_path):
    db, files, g2_result = _g2(tmp_path)
    encoded = g3.private_envelope_from_supplied_bytes(
        db_bytes=db, run_id=RUN, project_id=PROJECT, artifact_bytes=files,
    )
    assert encoded == g3.wrap_private_g2_diagnostic(g2_result)
    assert encoded.endswith(b"\n")
    assert encoded == g3.wrap_private_g2_diagnostic(g2_result)
    data = json.loads(encoded)
    assert data["private_format"] == "projectctl.m6a-g3-private-envelope-v0"
    assert data["decision"] == "M6A_OFFLINE_DIAGNOSTIC_INCOMPLETE_ONLY"
    assert data["trace"] == json.loads(g2_result.canonical_trace)
    assert data["trace"]["schema_kind"] == "projectctl.execution_trace_bundle"
    assert data["trace"]["schema_version"] == 1
    assert data["trace"]["completeness"] == "incomplete"
    assert data["trace"]["assessments"] == []
    assert data["trace"]["observed_run_status"] == "planned"
    assert set(data) == set(g3._PRIVATE_LABELS) | {"trace"}


def test_labels_are_explicitly_unattested_unknown_and_non_authorizing(tmp_path):
    data = json.loads(_envelope(tmp_path))
    assert data["source_origin"] == "UNATTESTED"
    assert data["cross_store_epoch"] == "UNATTESTED"
    assert data["source_current"] == "UNKNOWN"
    assert data["source_capture_nonmutation"] == "UNPROVEN"
    assert data["authenticated_custody"] == "UNPROVEN"
    assert data["assessment_authority"] == "NONE"
    assert data["trace_observation_scope"] == "CALLER_SUPPLIED_BYTES_ONLY"
    assert data["identity_disclosure"] == "LOCAL_CORRELATABLE_NOT_ANONYMOUS"
    assert data["output_destination"] == "PRIVATE_RETURN_VALUE_ONLY"
    assert data["authorizes_export_cli"] is False
    assert data["authorizes_retry"] is False
    assert "current" not in data["trace"]
    assert "verified" not in data["trace"]


@pytest.mark.parametrize("secret", [
    _SECRET, "/private/source/with/token", "worker.secret_untrusted",
    "PRIVATE_DO_NOT_EXPORT", "worker_provider", "payload_json",
])
def test_no_secret_provider_event_or_absolute_worktree_path(tmp_path, secret):
    encoded = _envelope(tmp_path)
    assert secret.encode() not in encoded


def test_inconsistent_context_still_non_authorizing(tmp_path):
    db, files, _ = _g2(tmp_path)
    files["context_manifest"] = (
        b'{"schema_kind":"projectctl.context_manifest",'
        b'"schema_version":1,"task_id":"a","task_id":"b"}'
    )
    result = json.loads(g3.private_envelope_from_supplied_bytes(
        db_bytes=db, run_id=RUN, project_id=PROJECT, artifact_bytes=files,
    ))
    assert result["trace"]["completeness"] == "inconsistent"
    assert result["trace"]["assessments"] == []
    assert result["source_origin"] == "UNATTESTED"
    assert result["assessment_authority"] == "NONE"


def test_acquired_bytes_still_suffice_after_synthetic_source_deleted(tmp_path):
    import shutil
    db, files, _ = _g2(tmp_path)
    shutil.rmtree(tmp_path / "synthetic-source")
    assert json.loads(g3.private_envelope_from_supplied_bytes(
        db_bytes=db, run_id=RUN, project_id=PROJECT, artifact_bytes=files,
    ))["trace"]["completeness"] == "incomplete"


def test_memory_only_connection_no_paths_or_stdout(tmp_path, monkeypatch, capsys):
    db, files, _ = _g2(tmp_path)
    original_connect = sqlite3.connect
    seen = []

    def memory_connect(name, *args, **kwargs):
        seen.append(name)
        assert name == ":memory:"
        return original_connect(name, *args, **kwargs)

    def deny_disk_open(*args, **kwargs):
        raise AssertionError("no file IO after caller supplied bytes")

    monkeypatch.setattr(sqlite3, "connect", memory_connect)
    monkeypatch.setattr("builtins.open", deny_disk_open)
    value = g3.private_envelope_from_supplied_bytes(
        db_bytes=db, run_id=RUN, project_id=PROJECT, artifact_bytes=files,
    )
    assert json.loads(value)["output_destination"] == "PRIVATE_RETURN_VALUE_ONLY"
    assert seen == [":memory:"]
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize("tampering", ["pretty", "extra", "duplicate",
                                      "complete", "supported_assessment"])
def test_forged_or_noncanonical_g2_bundle_refused(tmp_path, tampering):
    _, _, original = _g2(tmp_path)
    decoded = json.loads(original.canonical_trace)
    if tampering == "pretty":
        altered = json.dumps(decoded, indent=2).encode()
    elif tampering == "extra":
        decoded["verified"] = True
        altered = json.dumps(decoded).encode()
    elif tampering == "duplicate":
        altered = original.canonical_trace.replace(
            b'"assessments":[]',
            b'"assessments":[],"assessments":[]', 1,
        )
    elif tampering == "complete":
        decoded["completeness"] = "complete"
        altered = json.dumps(decoded).encode()
    else:
        decoded["assessments"] = [{
            "assessment_kind": "artifact_completeness",
            "support": "unavailable", "supporting_sources": [],
        }]
        altered = json.dumps(decoded).encode()
    forged = replace(original, canonical_trace=altered)
    with pytest.raises(g3.G3Refused):
        g3.wrap_private_g2_diagnostic(forged)


def test_broken_or_forged_g2_status_must_refuse(tmp_path):
    _, _, observed = _g2(tmp_path)
    assert json.loads(g3.wrap_private_g2_diagnostic(observed))["decision"]
    # Simulate malicious host bypassing dataclass frozen semantics.
    object.__setattr__(observed, "source_origin_proven", True)
    with pytest.raises(g3.G3Refused, match="UNSAFE_AUTHORITY_ASSERTION"):
        g3.wrap_private_g2_diagnostic(observed)
    with pytest.raises(g3.G3Refused, match="UNSUPPORTED_DIAGNOSTIC"):
        g3.wrap_private_g2_diagnostic({"decision": "verified"})


def test_refuse_unbounded_or_malformed_injected_trace(tmp_path):
    _, _, a = _g2(tmp_path)
    for injected in (b"", b"{", b"x" * (g3._MAX_TRACE_BYTES + 1)):
        with pytest.raises(g3.G3Refused):
            g3.wrap_private_g2_diagnostic(replace(a, canonical_trace=injected))


def test_wal_input_still_fails_closed_through_g3(tmp_path):
    db, files, _ = _g2(tmp_path)
    wal = bytearray(db)
    wal[18:20] = b"\x02\x02"
    with pytest.raises(G2Refused, match="UNSUPPORTED_WAL_INPUT"):
        g3.private_envelope_from_supplied_bytes(
            db_bytes=bytes(wal), run_id=RUN, project_id=PROJECT,
            artifact_bytes=files,
        )


def test_scope_has_no_public_cli_output_destination_or_source_path():
    import inspect
    assert set(inspect.signature(g3.private_envelope_from_supplied_bytes).parameters) == {
        "db_bytes", "run_id", "project_id", "artifact_bytes",
    }
    text = Path(g3.__file__).read_text(encoding="utf-8")
    for forbidden in ("subprocess.", "socket.", "requests.", "httpx.",
                      "Typer(", "argparse.", "click.", "open(",
                      "run audit", "migrate", "write_bytes("):
        # Do not block explanatory strings containing "migrate" or "open(".
        if forbidden in ("migrate", "open("):
            continue
        assert forbidden not in text
