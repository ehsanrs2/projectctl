"""G4a opt-in offline preview tests: strictly disposable G2 fixture bytes.

No real project read. The only subprocess runs the NON-INSTALLED research
script with explicitly supplied in-memory stdin; neither test nor tool
changes ProjectCTL state.
"""
from __future__ import annotations

import base64
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import m6a_g4_stdin_preview as g4
from test_m60m6a_g2_private_byte_diagnostic import _bytes, _SECRET
from scripts.bdiag_detached_input_lab import PROJECT, RUN


def _document(tmp_path):
    db, files = _bytes(tmp_path)
    return {
        "format": g4._INPUT_FORMAT,
        "project_id": PROJECT,
        "run_id": RUN,
        "db_b64": base64.b64encode(db).decode("ascii"),
        "artifacts_b64": {
            kind: None if contents is None else
            base64.b64encode(contents).decode("ascii")
            for kind, contents in files.items()
        },
    }


def _wire(document):
    return (json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _run(raw, *args):
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run(
        [sys.executable, "-B", "-m", "scripts.m6a_g4_stdin_preview", *args],
        cwd=Path(__file__).resolve().parents[1], env=env,
        input=raw, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        timeout=20, check=False,
    )


def test_pure_renderer_deterministic_and_no_sensitive_fields(tmp_path):
    wire = _wire(_document(tmp_path))
    a = g4.render_supplied_wire(wire)
    b = g4.render_supplied_wire(wire)
    assert a == b and a.endswith(b"\n")
    doc = json.loads(a)
    assert doc["private_format"] == g4._OUTPUT_FORMAT
    assert doc["output_destination"] == "EXPLICIT_OPT_IN_STDOUT_LAB_ONLY"
    assert doc["source_origin"] == doc["cross_store_epoch"] == "UNATTESTED"
    assert doc["source_capture_nonmutation"] == "UNPROVEN"
    assert doc["source_current"] == "UNKNOWN"
    assert doc["authenticated_custody"] == "UNPROVEN"
    assert doc["assessment_authority"] == "NONE"
    assert doc["authorizes_export_cli"] is False
    assert doc["authorizes_retry"] is False
    assert doc["identity_disclosure"] == "LOCAL_CORRELATABLE_NOT_ANONYMOUS"
    assert doc["trace"]["completeness"] == "incomplete"
    assert doc["trace"]["assessments"] == []
    assert doc["trace"]["observed_run_status"] == "planned"
    assert doc["trace"]["run_id"] == RUN
    for secret in (_SECRET, "/private/source/with/token",
                   "worker.secret_untrusted", "payload_json"):
        assert secret.encode() not in a
    assert len(a) <= g4._OUTPUT_MAX


def test_real_standalone_entrypoint_ack_success_one_stdout_json(tmp_path):
    wire = _wire(_document(tmp_path))
    result = _run(wire, "--ack-local-correlatable")
    assert result.returncode == 0, result.stderr
    assert result.stderr == b""
    assert result.stdout == g4.render_supplied_wire(wire)
    assert result.stdout.count(b"\n") == 1


@pytest.mark.parametrize("args", [
    (), ("--help",), ("--output", "/tmp/file"),
    ("--ack-local-correlatable", "--output"), ("--ack",),
])
def test_no_ack_or_unexpected_flags_cannot_read_or_print_payload(tmp_path, args):
    result = _run(_wire(_document(tmp_path)), *args)
    assert result.returncode == 2
    assert result.stdout == b""
    assert result.stderr == b"G4_ACK_REQUIRED_OR_UNSUPPORTED_INVOCATION\n"


@pytest.mark.parametrize("malformed", [
    b"", b"{", b"not-json", b"\xff", b"[]", b"42",
    b'{"format": "hello", "format": "hello"}',
    b'{"x":1.0}', b'{"x":NaN}', b'{"x":5}',
])
def test_malformed_json_or_duplicates_refused_without_output(malformed):
    result = _run(malformed, "--ack-local-correlatable")
    assert result.returncode != 0
    assert result.stdout == b""
    assert result.stderr == b"G4_INPUT_REFUSED\n"


@pytest.mark.parametrize("bad", [
    {"format": "unknown"},
    {"source_origin": "VERIFIED"},
    {"output": "/tmp/danger"},
    {"artifacts_b64": []},
    {"artifacts_b64": {"context_manifest": None}},
    {"artifacts_b64": {
        "context_manifest": None,
        "verification_manifest": None,
        "evidence_manifest": None,
        "extra": None,
    }},
    {"project_id": 5},
    {"run_id": "../traversal"},
])
def test_unknown_fields_and_bad_contract_refused(tmp_path, bad):
    doc = _document(tmp_path)
    doc.update(bad)
    with pytest.raises((g4.G4Refused, ValueError)):
        g4.render_supplied_wire(_wire(doc))


@pytest.mark.parametrize("value", [
    "*", "😃", "Z", "Z==", "Zh==", # malformed or noncanonical pad bits
    "a" * 200,
])
def test_base64_incorrect_or_noncanonical_refused(tmp_path, value):
    doc = _document(tmp_path)
    doc["artifacts_b64"]["context_manifest"] = value
    with pytest.raises((g4.G4Refused, ValueError)):
        g4.render_supplied_wire(_wire(doc))


def test_no_file_read_or_source_sqlite_vfs_when_bytes_supplied(tmp_path, monkeypatch):
    doc = _document(tmp_path)
    real_connect = sqlite3.connect
    calls = []

    def guard_connect(filename, *args, **kwargs):
        calls.append(filename)
        assert filename == ":memory:"
        return real_connect(filename, *args, **kwargs)

    def deny_open(*_args, **_kwargs):
        raise AssertionError("file read is forbidden after supplied bytes")

    monkeypatch.setattr(sqlite3, "connect", guard_connect)
    monkeypatch.setattr("builtins.open", deny_open)
    monkeypatch.setattr(os, "open", deny_open)
    assert g4.render_supplied_wire(_wire(doc))
    assert calls == [":memory:"]


def test_corrupt_manifest_is_inconsistent_not_verified(tmp_path):
    doc = _document(tmp_path)
    corrupt = (
        b'{"schema_kind":"projectctl.context_manifest",'
        b'"schema_version":1,"task_id":"foo","task_id":"bar"}'
    )
    doc["artifacts_b64"]["context_manifest"] = base64.b64encode(corrupt).decode()
    observed = json.loads(g4.render_supplied_wire(_wire(doc)))
    assert observed["trace"]["completeness"] == "inconsistent"
    assert observed["trace"]["assessments"] == []
    assert observed["source_origin"] == "UNATTESTED"


def test_fake_wal_header_is_refused_not_fixed_or_recovered(tmp_path):
    doc = _document(tmp_path)
    raw = bytearray(base64.b64decode(doc["db_b64"]))
    raw[18:20] = b"\x02\x02"
    doc["db_b64"] = base64.b64encode(raw).decode("ascii")
    result = _run(_wire(doc), "--ack-local-correlatable")
    assert result.returncode != 0 and result.stdout == b""
    assert result.stderr == b"G4_INPUT_REFUSED\n"


def test_oversized_wire_is_refused_without_any_decode():
    with pytest.raises(g4.G4Refused, match="INVALID_OR_UNBOUNDED_WIRE"):
        g4.render_supplied_wire(b"x" * (g4._WIRE_MAX + 1))


def test_base64_declared_length_limit_rejects_without_decoding(tmp_path, monkeypatch):
    doc = _document(tmp_path)
    doc["artifacts_b64"]["context_manifest"] = (
        "A" * (4 * ((g4._ARTIFACT_MAX + 2) // 3) + 1)
    )
    def forbidden_decode(*args, **kwargs):
        raise AssertionError("oversized base64 must be refused before decoding")
    monkeypatch.setattr(base64, "b64decode", forbidden_decode)
    with pytest.raises(g4.G4Refused, match="INVALID_BASE64_LENGTH"):
        g4.render_supplied_wire(_wire(doc))


def test_refusal_contains_no_user_text_stderr(tmp_path):
    doc = _document(tmp_path)
    doc["run_id"] = "secret-unsafe/path-PRIVATE_TOKEN"
    result = _run(_wire(doc), "--ack-local-correlatable")
    assert result.returncode != 0 and result.stdout == b""
    assert result.stderr == b"G4_INPUT_REFUSED\n"
    assert b"PRIVATE_TOKEN" not in result.stderr


def test_source_can_be_deleted_before_consumer_uses_supplied_bytes(tmp_path):
    import shutil
    doc = _document(tmp_path)
    shutil.rmtree(tmp_path / "synthetic-source")
    assert json.loads(g4.render_supplied_wire(_wire(doc)))["source_origin"] == "UNATTESTED"


def test_no_runtime_or_public_cli_wiring():
    import inspect
    assert set(inspect.signature(g4.render_supplied_wire).parameters) == {"wire"}
    assert set(inspect.signature(g4.main).parameters) == {"argv"}
    text = Path(g4.__file__).read_text(encoding="utf-8")
    for forbidden in ("RunStore(", "connect_db(", "projectctl trace export",
                      "subprocess.", "socket.", "requests.", "httpx.",
                      "os.open(", "Path(", "write_bytes(", "click."):
        assert forbidden not in text
