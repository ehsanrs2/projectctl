from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from projectctl.core.enums import ModelProfile, ReasoningLevel, RunStatus
from projectctl.schemas.run import RunManifest, RunManifestV1, WorkerDescriptor
from projectctl.storage.sqlite import initialize_project_state_db
from projectctl.trace.snapshot import (
    MAX_ARTIFACT_BYTES,
    MAX_RUN_EVENTS,
    TraceSnapshotError,
    read_run_artifact,
    read_run_db_snapshot,
)

pytestmark = pytest.mark.skipif(
    os.name != "posix", reason="B1 no-follow descriptor policy currently POSIX only"
)
NOW = datetime(2026, 10, 13, 7, tzinfo=timezone.utc)


def _worker():
    return WorkerDescriptor(
        provider="codex",
        model_profile=ModelProfile.BALANCED,
        reasoning=ReasoningLevel.MEDIUM,
    )


def _manifest(version: int = 2):
    fields = dict(run_id="run-1", task_id="task-1", worker=_worker())
    if version == 1:
        return RunManifestV1(**fields)
    return RunManifest(
        **fields, execution_plan_digest="plan-digest",
        base_commit="deadbeef", branch_name="run-run-1",
        worktree_id="worktree-run-1",
    )


def _fixture(tmp_path: Path, *, version: int = 2, with_event: bool = True):
    d = tmp_path / ".projectctl"
    d.mkdir()
    db = d / "state.sqlite"
    initialize_project_state_db(db)
    conn = sqlite3.connect(db)
    # Cold, ordinary rollback-journal fixture. WAL is tested separately.
    conn.execute("PRAGMA journal_mode=DELETE")
    manifest = _manifest(version)
    payload = json.dumps(manifest.model_dump(mode="json"), sort_keys=True)
    conn.execute(
        "INSERT INTO runs (run_id,task_id,status,execution_plan_digest,"
        "base_commit,branch_name,worktree_id,worktree_path,worker_provider,"
        "created_at,manifest_json) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        ("run-1", "task-1", "planned", "plan-digest",
         "deadbeef", "run-run-1", "worktree-run-1",
         "/private/home/worker", "codex", NOW.isoformat(), payload),
    )
    if with_event:
        conn.execute(
            "INSERT INTO run_events(run_id,created_at,event_type,payload_json) "
            "VALUES(?,?,?,?)",
            ("run-1", NOW.isoformat(), "run.created",
             json.dumps({"prompt": "SECRET_EVENT_PAYLOAD", "token": "SECRET123"})),
        )
    conn.commit()
    conn.close()
    return db


def _state(db: Path):
    result = {}
    for p in (db, Path(str(db) + "-wal"), Path(str(db) + "-shm")):
        if p.exists():
            result[p.name] = p.read_bytes()
    return result


def test_read_db_snapshot_on_cold_db_is_nonmutating_and_deterministic(tmp_path):
    db = _fixture(tmp_path)
    before = _state(db)
    first = read_run_db_snapshot(tmp_path, "run-1")
    second = read_run_db_snapshot(tmp_path, "run-1")
    assert _state(db) == before
    assert first == second
    assert first.run_manifest_version == 2
    assert first.observed_status == RunStatus.PLANNED
    assert first.events[0].category == "lifecycle"
    assert first.events[0].occurred_at == NOW
    assert "SECRET_EVENT_PAYLOAD" not in repr(first)
    assert "/private/home" not in repr(first)
    assert first.run_record_sha256 != first.run_manifest_sha256


def test_historical_run_manifest_v1_uses_its_own_model(tmp_path):
    db = _fixture(tmp_path, version=1)
    original = _state(db)
    result = read_run_db_snapshot(tmp_path, "run-1")
    assert result.run_manifest_version == 1
    assert _state(db) == original


def test_missing_db_and_unknown_run_cannot_create_storage(tmp_path):
    with pytest.raises(TraceSnapshotError) as e:
        read_run_db_snapshot(tmp_path, "run-1")
    assert e.value.reason_code in {"unsafe_source_path", "source_unreadable"}
    assert not (tmp_path / ".projectctl").exists()

    db = _fixture(tmp_path)
    before = _state(db)
    with pytest.raises(TraceSnapshotError) as e:
        read_run_db_snapshot(tmp_path, "run-absent")
    assert e.value.reason_code == "missing_source"
    assert _state(db) == before


@pytest.mark.parametrize("run_id", [
    "../etc", "a/b", "/tmp/file", ".", "..", "a\\b", "",
    "run-1\x00evil", "secret@example.org",
])
def test_run_id_path_traversal_and_control_strings_rejected_without_io(
    tmp_path, run_id
):
    with pytest.raises(TraceSnapshotError) as e:
        read_run_db_snapshot(tmp_path, run_id)
    assert e.value.reason_code == "unsafe_source_path"
    assert not (tmp_path / ".projectctl").exists()


def test_db_or_internal_directory_symlink_rejected(tmp_path):
    external = tmp_path / "external.sqlite"
    external.write_bytes(b"private")
    (tmp_path / ".projectctl").symlink_to(tmp_path)
    with pytest.raises(TraceSnapshotError):
        read_run_db_snapshot(tmp_path, "run-1")
    assert external.read_bytes() == b"private"

    (tmp_path / ".projectctl").unlink()
    (tmp_path / ".projectctl").mkdir()
    (tmp_path / ".projectctl" / "state.sqlite").symlink_to(external)
    with pytest.raises(TraceSnapshotError):
        read_run_db_snapshot(tmp_path, "run-1")
    assert external.read_bytes() == b"private"


def test_db_event_limit_refuses_silent_truncation(tmp_path):
    db = _fixture(tmp_path, with_event=False)
    conn = sqlite3.connect(db)
    conn.executemany(
        "INSERT INTO run_events(run_id,created_at,event_type,payload_json) "
        "VALUES(?,?,?,?)",
        [("run-1", NOW.isoformat(), "worker.payload",
          json.dumps({"secret": f"TOKEN_{i}"}))
         for i in range(MAX_RUN_EVENTS + 1)],
    )
    conn.commit()
    conn.close()
    with pytest.raises(TraceSnapshotError) as e:
        read_run_db_snapshot(tmp_path, "run-1")
    assert e.value.reason_code == "source_unreadable"


def test_corrupt_manifest_never_falls_back_to_current_schema(tmp_path):
    db = _fixture(tmp_path)
    conn = sqlite3.connect(db)
    doc = {"schema_kind": "projectctl.run_manifest", "schema_version": 99}
    conn.execute("UPDATE runs SET manifest_json=? WHERE run_id='run-1'",
                 (json.dumps(doc),))
    conn.commit()
    conn.close()
    with pytest.raises(TraceSnapshotError) as e:
        read_run_db_snapshot(tmp_path, "run-1")
    assert e.value.reason_code == "unsupported_schema"


def test_run_manifest_identity_mismatch_is_fail_closed(tmp_path):
    db = _fixture(tmp_path)
    conn = sqlite3.connect(db)
    model = _manifest().model_dump(mode="json")
    model["task_id"] = "different-task"
    conn.execute("UPDATE runs SET manifest_json=? WHERE run_id='run-1'",
                 (json.dumps(model),))
    conn.commit()
    conn.close()
    with pytest.raises(TraceSnapshotError) as e:
        read_run_db_snapshot(tmp_path, "run-1")
    assert e.value.reason_code == "identity_mismatch"


def test_fixed_artifact_locator_is_nonmutating_and_nofollow(tmp_path):
    run = tmp_path / ".projectctl" / "runs" / "run-1"
    run.mkdir(parents=True)
    file = run / "evidence-manifest.json"
    secret_bytes = b'{"safe":true,"raw_prompt":"MUST_NOT_EXPORT"}\n'
    file.write_bytes(secret_bytes)
    before = file.read_bytes()
    result = read_run_artifact(tmp_path, "run-1", "evidence_manifest")
    assert result is not None
    assert result.raw_bytes == before
    assert result.content_sha256 == hashlib.sha256(before).hexdigest()
    assert "MUST_NOT_EXPORT" not in repr(result)
    assert file.read_bytes() == before
    assert read_run_artifact(tmp_path, "run-1", "publication_manifest") is None


def test_symlinked_artifact_or_parent_is_rejected_not_followed(tmp_path):
    run = tmp_path / ".projectctl" / "runs" / "run-1"
    run.mkdir(parents=True)
    external = tmp_path / "outside-secret"
    external.write_text("DO_NOT_READ")
    (run / "evidence-manifest.json").symlink_to(external)
    with pytest.raises(TraceSnapshotError):
        read_run_artifact(tmp_path, "run-1", "evidence_manifest")

    # Same rejection for directory components.
    (tmp_path / ".projectctl" / "runs" / "run-2").symlink_to(run)
    with pytest.raises(TraceSnapshotError):
        read_run_artifact(tmp_path, "run-2", "evidence_manifest")
    assert external.read_text() == "DO_NOT_READ"


def test_oversized_artifact_and_invalid_source_kind_rejected(tmp_path):
    run = tmp_path / ".projectctl" / "runs" / "run-1"
    run.mkdir(parents=True)
    (run / "evidence-manifest.json").write_bytes(b"x" * (MAX_ARTIFACT_BYTES + 1))
    with pytest.raises(TraceSnapshotError):
        read_run_artifact(tmp_path, "run-1", "evidence_manifest")
    with pytest.raises(TraceSnapshotError):
        read_run_artifact(tmp_path, "run-1", "../../outside")


def test_file_reader_does_not_create_missing_project_or_run_dirs(tmp_path):
    with pytest.raises(TraceSnapshotError) as e:
        read_run_artifact(tmp_path, "run-1", "worker_result")
    assert e.value.reason_code == "unsafe_source_path"
    assert not (tmp_path / ".projectctl").exists()


def test_reader_rejects_unsupported_db_version_without_upgrading(tmp_path):
    db = _fixture(tmp_path)
    conn = sqlite3.connect(db)
    conn.execute("PRAGMA user_version=999")
    conn.close()
    before = _state(db)
    with pytest.raises(TraceSnapshotError) as e:
        read_run_db_snapshot(tmp_path, "run-1")
    assert e.value.reason_code == "invalid_content"
    assert _state(db) == before
