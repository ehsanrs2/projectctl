from datetime import datetime, timezone
from pathlib import Path

from projectctl.context.assembler import assemble_context
from projectctl.core.digest import digest
from projectctl.core.enums import (
    ApprovalPolicy,
    ExecutionSandboxMode,
    ModelProfile,
    NetworkPolicy,
    ReasoningLevel,
    TaskStatus,
    TaskType,
    WorkerStrategyKind,
)
from projectctl.schemas.capabilities import WorkerPhasePolicy, WorkerStrategyDecision
from projectctl.schemas.config import ProjectConfig, ProjectIdentity
from projectctl.schemas.execution import ExecutionPlan, ExecutionPolicy
from projectctl.schemas.run import WorkerDescriptor
from projectctl.schemas.task import NormalizedTask, TaskReferences, TaskSource
import yaml

NOW = datetime(2026, 10, 3, 6, 0, tzinfo=timezone.utc)


class FakeStore:
    def __init__(self, task):
        self.task = task

    def get(self, task_id):
        assert task_id == self.task.id
        return self.task


def test_context_assembler_records_paths_digests_and_scopes_without_dumping_content(
    tmp_path: Path, monkeypatch
):
    root = tmp_path / "repo"
    worktree = tmp_path / "worktree"
    (root / ".projectctl").mkdir(parents=True)
    worktree.mkdir()

    config = ProjectConfig(project=ProjectIdentity(id="demo"))
    (root / ".projectctl" / "config.yaml").write_text(
        yaml.safe_dump(config.model_dump(mode="json"), sort_keys=False),
        encoding="utf-8",
    )

    (worktree / "docs").mkdir()
    (worktree / "docs" / "PROJECT.md").write_text("project secret-content", encoding="utf-8")
    (worktree / "docs" / "ROADMAP.md").write_text("roadmap", encoding="utf-8")
    (worktree / "docs" / "CONSTRAINTS.md").write_text("constraints", encoding="utf-8")
    (worktree / "AGENTS.md").write_text("root rules", encoding="utf-8")
    (worktree / "backend").mkdir()
    (worktree / "backend" / "AGENTS.md").write_text("backend rules", encoding="utf-8")
    (worktree / "specs").mkdir()
    (worktree / "specs" / "task.md").write_text("spec secret-spec", encoding="utf-8")

    task = NormalizedTask(
        id="t1",
        title="Implement task",
        source=TaskSource(provider="test", external_id="t1"),
        type=TaskType.FEATURE,
        status=TaskStatus.RUNNING,
        references=TaskReferences(specs=["specs/task.md"]),
    )
    monkeypatch.setattr(
        "projectctl.context.assembler.task_store_for_project",
        lambda project_root: FakeStore(task),
    )

    worker = WorkerDescriptor(
        provider="codex",
        model_profile=ModelProfile.BALANCED,
        reasoning=ReasoningLevel.MEDIUM,
    )
    strategy = WorkerStrategyDecision(
        task_id="t1",
        requested=WorkerStrategyKind.DIRECT,
        resolved=WorkerStrategyKind.DIRECT,
        compatible=True,
        capability_snapshot_digest="caps",
        execution=WorkerPhasePolicy(
            mode="default",
            sandbox=ExecutionSandboxMode.WORKSPACE_WRITE,
            network=NetworkPolicy.DISABLED,
            approval=ApprovalPolicy.DENY_ALL,
        ),
    )
    plan = ExecutionPlan(
        plan_id="ep1",
        project_id="demo",
        task_id="t1",
        scheduler_decision_digest="sched",
        task_snapshot_digest="tasks",
        project_state_digest="state",
        quota_snapshot_digest="quota",
        capability_snapshot_digest="caps",
        strategy_decision_digest=digest(strategy),
        strategy=WorkerStrategyKind.DIRECT,
        base_commit="abcdef1",
        integration_target_ref="main",
        worker=worker,
        execution_policy=ExecutionPolicy(),
        created_at=NOW,
    )

    bundle = assemble_context(
        root,
        worktree=worktree,
        run_id="run-1",
        plan=plan,
        strategy=strategy,
        context_manifest_path=".projectctl/runs/run-1/context-manifest.json",
    )

    assert [x.path for x in bundle.manifest.instruction_sources] == [
        "AGENTS.md",
        "backend/AGENTS.md",
    ]
    assert [x.scope for x in bundle.manifest.instruction_sources] == [".", "backend"]
    assert bundle.manifest.spec_digest is not None
    assert "specs/task.md" in bundle.request.context_sources
    assert "docs/PROJECT.md" in bundle.request.context_sources
    serialized = bundle.request.model_dump_json()
    assert "secret-content" not in serialized
    assert "secret-spec" not in serialized
