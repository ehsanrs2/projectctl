import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml
from typer.testing import CliRunner

from projectctl.application.verification import verify_run
from projectctl.cli.entry import app
from projectctl.core.digest import digest
from projectctl.core.enums import (
    ModelProfile,
    ReasoningLevel,
    RunStatus,
    RunTerminalReason,
    WorkerResultStatus,
    WorkerStrategyKind,
)
from projectctl.git import WorktreeManager, resolve_commit
from projectctl.schemas.execution import ExecutionPlan, WorkerResult
from projectctl.schemas.run import RunManifest, WorkerDescriptor
from projectctl.storage.runs import RunStore

NOW = datetime(2026, 10, 3, 6, 0, tzinfo=timezone.utc)
runner = CliRunner()


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def catalog(command_code: str) -> dict:
    return {
        "schema_kind": "projectctl.verification_catalog",
        "schema_version": 1,
        "default_profile": "default",
        "profiles": {
            "default": {
                "id": "default",
                "commands": [
                    {
                        "id": "verify",
                        "argv": [sys.executable, "-c", command_code],
                        "timeout_seconds": 20,
                        "required": True,
                    }
                ],
            }
        },
    }


def setup_run(
    tmp_path: Path,
    monkeypatch,
    *,
    strategy: WorkerStrategyKind = WorkerStrategyKind.DIRECT,
    command_code: str = "import pathlib; assert pathlib.Path('app.py').exists()",
    modify: str | None = "value = 2\n",
):
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "config", "user.email", "test@example.com")
    git(repo, "config", "user.name", "Test")
    monkeypatch.setenv("PROJECTCTL_HOME", str(tmp_path / "home"))

    initialized = runner.invoke(app, ["init", str(repo)])
    assert initialized.exit_code == 0, initialized.output

    (repo / ".gitignore").write_text(".projectctl/\n", encoding="utf-8")
    (repo / "app.py").write_text("value = 1\n", encoding="utf-8")
    (repo / "projectctl.verification.yaml").write_text(
        yaml.safe_dump(catalog(command_code), sort_keys=False),
        encoding="utf-8",
    )
    git(repo, "add", ".gitignore", "app.py", "projectctl.verification.yaml", "AGENTS.md", "docs")
    git(repo, "commit", "-q", "-m", "baseline")
    base = git(repo, "rev-parse", "HEAD")

    run_id = "run-test"
    branch = f"projectctl/run/{run_id}"
    manager = WorktreeManager(repo)
    worktree = manager.create(
        worktree_id=run_id,
        branch_name=branch,
        base_commit=base,
    ).path

    if modify is not None:
        (worktree / "app.py").write_text(modify, encoding="utf-8")

    worker = WorkerDescriptor(
        provider="codex",
        model_profile=ModelProfile.BALANCED,
        reasoning=ReasoningLevel.MEDIUM,
    )
    plan = ExecutionPlan(
        plan_id="ep-test",
        project_id="repo",
        task_id="bd-1",
        scheduler_decision_digest="sched",
        task_snapshot_digest="tasks",
        project_state_digest="state",
        quota_snapshot_digest="quota",
        capability_snapshot_digest="caps",
        strategy_decision_digest="strategy",
        strategy=strategy,
        base_commit=base,
        integration_target_ref=git(repo, "branch", "--show-current"),
        worker=worker,
        verification_profile="default",
        created_at=NOW,
    )
    result = WorkerResult(
        run_id=run_id,
        task_id="bd-1",
        status=WorkerResultStatus.IMPLEMENTED,
        summary="worker finished",
        worker_thread_id="thr-test",
        completed_at=NOW,
    )
    run_dir = repo / ".projectctl" / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "execution-plan.json").write_text(
        json.dumps(plan.model_dump(mode="json")),
        encoding="utf-8",
    )
    (run_dir / "worker-result.json").write_text(
        json.dumps(result.model_dump(mode="json")),
        encoding="utf-8",
    )

    manifest = RunManifest(
        run_id=run_id,
        task_id="bd-1",
        execution_plan_digest=digest(plan),
        status=RunStatus.VERIFYING,
        base_commit=base,
        branch_name=branch,
        worktree_id=run_id,
        worker=worker,
        worker_thread_id="thr-test",
    )
    RunStore(repo).create(manifest, worktree_path=worktree, now=NOW)
    return repo, worktree, base, run_id


def test_verification_pass_creates_candidate_and_evidence(tmp_path: Path, monkeypatch):
    repo, worktree, base, run_id = setup_run(tmp_path, monkeypatch)

    verified = verify_run(repo, run_id)

    assert verified.record.status == RunStatus.READY_TO_INTEGRATE
    assert verified.verification.overall_pass is True
    assert verified.evidence.overall_pass is True
    assert verified.record.candidate_commit
    assert verified.record.candidate_commit != base
    assert resolve_commit(worktree, "HEAD") == verified.record.candidate_commit
    parents = git(worktree, "rev-list", "--parents", "-n", "1", verified.record.candidate_commit).split()
    assert parents == [verified.record.candidate_commit, base]
    assert git(worktree, "status", "--porcelain") == ""
    manifest = RunStore(repo).manifest(run_id)
    assert manifest.evidence_manifest == f".projectctl/runs/{run_id}/evidence-manifest.json"


def test_protected_change_blocks_before_commands(tmp_path: Path, monkeypatch):
    repo, worktree, base, run_id = setup_run(tmp_path, monkeypatch)
    (worktree / "AGENTS.md").write_text("worker changed authority\n", encoding="utf-8")

    verified = verify_run(repo, run_id)

    assert verified.record.status == RunStatus.BLOCKED_POLICY
    assert verified.record.terminal_reason == RunTerminalReason.POLICY_BLOCKED
    assert verified.evidence.candidate_commit is None
    assert verified.evidence.overall_pass is False
    assert any("AGENTS.md" in item for item in verified.verification.policy_violations)


def test_failed_command_produces_failure_evidence(tmp_path: Path, monkeypatch):
    repo, worktree, base, run_id = setup_run(
        tmp_path,
        monkeypatch,
        command_code="raise SystemExit(7)",
    )

    verified = verify_run(repo, run_id)

    assert verified.record.status == RunStatus.FAILED
    assert verified.record.terminal_reason == RunTerminalReason.VERIFICATION_FAILED
    assert verified.evidence.candidate_commit is None
    assert verified.verification.overall_pass is False


def test_verifier_mutation_is_detected(tmp_path: Path, monkeypatch):
    repo, worktree, base, run_id = setup_run(
        tmp_path,
        monkeypatch,
        command_code="open('app.py', 'a').write('mutated by verifier\\n')",
    )

    verified = verify_run(repo, run_id)

    assert verified.record.status == RunStatus.FAILED
    assert verified.record.terminal_reason == RunTerminalReason.VERIFICATION_FAILED
    stability = next(
        check for check in verified.verification.checks if check.id == "workspace-stability"
    )
    assert stability.status.value == "failed"


def test_review_run_requires_no_changes_and_finishes_without_integration(
    tmp_path: Path, monkeypatch
):
    repo, worktree, base, run_id = setup_run(
        tmp_path,
        monkeypatch,
        strategy=WorkerStrategyKind.REVIEW,
        modify=None,
    )

    verified = verify_run(repo, run_id)

    assert verified.record.status == RunStatus.PASSED
    assert verified.record.candidate_commit == base
    assert verified.evidence.candidate_commit == base
    assert verified.evidence.changed_paths == []



def test_run_verify_cli_is_registered():
    result = runner.invoke(app, ["run", "verify", "--help"])
    assert result.exit_code == 0, result.output
    assert "--project" in result.output
    assert "--json" in result.output
