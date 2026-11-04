import json
import sqlite3
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from projectctl.application.lifecycle_audit import audit_run
from projectctl.application.lifecycle_git import porcelain_clean
from projectctl.cli.entry import app
from projectctl.core.enums import RunStatus
from test_m14_integration_recovery import setup_ready_run


def cold(repo):
    conn = sqlite3.connect(repo / ".projectctl/state.sqlite")
    conn.execute("PRAGMA journal_mode=DELETE")
    conn.close()


def tree_bytes(repo):
    return {str(p.relative_to(repo)): p.read_bytes() for p in repo.rglob("*")
            if p.is_file() and not p.is_symlink()}


def set_status(repo, status, **updates):
    conn = sqlite3.connect(repo / ".projectctl/state.sqlite")
    raw = json.loads(conn.execute("SELECT manifest_json FROM runs").fetchone()[0])
    raw["status"] = status
    if "candidate_commit" in updates:
        raw["candidate_commit"] = updates["candidate_commit"]
    if status in {"blocked_policy", "needs_decision", "failed", "cancelled", "abandoned"}:
        raw["terminal_reason"] = "worker_error"
    conn.execute("UPDATE runs SET status=?, manifest_json=?, terminal_reason=?",
                 (status, json.dumps(raw), raw.get("terminal_reason")))
    for key, value in updates.items():
        assert key in {"lease_owner", "checkpoint_ref", "candidate_commit"}
        conn.execute(f"UPDATE runs SET {key}=?", (value,))
    conn.commit()
    conn.close()


def event(repo, kind, payload):
    conn = sqlite3.connect(repo / ".projectctl/state.sqlite")
    conn.execute("INSERT INTO run_events(run_id,created_at,event_type,payload_json) "
                 "VALUES(?,?,?,?)", ("run-integration", "2026-10-31T00:00:00+00:00", kind, payload))
    conn.commit()
    conn.close()


def test_audit_is_deterministic_readonly_and_sanitized(tmp_path, monkeypatch):
    repo, worktree, *_, run_id = setup_ready_run(tmp_path, monkeypatch)
    cold(repo)
    event(repo, "worker.started", '{"prompt":"SECRET","worker_thread_id":"SECRET_THREAD"}')
    before = tree_bytes(tmp_path)
    first = audit_run(repo, run_id)
    assert first == audit_run(repo, run_id)
    assert first["checks"]["candidate_binding"]["state"] == "observed"
    assert first["checks"]["candidate_diff"]["state"] == "observed"
    assert first["handoff"]["proposed_stage"] == "integrate"
    assert first["handoff"]["dispatch_authorized"] is False
    assert first["handoff"]["implicit_retry_allowed"] is False
    assert "SECRET" not in json.dumps(first)
    assert tree_bytes(tmp_path) == before
    output = CliRunner().invoke(app, ["run", "audit", run_id, "--project", str(repo), "--json"])
    assert output.exit_code == 0, output.output
    assert json.loads(output.output) == first
    assert tree_bytes(tmp_path) == before


@pytest.mark.parametrize("status", [s.value for s in RunStatus])
def test_every_current_run_status_stays_non_dispatching(tmp_path, monkeypatch, status):
    repo, *_, run_id = setup_ready_run(tmp_path, monkeypatch)
    cold(repo)
    set_status(repo, status)
    report = audit_run(repo, run_id)
    assert report["observed_status"] == status
    assert report["handoff"]["permitted_action"] == "inspect"
    assert not report["handoff"]["dispatch_authorized"]


@pytest.mark.parametrize("mutation", ["candidate", "worker", "plan", "event", "lease", "target", "workspace"])
def test_mismatches_and_uncertainty_refuse_handoff(tmp_path, monkeypatch, mutation):
    repo, worktree, *_, run_id = setup_ready_run(tmp_path, monkeypatch)
    cold(repo)
    run = repo / ".projectctl/runs" / run_id
    if mutation in {"candidate", "worker", "plan"}:
        name, field, value = {
            "candidate": ("evidence-manifest.json", "candidate_commit", "abcdef0123456789"),
            "worker": ("worker-result.json", "run_id", "foreign"),
            "plan": ("execution-plan.json", "base_commit", "abcdef0123456789"),
        }[mutation]
        raw = json.loads((run / name).read_text())
        raw[field] = value
        (run / name).write_text(json.dumps(raw))
    elif mutation == "event":
        event(repo, "verification.passed", '{"evidence_manifest_digest":"tampered"}')
    elif mutation == "lease":
        set_status(repo, "ready_to_integrate", lease_owner="some-owner")
    elif mutation == "target":
        (repo / "advance").write_text("advance")
        subprocess.run(["git", "-C", str(repo), "add", "advance"], check=True)
        subprocess.run(["git", "-C", str(repo), "commit", "-qm", "advance"], check=True)
    else:
        (worktree / "app.py").write_text("drift")
    report = audit_run(repo, run_id)
    assert report["handoff"]["proposed_stage"] is None
    assert not report["handoff"]["implicit_retry_allowed"]


def test_dispatched_start_never_retries_even_with_missing_stdout(tmp_path, monkeypatch):
    repo, *_, run_id = setup_ready_run(tmp_path, monkeypatch)
    cold(repo)
    set_status(repo, "claimed")
    event(repo, "worker.started", "{}")
    for _ in range(2):
        report = audit_run(repo, run_id)
        assert report["handoff"]["proposed_stage"] is None
        assert "possibly_dispatched_reconcile_only" in report["handoff"]["guards"]


def test_wal_source_is_explicit_unknown_without_source_mutation(tmp_path, monkeypatch):
    repo, *_, run_id = setup_ready_run(tmp_path, monkeypatch)
    before = tree_bytes(tmp_path)
    report = audit_run(repo, run_id)
    assert report["observed_status"] is None
    assert report["source"]["state"] == "unknown"
    assert tree_bytes(tmp_path) == before


def test_porcelain_leading_blank_is_not_stripped():
    assert not porcelain_clean(b" M app.py\0")
    assert not porcelain_clean(b"?? new\0")
    assert porcelain_clean(b"")


def test_passed_cleanup_is_expected_and_local_is_not_publication(tmp_path, monkeypatch):
    from projectctl.application.integration import integrate_run
    from test_m14_integration_recovery import FakeCompletionWriter
    repo, worktree, *_, run_id = setup_ready_run(tmp_path, monkeypatch)
    monkeypatch.setattr("projectctl.application.integration._completion_writer",
                        lambda root: FakeCompletionWriter())
    integrate_run(repo, run_id)  # Disposable synthetic repo; no provider calls.
    cold(repo)
    assert not worktree.exists()
    before = tree_bytes(tmp_path)
    report = audit_run(repo, run_id)
    assert report["observed_status"] == "passed"
    assert report["checks"]["worktree"]["state"] == "not_applicable"
    assert report["checks"]["publication_manifest"]["state"] == "not_applicable"
    assert report["handoff"]["proposed_stage"] is None
    assert tree_bytes(tmp_path) == before


def test_missing_evidence_and_foreign_worktree_fail_closed(tmp_path, monkeypatch):
    repo, *_, run_id = setup_ready_run(tmp_path, monkeypatch)
    cold(repo)
    (repo / ".projectctl/runs" / run_id / "evidence-manifest.json").unlink()
    conn = sqlite3.connect(repo / ".projectctl/state.sqlite")
    conn.execute("UPDATE runs SET worktree_path=?", (str(tmp_path / "foreign"),))
    conn.commit()
    conn.close()
    report = audit_run(repo, run_id)
    assert report["checks"]["evidence_manifest"]["state"] == "missing"
    assert report["checks"]["worktree_path"]["state"] == "inconsistent"
    assert report["handoff"]["proposed_stage"] is None


def checkpoint_run(tmp_path, monkeypatch):
    from test_m12b_codex_adapter import checkpoint_bindings, request, FakeCheckpointMonitor
    from projectctl.workers.codex.adapter import CodexWorkerAdapter
    from projectctl.core.digest import digest
    from projectctl.application.execution import _worktree_state_digest
    repo, worktree, base, _, _, run_id = setup_ready_run(tmp_path, monkeypatch)
    subprocess.run(["git", "-C", str(worktree), "reset", "--hard", base], check=True, capture_output=True)
    for name in ("worker-result.json", "verification-manifest.json", "evidence-manifest.json"):
        (repo / ".projectctl/runs" / run_id / name).unlink()
    (worktree / "app.py").write_text("checkpoint partial work\n")
    (worktree / "partial.txt").write_text("untracked checkpoint work\n")
    checkpoint = CodexWorkerAdapter(bindings_loader=checkpoint_bindings).start(
        request(), workspace=worktree, checkpoint_monitor=FakeCheckpointMonitor())
    checkpoint = checkpoint.model_copy(update={"run_id": run_id, "task_id": "bd-1",
        "base_commit": base, "worktree_id": run_id,
        "branch_name": f"projectctl/run/{run_id}",
        "workspace_digest": _worktree_state_digest(worktree)})
    directory = repo / ".projectctl/runs" / run_id / "checkpoints"
    directory.mkdir()
    path = directory / ("checkpoint-" + "a" * 32 + ".json")
    path.write_text(checkpoint.model_dump_json())
    cold(repo)
    set_status(repo, "running", checkpoint_ref=str(path.relative_to(repo)), candidate_commit=None)
    event(repo, "worker.checkpointed", json.dumps({"checkpoint_digest": digest(checkpoint),
          "checkpoint_ref": str(path.relative_to(repo))}))
    return repo, worktree, run_id, path


def test_checkpoint_is_running_with_durable_checkpoint_not_a_new_status(tmp_path, monkeypatch):
    repo, worktree, run_id, path = checkpoint_run(tmp_path, monkeypatch)
    before = tree_bytes(tmp_path)
    report = audit_run(repo, run_id)
    assert report["observed_status"] == "running"
    assert report["checkpointed"] is True
    assert report["checks"]["worker_checkpoint"]["state"] == "observed"
    assert report["checks"]["checkpoint_workspace"]["state"] == "observed"
    assert report["handoff"]["proposed_stage"] == "resume"
    assert tree_bytes(tmp_path) == before
    event(repo, "worker.resumed", "{}")
    report = audit_run(repo, run_id)
    assert report["handoff"]["proposed_stage"] is None


def test_audit_cannot_enter_mutable_runtime_or_task_provider(tmp_path, monkeypatch):
    repo, *_, run_id = setup_ready_run(tmp_path, monkeypatch)
    cold(repo)
    beads = repo / ".beads"
    beads.mkdir()
    (beads / "issues.jsonl").write_text('{"id":"bd-1","status":"open","title":"SECRET_TASK"}\n')
    before = tree_bytes(tmp_path)

    def forbidden(*args, **kwargs):
        pytest.fail("read-only audit entered a mutable runtime path")

    for target in (
        "projectctl.storage.runs.RunStore.__init__",
        "projectctl.git.WorktreeManager.__init__",
        "projectctl.storage.sqlite.connect_db",
        "projectctl.application.auto.run_auto",
        "projectctl.application.turns.advance_non_worker_phases",
        "projectctl.application.recovery.recover_run",
    ):
        monkeypatch.setattr(target, forbidden)
    original = subprocess.run

    def git_only(argv, *args, **kwargs):
        assert argv[0] == "git"
        return original(argv, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", git_only)
    report = audit_run(repo, run_id)
    assert "SECRET_TASK" not in json.dumps(report)
    assert tree_bytes(tmp_path) == before


def test_missing_manager_storage_is_not_created(tmp_path, monkeypatch):
    repo, *_, run_id = setup_ready_run(tmp_path, monkeypatch)
    cold(repo)
    home = tmp_path / "absent-home"
    monkeypatch.setenv("PROJECTCTL_HOME", str(home))
    report = audit_run(repo, run_id)
    assert report["checks"]["worktree_path"]["state"] == "inconsistent"
    assert not home.exists()


def test_shared_worktree_contract_rejects_cross_instance_symlink(tmp_path):
    from projectctl.git import WorktreeManager
    from projectctl.core.errors import WorktreeError
    instance = tmp_path / "worktrees/instance"
    other = tmp_path / "worktrees/other"
    instance.mkdir(parents=True)
    other.mkdir()
    (instance / "run-1").symlink_to(other, target_is_directory=True)
    with pytest.raises(WorktreeError):
        WorktreeManager.storage_path(tmp_path, "instance", "run-1")


def test_cli_measurement_collision_never_reenters_existing_stage(tmp_path, monkeypatch):
    from projectctl.core.errors import RunStoreError
    repo, *_, run_id = setup_ready_run(tmp_path, monkeypatch)
    path = tmp_path / "measurements.json"
    calls = []

    def stage(root, run):
        calls.append(run)
        assert json.loads(path.read_text())["state"] == "pending"
        raise RunStoreError("synthetic stop")

    monkeypatch.setattr("projectctl.cli.m11.start_prepared_run", stage)
    args = ["run", "start", run_id, "--project", str(repo), "--measurements", str(path)]
    runner = CliRunner()
    assert runner.invoke(app, args).exit_code != 0
    before = path.read_bytes()
    assert runner.invoke(app, args).exit_code != 0
    assert calls == [run_id]
    assert path.read_bytes() == before


def test_event_payload_budget_is_checked_before_loading_stream(tmp_path, monkeypatch):
    repo, *_, run_id = setup_ready_run(tmp_path, monkeypatch)
    cold(repo)
    event(repo, "worker.started", json.dumps({"payload": "x" * (2 * 1024 * 1024)}))
    report = audit_run(repo, run_id)
    assert report["source"]["state"] == "unknown"
    assert report["handoff"]["proposed_stage"] is None


def test_pending_or_interrupted_telemetry_suppresses_stage_suggestion(tmp_path, monkeypatch):
    from projectctl.telemetry.lifecycle import measurement_artifact
    repo, *_, run_id = setup_ready_run(tmp_path, monkeypatch)
    cold(repo)
    path = tmp_path / "telemetry.json"
    with pytest.raises(RuntimeError):
        with measurement_artifact(path, run_id=run_id, stage="integrate"):
            pending = audit_run(repo, run_id, measurements=path)
            assert pending["handoff"]["proposed_stage"] is None
            raise RuntimeError("synthetic interruption")
    report = audit_run(repo, run_id, measurements=path)
    assert report["handoff"]["proposed_stage"] is None
    assert "measurement_operation_uncertain_reconcile_only" in report["handoff"]["guards"]


@pytest.mark.parametrize("head", ["frozen_base", "unexpected", "unverifiable"])
def test_start_requires_frozen_base_head(tmp_path, monkeypatch, head):
    repo, worktree, base, _, _, run_id = setup_ready_run(tmp_path, monkeypatch)
    cold(repo)
    set_status(repo, "claimed", candidate_commit=None)
    for name in ("worker-result.json", "verification-manifest.json", "evidence-manifest.json"):
        (repo / ".projectctl/runs" / run_id / name).unlink()
    if head == "frozen_base":
        subprocess.run(["git", "-C", str(worktree), "reset", "--hard", base], check=True, capture_output=True)
    elif head == "unverifiable":
        from projectctl.application import lifecycle_git
        original = lifecycle_git._git

        def unavailable(root, *args):
            if root == worktree and args[0] == "rev-parse":
                raise ValueError("PRIVATE_GIT_ERROR")
            return original(root, *args)

        monkeypatch.setattr(lifecycle_git, "_git", unavailable)
    before = tree_bytes(tmp_path)
    report = audit_run(repo, run_id)
    assert report["handoff"]["proposed_stage"] == ("start" if head == "frozen_base" else None)
    if head == "unexpected":
        assert report["checks"]["worktree_head"]["state"] == "inconsistent"
    assert not report["handoff"]["dispatch_authorized"]
    assert "PRIVATE_GIT_ERROR" not in json.dumps(report)
    assert tree_bytes(tmp_path) == before


@pytest.mark.parametrize("mutation", ["tracked", "untracked", "head", "digest", "missing_digest", "branch", "event_ref"])
def test_resume_rejects_checkpoint_or_workspace_drift(tmp_path, monkeypatch, mutation):
    from projectctl.core.digest import digest
    from projectctl.schemas.execution import parse_worker_checkpoint
    repo, worktree, run_id, path = checkpoint_run(tmp_path, monkeypatch)
    if mutation == "tracked":
        (worktree / "app.py").write_text("changed after checkpoint")
    elif mutation == "untracked":
        (worktree / "partial.txt").write_text("changed untracked bytes")
    elif mutation == "head":
        subprocess.run(["git", "-C", str(worktree), "-c", "user.name=Test", "-c",
                        "user.email=test@example.com", "commit", "--allow-empty", "-qm", "unexpected HEAD"], check=True)
    else:
        raw = json.loads(path.read_text())
        if mutation == "branch":
            raw["branch_name"] = "foreign-branch"
        elif mutation != "event_ref":
            raw["workspace_digest"] = None if mutation == "missing_digest" else "wrong-digest"
        path.write_text(json.dumps(raw))
        # Rebind event digest to isolate workspace/identity validation, not only file tampering.
        conn = sqlite3.connect(repo / ".projectctl/state.sqlite")
        conn.execute("UPDATE run_events SET payload_json=? WHERE event_type='worker.checkpointed'",
                     (json.dumps({"checkpoint_digest": digest(parse_worker_checkpoint(raw)),
                                  "checkpoint_ref": "foreign-ref" if mutation == "event_ref" else str(path.relative_to(repo))}),))
        conn.commit()
        conn.close()
    before = tree_bytes(tmp_path)
    report = audit_run(repo, run_id)
    assert report["handoff"]["proposed_stage"] is None
    assert not report["handoff"]["implicit_retry_allowed"]
    assert tree_bytes(tmp_path) == before


@pytest.mark.parametrize("failure", ["missing", "unknown", "inconsistent", "exception"])
def test_integrate_requires_complete_candidate_git_evidence(tmp_path, monkeypatch, failure):
    from projectctl.application import lifecycle_git
    repo, *_, run_id = setup_ready_run(tmp_path, monkeypatch)
    cold(repo)
    if failure == "exception":
        original = lifecycle_git._git

        def unavailable(root, *args):
            if args[0] == "diff":
                raise ValueError("PRIVATE_CANDIDATE_ERROR")
            return original(root, *args)

        monkeypatch.setattr(lifecycle_git, "_git", unavailable)
    else:
        original = lifecycle_git.inspect_git

        def insufficient(*args, **kwargs):
            checks = original(*args, **kwargs)
            if failure == "missing":
                checks.pop("candidate_diff")
            else:
                checks["candidate_diff"]["state"] = failure
            return checks

        monkeypatch.setattr(lifecycle_git, "inspect_git", insufficient)
    before = tree_bytes(tmp_path)
    report = audit_run(repo, run_id)
    assert report["handoff"]["proposed_stage"] is None
    assert report["handoff"]["guards"]
    assert "PRIVATE_CANDIDATE_ERROR" not in json.dumps(report)
    assert tree_bytes(tmp_path) == before


def verifying_run(tmp_path, monkeypatch, *, frozen_head=True):
    repo, worktree, base, _, _, run_id = setup_ready_run(tmp_path, monkeypatch)
    cold(repo)
    set_status(repo, "verifying", candidate_commit=None)
    for name in ("verification-manifest.json", "evidence-manifest.json"):
        (repo / ".projectctl/runs" / run_id / name).unlink()
    if frozen_head:
        subprocess.run(["git", "-C", str(worktree), "reset", "--hard", base],
                       check=True, capture_output=True)
    return repo, worktree, run_id


@pytest.mark.parametrize("frozen_head", [True, False])
def test_verify_requires_observed_frozen_base_head(tmp_path, monkeypatch, frozen_head):
    repo, _, run_id = verifying_run(tmp_path, monkeypatch, frozen_head=frozen_head)
    report = audit_run(repo, run_id)
    assert report["handoff"]["proposed_stage"] == ("verify" if frozen_head else None)
    assert report["checks"]["worktree_head"] == {
        "state": "observed" if frozen_head else "inconsistent",
        "reason": "frozen_base_head_cross_check",
    }
    assert not report["handoff"]["dispatch_authorized"]
    assert not report["handoff"]["implicit_retry_allowed"]


@pytest.mark.parametrize("status", ["running", "verifying"])
@pytest.mark.parametrize("dirty", [None, "tracked", "staged", "untracked"])
def test_pending_verification_reports_actual_cleanliness(tmp_path, monkeypatch, status, dirty):
    repo, worktree, run_id = verifying_run(tmp_path, monkeypatch)
    set_status(repo, status, candidate_commit=None)
    if dirty == "untracked":
        (worktree / "new.txt").write_text("worker output\n")
    elif dirty:
        (worktree / "app.py").write_text("worker output\n")
        if dirty == "staged":
            subprocess.run(["git", "-C", str(worktree), "add", "app.py"], check=True)
    before = tree_bytes(tmp_path)
    report = audit_run(repo, run_id)
    assert report["checks"]["worktree_clean"] == {
        "state": "not_applicable" if dirty else "observed",
        "reason": "dirty_workspace_pending_verification" if dirty else "git_porcelain_observation",
    }
    assert report["handoff"]["proposed_stage"] == ("verify" if status == "verifying" else None)
    assert not report["handoff"]["dispatch_authorized"]
    assert not report["handoff"]["implicit_retry_allowed"]
    assert tree_bytes(tmp_path) == before


@pytest.mark.parametrize("state", [None, "unknown", "not_applicable"])
def test_verify_refuses_unproven_head(tmp_path, monkeypatch, state):
    from projectctl.application import lifecycle_git
    repo, _, run_id = verifying_run(tmp_path, monkeypatch)
    original = lifecycle_git.inspect_git

    def insufficient(*args, **kwargs):
        checks = original(*args, **kwargs)
        checks.pop("worktree_head", None)
        if state is not None:
            checks["worktree_head"] = {"state": state, "reason": "synthetic_unproven_head"}
        return checks

    monkeypatch.setattr(lifecycle_git, "inspect_git", insufficient)
    report = audit_run(repo, run_id)
    assert report["handoff"]["proposed_stage"] is None
    assert "git_inputs_unproven" in report["handoff"]["guards"]
