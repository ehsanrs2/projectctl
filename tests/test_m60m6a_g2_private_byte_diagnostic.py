"""G2 private byte-only, non-authoritative diagnostic experiments.

No real ProjectCTL source. The existing B-Diagnostic synthetic _source()
creates all fixtures inside tmp_path; only the TEST acquires file bytes.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from scripts.m6a_g2_private_byte_diagnostic import (
    G2Refused, inspect_untrusted_supplied_bytes,
)
from scripts.bdiag_detached_input_lab import RUN, PROJECT
from test_m60bdiag_detached_input_gate import _source, _SECRET

_CONTEXT = "context-manifest.json"


def _bytes(tmp_path: Path):
    root = _source(tmp_path)
    db = (root / ".projectctl/state.sqlite").read_bytes()
    context = (root / ".projectctl/runs" / RUN / _CONTEXT).read_bytes()
    return db, {"context_manifest": context,
                "verification_manifest": None, "evidence_manifest": None}


def _inspect(db: bytes, files: dict):
    return inspect_untrusted_supplied_bytes(
        db_bytes=db, run_id=RUN, project_id=PROJECT,
        artifact_bytes=files,
    )


def test_incomplete_deterministic_bytes_only_trace_reuses_v1_contract(tmp_path):
    db, files = _bytes(tmp_path)
    a, b = _inspect(db, files), _inspect(db, files)
    assert a == b
    assert a.decision == "M6A_OFFLINE_DIAGNOSTIC_INCOMPLETE_ONLY"
    trace = json.loads(a.canonical_trace)
    assert a.completeness == trace["completeness"] == "incomplete"
    assert trace["assessments"] == []
    assert trace["run_id"] == RUN
    assert trace["events"][0]["category"] == "unclassified"
    assert trace["sources"] == sorted(
        trace["sources"], key=lambda item: item["source_kind"]
    )
    assert not any((
        a.source_origin_proven, a.cross_store_epoch_proven,
        a.source_capture_nonmutation_proven, a.authenticated_custody_proven,
        a.current_state_proven, a.authorizes_export_cli, a.authorizes_retry,
    ))
    for secret in (
        _SECRET.encode(), b"/private/source/with/token",
        b"worker.secret_untrusted", b"PRIVATE_DO_NOT_EXPORT",
    ):
        assert secret not in a.canonical_trace
    assert a.canonical_trace.endswith(b"\n")


def test_source_directory_gone_after_caller_reads_all_bytes(tmp_path):
    import shutil
    db, files = _bytes(tmp_path)
    shutil.rmtree(tmp_path / "synthetic-source")
    assert _inspect(db, files).completeness == "incomplete"


def test_invalid_context_never_upgrades_to_complete_or_supported(tmp_path):
    db, files = _bytes(tmp_path)
    files["context_manifest"] = (
        b'{"schema_kind":"projectctl.context_manifest",'
        b'"schema_version":1,"task_id":"x","task_id":"y"}'
    )
    observed = _inspect(db, files)
    trace = json.loads(observed.canonical_trace)
    assert trace["completeness"] == "inconsistent"
    assert trace["assessments"] == []
    assert any(v["source_kind"] == "context_manifest"
               and v["validation_state"] == "invalid"
               for v in trace["sources"])


@pytest.mark.parametrize("broken", [
    {},
    {"context_manifest": None},
    {"context_manifest": None, "verification_manifest": None,
     "evidence_manifest": None, "extra": b"secret"},
])
def test_exact_artifact_set_required(tmp_path, broken):
    db, _ = _bytes(tmp_path)
    with pytest.raises(G2Refused, match="INVALID_ARTIFACT_SET"):
        _inspect(db, broken)


@pytest.mark.parametrize("incorrect", [
    "../run", " run", "", "bad/slash", "*"
])
def test_unsafe_run_id_refused_before_sqlite(tmp_path, incorrect, monkeypatch):
    db, files = _bytes(tmp_path)

    def no_connect(*args, **kwargs):
        raise AssertionError("must refuse before SQLite memory connection")

    monkeypatch.setattr(sqlite3, "connect", no_connect)
    with pytest.raises(G2Refused, match="INVALID_IDENTITY"):
        inspect_untrusted_supplied_bytes(
            db_bytes=db, run_id=incorrect, project_id=PROJECT,
            artifact_bytes=files,
        )


@pytest.mark.parametrize("input_db", [
    b"", b"hello", b"SQLite format 3\x00",
    b"SQLite format 3\x00" + b"\x00" * 1024,
])
def test_malformed_db_refused(input_db, tmp_path):
    _, files = _bytes(tmp_path)
    with pytest.raises(G2Refused):
        _inspect(input_db, files)


def test_real_disposable_wal_header_refused_without_sqlite_memory_open(tmp_path, monkeypatch):
    db_file = tmp_path / "wal-fixture.sqlite"
    conn = sqlite3.connect(db_file)
    try:
        assert conn.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"
        conn.execute("CREATE TABLE fixture(x)")
        conn.execute("INSERT INTO fixture VALUES(1)")
        conn.commit()
        raw = db_file.read_bytes()
        assert raw[18:20] == b"\x02\x02"
    finally:
        conn.close()
    _, files = _bytes(tmp_path)
    original_connect = sqlite3.connect

    def no_connect(*args, **kwargs):
        raise AssertionError("WAL rejected before connection")

    monkeypatch.setattr(sqlite3, "connect", no_connect)
    try:
        with pytest.raises(G2Refused, match="UNSUPPORTED_WAL_INPUT"):
            _inspect(raw, files)
    finally:
        monkeypatch.setattr(sqlite3, "connect", original_connect)


def test_missing_run_is_not_a_fake_current_status(tmp_path):
    db, files = _bytes(tmp_path)
    with pytest.raises(G2Refused, match="MISSING_RUN"):
        inspect_untrusted_supplied_bytes(
            db_bytes=db, run_id="another-run",
            project_id=PROJECT, artifact_bytes=files,
        )


def test_private_byte_composer_has_no_path_or_cli_argument():
    import inspect
    from scripts import m6a_g2_private_byte_diagnostic as m
    signature = inspect.signature(m.inspect_untrusted_supplied_bytes)
    assert set(signature.parameters) == {
        "db_bytes", "run_id", "project_id", "artifact_bytes"
    }
    source = Path(m.__file__).read_text(encoding="utf-8")
    for forbidden in ("os.open(", "sqlite3.connect(uri", "requests.", "httpx.",
                      "subprocess.", "codex_sdk", "typer.", "click."):
        assert forbidden not in source
