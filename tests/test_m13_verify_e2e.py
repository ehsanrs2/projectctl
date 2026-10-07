import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml
from typer.testing import CliRunner

from projectctl.application.verification import verify_run
from projectctl.application.execution_inputs import semantic_execution_input_digest
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
from projectctl.schemas.execution_input import (
    ClaimTransitionEvidence,
    ExecutionInputManifest,
    ExecutionPathScope,
)
from projectctl.schemas.task import NormalizedTask, TaskSource
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
    monkeypatch.setattr(
        "projectctl.application.task_lifecycle.release_task_for_retry",
        lambda root, store, run_id, actor: None,
    )
    monkeypatch.setattr(
        "projectctl.application.task_lifecycle.block_task_for_decision",
        lambda root, task_id, reason: None,
    )
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





def test_execution_write_scope_blocks_before_passing_evidence(tmp_path: Path, monkeypatch):
    repo, worktree, base, run_id = setup_run(tmp_path, monkeypatch)
    run_dir = repo / ".projectctl" / "runs" / run_id
    raw_plan = json.loads((run_dir / "execution-plan.json").read_text(encoding="utf-8"))
    plan = ExecutionPlan.model_validate(raw_plan)

    scoped_task = NormalizedTask(
        id="bd-1",
        title="Scoped task",
        source=TaskSource(provider="test", external_id="bd-1"),
        status="running",
    )
    transition = ClaimTransitionEvidence(
        provider="test",
        claim_digest="claim",
        before_selected_task_digest="before",
        after_selected_task_digest="after",
        transition_kind="unchanged",
        validated_at=NOW,
    )
    execution_input = ExecutionInputManifest(
        project_id="repo",
        task_id="bd-1",
        task_provider="test",
        scheduler_task_snapshot_digest=plan.task_snapshot_digest,
        project_state_digest=plan.project_state_digest,
        preclaim_task_scope_digest="task-scope",
        admitted_task_scope_digest="task-scope",
        scoped_task_ids=["bd-1"],
        preclaim_tasks=[scoped_task],
        base_commit=base,
        integration_target_ref=plan.integration_target_ref,
        writes=[ExecutionPathScope(path="src/allowed.py", kind="exact")],
        phase="admitted",
        claim_transition=transition,
        created_at=NOW,
    )
    input_digest = semantic_execution_input_digest(execution_input)
    updated_plan = plan.model_copy(
        update={
            "execution_input_manifest": f".projectctl/runs/{run_id}/execution-input.json",
            "execution_input_digest": input_digest,
        }
    )
    (run_dir / "execution-input.json").write_text(
        json.dumps(execution_input.model_dump(mode="json")),
        encoding="utf-8",
    )
    (run_dir / "execution-plan.json").write_text(
        json.dumps(updated_plan.model_dump(mode="json")),
        encoding="utf-8",
    )
    RunStore(repo).rebind_execution_plan(
        run_id,
        expected={RunStatus.VERIFYING},
        execution_plan_digest=digest(updated_plan),
        now=NOW,
    )
    monkeypatch.setattr(
        "projectctl.application.verification.revalidate_execution_input",
        lambda root, manifest: None,
    )

    verified = verify_run(repo, run_id)

    assert verified.record.status == RunStatus.BLOCKED_POLICY
    assert verified.record.terminal_reason == RunTerminalReason.POLICY_BLOCKED
    assert verified.verification.overall_pass is False
    assert verified.evidence.overall_pass is False
    assert verified.evidence.candidate_commit is None
    assert "execution_write_scope:app.py" in verified.verification.policy_violations
    scope_check = next(
        check
        for check in verified.verification.checks
        if check.id == "execution-write-scope"
    )
    assert scope_check.status.value == "failed"


def test_run_verify_cli_is_registered():
    result = runner.invoke(app, ["run", "verify", "--help"])
    assert result.exit_code == 0, result.output
