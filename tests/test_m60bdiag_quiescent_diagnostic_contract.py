"""M6.0 B-Diagnostic: test-only offline rollback-journal read assembly.

This is NOT a Collector, public CLI, production offline admission proof, or
live-WAL Reader. SQLite may interact with source files; only disposable
fixtures constructed within pytest's private directory are opened.
"""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from projectctl.core.enums import ModelProfile, ReasoningLevel, RunStatus
from projectctl.schemas.run import ContextManifestV1, RunManifest, WorkerDescriptor
from projectctl.storage.sqlite import initialize_project_state_db
from projectctl.trace.format import canonical_trace_json_bytes
from projectctl.trace.snapshot import (
    TraceSnapshotError, read_run_artifact, read_run_db_snapshot,
)
from projectctl.trace.validate import (
    conservative_trace_from_snapshots, inspect_artifact_snapshot,
)


pytestmark = pytest.mark.skipif(
    os.name != "posix" or not hasattr(os, "O_NOFOLLOW"),
    reason="quiescent private fixture relies on POSIX no-follow checks",
)

_RUN = "run-bdiag"
_TASK = "task-bdiag"
_PROJECT = "bdiag-local"
_NOW = datetime(2026, 10, 19, 8, tzinfo=timezone.utc)
_SECRET = "DO_NOT_EXPORT_DIAGNOSTIC_SECRET_012345"


def _fixture(tmp_path: Path):
    """Only create disposable ProjectCTL v2 DB, not a live project."""
    store = tmp_path / "project"
    internal = store / ".projectctl"
    internal.mkdir(parents=True)
    db = internal / "state.sqlite"
    initialize_project_state_db(db)
    worker = WorkerDescriptor(
        provider="codex",
        model_profile=ModelProfile.BALANCED,
        reasoning=ReasoningLevel.MEDIUM,
    )
    manifest = RunManifest(
        run_id=_RUN, task_id=_TASK, worker=worker, status=RunStatus.PLANNED,
        execution_plan_digest="plan-fixture",
        base_commit="deadbeef",
        branch_name="run-bdiag", worktree_id="worktree-bdiag",
    )
    conn = sqlite3.connect(db)
    try:
        # Production normally uses WAL; the ONLY test-approved experimental
        # condition is a disconnected rollback-journal DB.
        assert conn.execute("PRAGMA journal_mode=DELETE").fetchone()[0] == "delete"
        conn.execute(
            "INSERT INTO runs (run_id,task_id,status,execution_plan_digest,"
            "base_commit,branch_name,worktree_id,worktree_path,worker_provider,"
            "created_at,manifest_json) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (
                _RUN, _TASK, "planned", "plan-fixture", "deadbeef",
                "run-bdiag", "worktree-bdiag", "/secret/home/worktree",
                "codex", _NOW.isoformat(),
                json.dumps(manifest.model_dump(mode="json"), sort_keys=True),
            ),
        )
        conn.execute(
            "INSERT INTO run_events(run_id,created_at,event_type,payload_json) "
            "VALUES (?,?,?,?)",
            (
                _RUN, _NOW.isoformat(), "worker.secret_unrecognized_type",
                json.dumps({"provider_key": _SECRET, "prompt": _SECRET}),
            ),
        )
        conn.commit()
    finally:
        conn.close()

    run_dir = internal / "runs" / _RUN
    run_dir.mkdir(parents=True)
    context = ContextManifestV1(task_id=_TASK, git_commit="deadbeef")
    (run_dir / "context-manifest.json").write_text(
        json.dumps(context.model_dump(mode="json"), sort_keys=True),
        encoding="utf-8",
    )
    assert not db.with_name("state.sqlite-wal").exists()
    assert not db.with_name("state.sqlite-shm").exists()
    return store, db, run_dir


def _fingerprint_files(root: Path):
    """Diagnostic content+basic metadata; sampling itself may update atime."""
    result = {}
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        st = path.lstat()
        result[str(path.relative_to(root))] = (
            path.read_bytes(), st.st_dev, st.st_ino, st.st_mode,
            st.st_size, st.st_mtime_ns, st.st_ctime_ns,
        )
    return result


def _assemble_test_only(root: Path):
    """Private fixture composition, deliberately NOT a public Collector."""
    db = read_run_db_snapshot(root, _RUN)
    file_kinds = ("context_manifest", "verification_manifest", "evidence_manifest")
    descriptors = {
        kind: inspect_artifact_snapshot(
            read_run_artifact(root, _RUN, kind),
            source_kind=kind, run_id=_RUN, task_id=db.task_id,
            project_id=_PROJECT,
        ) for kind in file_kinds
    }
    trace = conservative_trace_from_snapshots(
        project_id=_PROJECT, db_snapshot=db, file_sources=descriptors
    )
    return trace, canonical_trace_json_bytes(trace)


def test_quiescent_rollback_fixture_is_deterministic_non_authoritative(tmp_path):
    root, db, _ = _fixture(tmp_path)
    before = _fingerprint_files(root)
    first, first_bytes = _assemble_test_only(root)
    second, second_bytes = _assemble_test_only(root)
    after = _fingerprint_files(root)
    assert first_bytes == second_bytes
    assert before == after
    assert first.completeness == "incomplete"
    assert first.assessments == []
    assert first.observed_run_status == RunStatus.PLANNED
    assert {item.source_kind: item.validation_state for item in first.sources}[
        "context_manifest"
    ] == "present"
    assert b'"complete"' not in first_bytes
    assert _SECRET.encode() not in first_bytes
    assert b"/secret/home" not in first_bytes
    assert b"worker.secret_unrecognized_type" not in first_bytes
    assert b"provider_key" not in first_bytes
    assert first.events[0].category == "unclassified"
    assert not Path(str(db) + "-wal").exists()
    assert not Path(str(db) + "-shm").exists()


def test_disposable_dac_readonly_directory_not_modified(tmp_path):
    if not hasattr(os, "chmod"):
        pytest.skip("chmod unavailable")
    root, db, run_dir = _fixture(tmp_path)
    internal = root / ".projectctl"
    fixture_file = run_dir / "context-manifest.json"
    # Harden only disposable test-owned files and directories. This is not
    # an attestation that another owner or process cannot modify them.
    try:
        db.chmod(0o400)
        fixture_file.chmod(0o400)
        run_dir.chmod(0o500)
        internal.chmod(0o500)
        before = _fingerprint_files(root)
        trace, _ = _assemble_test_only(root)
        assert trace.completeness == "incomplete"
        assert before == _fingerprint_files(root)
        assert not Path(str(db) + "-journal").exists()
        assert not Path(str(db) + "-wal").exists()
        assert not Path(str(db) + "-shm").exists()
    finally:
        internal.chmod(0o700)
        run_dir.chmod(0o700)
        db.chmod(0o600)
        fixture_file.chmod(0o600)


def test_missing_artifacts_stay_missing_not_verification(tmp_path):
    root, _, run_dir = _fixture(tmp_path)
    (run_dir / "context-manifest.json").unlink()
    trace, encoded = _assemble_test_only(root)
    assert trace.completeness == "incomplete"
    assert trace.assessments == []
    source = {x.source_kind: x for x in trace.sources}
    assert source["context_manifest"].validation_state == "missing"
    assert source["verification_manifest"].validation_state == "missing"
    assert b"missing_source" in encoded


def test_corrupt_artifact_fails_to_inconsistent_without_raw_text_leak(tmp_path):
    root, _, run_dir = _fixture(tmp_path)
    (run_dir / "context-manifest.json").write_text(
        '{"schema_kind":"projectctl.context_manifest",'
        '"task_id":"'+_SECRET+'", "task_id":"'+_SECRET+'"}',
        encoding="utf-8",
    )
    trace, output = _assemble_test_only(root)
    assert trace.completeness == "inconsistent"
    assert trace.assessments == []
    assert _SECRET.encode() not in output
    source = {x.source_kind: x for x in trace.sources}
    assert source["context_manifest"].validation_state == "invalid"


def test_symlinked_artifact_rejected_not_reclassified_present(tmp_path):
    root, _, run_dir = _fixture(tmp_path)
    context = run_dir / "context-manifest.json"
    external = tmp_path / "external-secret.json"
    external.write_text(_SECRET, encoding="utf-8")
    context.unlink()
    context.symlink_to(external)
    with pytest.raises(TraceSnapshotError):
        _assemble_test_only(root)
    assert external.read_text(encoding="utf-8") == _SECRET


def test_symlinked_run_directory_fails_before_any_export(tmp_path):
    root, _, run_dir = _fixture(tmp_path)
    moved = tmp_path / "moved-run-dir"
    run_dir.rename(moved)
    run_dir.symlink_to(moved, target_is_directory=True)
    with pytest.raises(TraceSnapshotError):
        _assemble_test_only(root)
    assert (moved / "context-manifest.json").exists()


def test_active_wal_never_falls_back_to_experimental_vfs(tmp_path):
    root, db, _ = _fixture(tmp_path)
    writer = sqlite3.connect(db)
    try:
        assert writer.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"
        writer.execute("INSERT INTO run_events(run_id,created_at,event_type,payload_json) "
                       "VALUES (?,?,?,?)",
                       (_RUN, _NOW.isoformat(), "run.transition", json.dumps({"private": _SECRET})))
        writer.commit()
        before = _fingerprint_files(root)
        with pytest.raises(TraceSnapshotError, match="source_unreadable"):
            _assemble_test_only(root)
        assert before == _fingerprint_files(root)
    finally:
        writer.close()


def test_separate_external_file_is_not_frozen_by_sqlite_snapshot(tmp_path):
    """Even offline files can be swapped by an uncooperative same-UID actor."""
    root, _, run_dir = _fixture(tmp_path)
    first = read_run_db_snapshot(root, _RUN)
    target = run_dir / "context-manifest.json"
    replacement = ContextManifestV1(task_id=_TASK, git_commit="cafebabe")
    temp = run_dir / "new-context.tmp"
    temp.write_text(json.dumps(replacement.model_dump(mode="json")), encoding="utf-8")
    os.replace(temp, target)
    second = read_run_artifact(root, _RUN, "context_manifest")
    assert second is not None
    observed = inspect_artifact_snapshot(
        second, source_kind="context_manifest",
        run_id=_RUN, task_id=first.task_id, project_id=_PROJECT,
    )
    assert observed.validation_state == "present"
    # "present" validates one file; it is not an external quiescence
    # certificate or a DB+file as-of Seal.
    mixed = conservative_trace_from_snapshots(
        project_id=_PROJECT,
        db_snapshot=first,
        file_sources={"context_manifest": observed},
    )
    assert mixed.completeness == "incomplete"
    assert mixed.assessments == []


def test_no_current_production_collector_cli_or_db_version_bump():
    from projectctl.storage.sqlite import PROJECT_STATE_DB_VERSION
    assert PROJECT_STATE_DB_VERSION == 2
    import projectctl.cli.entry as entry
    assert not hasattr(entry, "register_trace")
    assert not hasattr(entry, "register_trace_export")
