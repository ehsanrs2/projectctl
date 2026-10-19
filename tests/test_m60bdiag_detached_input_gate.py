"""M6.0 detached-input gate: real disposable v2 rollback bytes only."""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from projectctl.core.enums import ModelProfile, ReasoningLevel, RunStatus
from projectctl.schemas.run import ContextManifestV1, RunManifest, WorkerDescriptor
from projectctl.storage.sqlite import initialize_project_state_db
from scripts import bdiag_detached_input_lab as lab

pytestmark = pytest.mark.skipif(
    os.name != "posix" or not hasattr(os, "O_NOFOLLOW")
    or os.getuid() == 0 or os.geteuid() == 0,
    reason="disposable Linux/POSIX nonroot private fixture only",
)

_SECRET = "PRIVATE_DO_NOT_EXPORT_DETACHED_123456"
_NOW = datetime(2026, 10, 19, 8, tzinfo=timezone.utc)


def _source(tmp_path: Path) -> Path:
    """Always created by test; never a user-selected project path."""
    src = tmp_path / "synthetic-source"
    internal = src / ".projectctl"
    run = internal / "runs" / lab.RUN
    run.mkdir(parents=True)
    db = internal / "state.sqlite"
    initialize_project_state_db(db)
    conn = sqlite3.connect(db)
    try:
        assert conn.execute("PRAGMA journal_mode=DELETE").fetchone()[0] == "delete"
        manifest = RunManifest(
            run_id=lab.RUN, task_id=lab.TASK, status=RunStatus.PLANNED,
            worker=WorkerDescriptor(
                provider="codex",
                model_profile=ModelProfile.BALANCED,
                reasoning=ReasoningLevel.MEDIUM,
            ),
            execution_plan_digest="plan-only",
            base_commit="deadbeef", branch_name="run-detached",
            worktree_id="worktree-detached",
        )
        conn.execute(
            "INSERT INTO runs(run_id,task_id,status,execution_plan_digest,"
            "base_commit,branch_name,worktree_id,worktree_path,worker_provider,"
            "created_at,manifest_json) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (lab.RUN, lab.TASK, "planned", "plan-only",
             "deadbeef", "run-detached", "worktree-detached",
             "/private/source/with/token", "codex", _NOW.isoformat(),
             json.dumps(manifest.model_dump(mode="json"), sort_keys=True)),
        )
        conn.execute(
            "INSERT INTO run_events(run_id,created_at,event_type,payload_json)"
            " VALUES(?,?,?,?)",
            (lab.RUN, _NOW.isoformat(), "worker.secret_untrusted",
             json.dumps({"prompt": _SECRET, "token": _SECRET})),
        )
        conn.commit()
    finally:
        conn.close()
    context = ContextManifestV1(task_id=lab.TASK, git_commit="deadbeef")
    (run / "context-manifest.json").write_text(
        json.dumps(context.model_dump(mode="json"), sort_keys=True),
        encoding="utf-8",
    )
    assert not Path(str(db) + "-wal").exists()
    assert not Path(str(db) + "-shm").exists()
    return src


def _resign_inventory(package: Path) -> None:
    """Only in tests: hashes are untrusted and can be forged by SAME UID."""
    by_path = {name: (package / name).read_bytes() for name in lab.PATHS}
    dest = package / lab.INVENTORY
    dest.chmod(0o600) if dest.exists() else None
    dest.write_bytes(lab.canonical_inventory(by_path))
    dest.chmod(0o400)


def _package(tmp_path: Path) -> tuple[Path, Path]:
    src = _source(tmp_path)
    package = Path(tempfile.mkdtemp(prefix=lab.PREFIX, dir=tmp_path))
    target_run = package / ".projectctl" / "runs" / lab.RUN
    target_run.mkdir(parents=True, mode=0o700)
    for name in lab.PATHS:
        target = package / name
        shutil.copyfile(src / name, target)
        target.chmod(0o400)
    _resign_inventory(package)
    return src, package


def test_detached_fixture_survives_total_removal_of_synthetic_source(tmp_path):
    src, package = _package(tmp_path)
    shutil.rmtree(src)
    assert not src.exists()
    first = lab.inspect_detached_test_fixture(package)
    second = lab.inspect_detached_test_fixture(package)
    assert first == second
    assert first.decision == "NO_GO_DETACHED_FIXTURE_BYTES_ONLY"
    assert first.completeness == "incomplete"
    assert first.sampled_file_identity_unchanged is True
    assert not any((
        first.source_origin_proven,
        first.cross_store_epoch_proven,
        first.independently_immutable_proven,
        first.authorizes_collector_or_cli,
        first.authorizes_live_wal_reader,
        first.authorizes_writer_seal,
        first.authorizes_migration,
    ))
    data = json.loads(first.canonical_trace)
    assert data["completeness"] == "incomplete"
    assert data["assessments"] == []
    assert data["events"][0]["category"] == "unclassified"
    assert _SECRET.encode() not in first.canonical_trace
    assert b"/private/source" not in first.canonical_trace
    assert b"worker.secret_untrusted" not in first.canonical_trace
    assert not (package / ".projectctl/state.sqlite-wal").exists()
    assert not (package / ".projectctl/state.sqlite-shm").exists()


def test_verifier_does_not_change_detached_fixture_bytes_or_leaf_set(tmp_path):
    _, package = _package(tmp_path)
    def state():
        return {
            name: ((package / name).read_bytes(), (package / name).lstat().st_mtime_ns)
            for name in (*lab.PATHS, lab.INVENTORY)
        }
    original = state()
    lab.inspect_detached_test_fixture(package)
    assert state() == original
    assert set((package / ".projectctl").iterdir()) == {
        package / ".projectctl" / "state.sqlite",
        package / ".projectctl" / "runs",
    }


@pytest.mark.parametrize("tamper", [
    "alter_db", "alter_context", "alter_inventory", "remove_inventory",
    "remove_db", "remove_context", "invent_authority", "noncanonical_inventory",
])
def test_changed_or_self_promoting_inventory_refuses(tmp_path, tamper):
    _, package = _package(tmp_path)
    inventory = package / lab.INVENTORY
    db = package / lab.DB
    context = package / lab.CONTEXT
    if tamper == "alter_db":
        db.chmod(0o600)
        with db.open("ab") as stream:
            stream.write(b"x")
        db.chmod(0o400)
    elif tamper == "alter_context":
        context.chmod(0o600)
        context.write_text('{"other":"tampered"}')
        context.chmod(0o400)
    elif tamper == "alter_inventory":
        inventory.chmod(0o600)
        inventory.write_bytes(b"INVALID INVENTORY")
        inventory.chmod(0o400)
    elif tamper == "remove_inventory":
        inventory.unlink()
    elif tamper == "remove_db":
        db.unlink()
    elif tamper == "remove_context":
        context.unlink()
    elif tamper == "invent_authority":
        candidate = json.loads(inventory.read_bytes())
        candidate["source_origin"] = "ATTESTED"
        inventory.chmod(0o600)
        inventory.write_text(json.dumps(candidate))
        inventory.chmod(0o400)
    else:
        inventory.chmod(0o600)
        inventory.write_text('{"format":"fake","format":"duplicate"}')
        inventory.chmod(0o400)
    with pytest.raises(lab.DetachedRefusal):
        lab.inspect_detached_test_fixture(package)


@pytest.mark.parametrize("name", [lab.DB, lab.CONTEXT, lab.INVENTORY])
def test_symlinked_package_file_never_followed(tmp_path, name):
    _, package = _package(tmp_path)
    file = package / name
    outside = tmp_path / "external-not-to-read"
    outside.write_bytes(file.read_bytes())
    file.unlink()
    file.symlink_to(outside)
    with pytest.raises(lab.DetachedRefusal):
        lab.inspect_detached_test_fixture(package)
    assert outside.read_bytes()


@pytest.mark.parametrize("name", [lab.DB, lab.CONTEXT, lab.INVENTORY])
def test_hardlink_never_promoted_to_detached_evidence(tmp_path, name):
    _, package = _package(tmp_path)
    file = package / name
    external = tmp_path / "outside-hardlink"
    os.link(file, external)
    with pytest.raises(lab.DetachedRefusal, match="UNTRUSTED_PRIVATE_LEAF"):
        lab.inspect_detached_test_fixture(package)
    assert external.exists()


@pytest.mark.parametrize("extra", [
    ".projectctl/state.sqlite-wal",
    ".projectctl/state.sqlite-shm",
    ".projectctl/state.sqlite-journal",
    ".projectctl/runs/run-bdiag-detached/foreign-secret",
    "foreign-unlisted-root-file",
])
def test_unlisted_files_and_all_sqlite_sidecars_fail_closed(tmp_path, extra):
    _, package = _package(tmp_path)
    (package / extra).write_bytes(_SECRET.encode())
    with pytest.raises(lab.DetachedRefusal, match="UNEXPECTED_OR_MISSING"):
        lab.inspect_detached_test_fixture(package)


@pytest.mark.parametrize("ancestor", [
    ".projectctl",
    ".projectctl/runs",
    ".projectctl/runs/run-bdiag-detached",
])
def test_directory_symlink_or_mode_drift_fails_closed(tmp_path, ancestor):
    _, package = _package(tmp_path)
    path = package / ancestor
    path.chmod(0o755)
    with pytest.raises(lab.DetachedRefusal, match="UNTRUSTED_PRIVATE_DIRECTORY"):
        lab.inspect_detached_test_fixture(package)


def test_out_of_scope_and_symlinked_top_directory_refused(tmp_path):
    src, package = _package(tmp_path)
    with pytest.raises(lab.DetachedRefusal, match="OUTSIDE_TEST_FIXTURE_SCOPE"):
        lab.inspect_detached_test_fixture(src)
    alias = tmp_path / (lab.PREFIX + "alias")
    alias.symlink_to(package, target_is_directory=True)
    with pytest.raises(lab.DetachedRefusal):
        lab.inspect_detached_test_fixture(alias)
    assert package.exists()


def test_reader_rejects_changed_file_during_a_pass(tmp_path, monkeypatch):
    _, package = _package(tmp_path)
    original = lab.read_run_db_snapshot
    def swap_after_db_read(root, run):
        answer = original(root, run)
        path = package / lab.CONTEXT
        path.chmod(0o600)
        model = ContextManifestV1(task_id=lab.TASK, git_commit="cafebabe")
        path.write_text(json.dumps(model.model_dump(mode="json")))
        path.chmod(0o400)
        _resign_inventory(package)
        return answer
    monkeypatch.setattr(lab, "read_run_db_snapshot", swap_after_db_read)
    with pytest.raises(lab.DetachedRefusal, match="DETACHED_FIXTURE_CHANGED"):
        lab.inspect_detached_test_fixture(package)


def test_valid_self_resigned_package_does_not_prove_provenance(tmp_path):
    _, package = _package(tmp_path)
    changed = package / lab.CONTEXT
    changed.chmod(0o600)
    model = ContextManifestV1(task_id=lab.TASK, git_commit="cafebabe")
    changed.write_text(json.dumps(model.model_dump(mode="json")))
    changed.chmod(0o400)
    _resign_inventory(package)  # any same-UID owner can compute SHA values
    result = lab.inspect_detached_test_fixture(package)
    assert result.completeness == "incomplete"
    assert result.source_origin_proven is False
    assert result.cross_store_epoch_proven is False
    assert result.independently_immutable_proven is False


def test_corrupt_but_inventory_matching_context_is_inconsistent(tmp_path):
    _, package = _package(tmp_path)
    path = package / lab.CONTEXT
    path.chmod(0o600)
    path.write_text('{"schema_kind":"projectctl.context_manifest",'
                    '"task_id":"secret","task_id":"secret"}' + _SECRET)
    path.chmod(0o400)
    _resign_inventory(package)
    result = lab.inspect_detached_test_fixture(package)
    assert result.completeness == "inconsistent"
    assert _SECRET.encode() not in result.canonical_trace
    assert json.loads(result.canonical_trace)["assessments"] == []


def test_read_only_leaf_permission_and_container_mode_enforced(tmp_path):
    _, package = _package(tmp_path)
    db = package / lab.DB
    db.chmod(0o600)
    with pytest.raises(lab.DetachedRefusal, match="UNTRUSTED_PRIVATE_LEAF"):
        lab.inspect_detached_test_fixture(package)
    db.chmod(0o400)
    package.chmod(0o755)
    with pytest.raises(lab.DetachedRefusal, match="UNTRUSTED_PRIVATE_DIRECTORY"):
        lab.inspect_detached_test_fixture(package)


def test_no_unauthorized_runtime_wiring_or_new_credential_surface():
    from projectctl.storage.sqlite import PROJECT_STATE_DB_VERSION
    assert PROJECT_STATE_DB_VERSION == 2
    source = Path(lab.__file__).read_text(encoding="utf-8")
    for forbidden in (
        "sudo ", "apparmor_parser", "systemctl ", "os.chown(",
        "os.setgroups(", "os.setuid(", "shutil.rmtree(",
        "sqlite3.connect(", "os.kill(", "os.replace(",
    ):
        assert forbidden not in source
    from projectctl.cli import entry
    assert not hasattr(entry, "register_trace_export")
