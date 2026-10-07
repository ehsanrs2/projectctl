from __future__ import annotations

import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

from projectctl.application.execution import ExecutionPlanningBundle, prepare_next_run
from projectctl.application.execution_inputs import (
    build_execution_input_manifest,
    execution_input_semantic_digest,
)
from projectctl.core.digest import digest
from projectctl.core.enums import (
    ApprovalPolicy,
    CapabilityState,
    ExecutionSandboxMode,
    ModelProfile,
    ReasoningLevel,
    ResourceClass,
    TaskStatus,
    WorkerMode,
    WorkerStrategyKind,
)
from projectctl.core.errors import StaleSnapshotError
from projectctl.schemas.capabilities import (
    CapabilitySupport,
    PermissionCapabilities,
    WorkerCapabilities,
    WorkerPhasePolicy,
    WorkerRuntimeDescriptor,
    WorkerStrategyDecision,
)
from projectctl.schemas.execution import ExecutionPlan, ExecutionPolicy
from projectctl.schemas.run import WorkerDescriptor
from projectctl.schemas.task import NormalizedTask, TaskSnapshot, TaskSource
from projectctl.schemas.task_claim import TaskClaim
from projectctl.project.state import load_project_state, semantic_project_state_digest
from projectctl.workers.capability_digest import effective_capability_digest

NOW = datetime(2026, 10, 7, 10, 0, tzinfo=timezone.utc)


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def task(
    task_id: str,
    *,
    status: TaskStatus,
    title: str | None = None,
    dependencies: list[str] | None = None,
) -> NormalizedTask:
    return NormalizedTask(
        id=task_id,
        title=title or task_id,
        source=TaskSource(
            provider="test",
            external_id=task_id,
            revision=f"rev-{task_id}",
        ),
        status=status,
        resource_class=ResourceClass.SMALL,
        dependencies=dependencies or [],
    )


def snapshot(*items: NormalizedTask) -> TaskSnapshot:
    return TaskSnapshot(
        provider="test",
        captured_at=NOW,
        source_revision="scheduler-observation",
        tasks=list(items),
    )


def capabilities() -> WorkerCapabilities:
    support = CapabilitySupport(
        runtime=CapabilityState.SUPPORTED,
        adapter=CapabilityState.SUPPORTED,
    )
    return WorkerCapabilities(
        probe_kind="test",
        runtime=WorkerRuntimeDescriptor(
            provider="codex",
            sdk_name="openai-codex",
            sdk_version="0.160.0",
            runtime_name="openai-codex-cli-bin",
            runtime_version="0.160.0",
            adapter_name="projectctl.codex",
            adapter_version="0.37.0",
            observed_at=NOW,
        ),
        modes={
            WorkerMode.DEFAULT: support,
            WorkerMode.PLAN: CapabilitySupport(),
            WorkerMode.GOAL: CapabilitySupport(),
        },
        permissions=PermissionCapabilities(
            sandboxes={
                ExecutionSandboxMode.READ_ONLY: support,
                ExecutionSandboxMode.WORKSPACE_WRITE: support,
            },
            approvals={ApprovalPolicy.DENY_ALL: support},
        ),
        structured_output=support,
    )


class MutatingClaimer:
    def __init__(self, state: dict[str, TaskSnapshot], *, mutate_dependency=False):
        self.state = state
        self.mutate_dependency = mutate_dependency
        self.claim_value: TaskClaim | None = None

    def claim(self, request):
        current = self.state["snapshot"]
        updated = []
        for item in current.tasks:
            if item.id == request.task_id:
                updated.append(
                    item.model_copy(
                        update={
                            "status": TaskStatus.RUNNING,
                            "source": item.source.model_copy(
                                update={"revision": "claimed-revision"}
                            ),
                        }
                    )
                )
            elif self.mutate_dependency and item.id == "dep":
                updated.append(item.model_copy(update={"title": "dep changed"}))
            else:
                updated.append(item)
        self.state["snapshot"] = current.model_copy(update={"tasks": updated})
        self.claim_value = TaskClaim(
            provider="test",
            task_id=request.task_id,
            run_id=request.run_id,
            actor=request.actor,
            base_commit=request.base_commit,
            integration_target_ref=request.integration_target_ref,
            claim_token=request.claim_token,
            request_digest=digest(request),
            acquired=True,
            observed_at=NOW,
        )
        return self.claim_value

    def reconcile(self, request):
        return self.claim_value

    def validate(self, claim):
        return self.claim_value is not None and claim == self.claim_value

    def validate_transition(self, claim, before, after):
        if not self.validate(claim):
            return False
        if before.id != after.id or before.id != claim.task_id:
            return False
        if before.status != TaskStatus.READY or after.status != TaskStatus.RUNNING:
            return False
        left = before.model_dump(mode="json")
        right = after.model_dump(mode="json")
        left["status"] = "<claim>"
        right["status"] = "<claim>"
        left["source"]["revision"] = "<claim>"
        right["source"]["revision"] = "<claim>"
        left["source"].pop("observed_at", None)
        right["source"].pop("observed_at", None)
        left.pop("team", None)
        right.pop("team", None)
        return left == right

    def release(self, claim):
        return None

    def release_legacy(self, task_id, *, actor):
        return None


def init_repo(tmp_path: Path, monkeypatch) -> tuple[Path, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "config", "user.email", "test@example.com")
    git(repo, "config", "user.name", "Test")
    monkeypatch.setenv("PROJECTCTL_HOME", str(tmp_path / "home"))

    # Use the real greenfield bootstrap so config/project-state/worktree layout
    # are the same inputs used by runtime code.
    from typer.testing import CliRunner
    from projectctl.cli.entry import app

    result = CliRunner().invoke(app, ["init", str(repo)])
    assert result.exit_code == 0, result.output
    (repo / ".gitignore").write_text(".projectctl/\n", encoding="utf-8")
    git(repo, "add", ".gitignore", "AGENTS.md", "docs")
    git(repo, "commit", "-q", "-m", "baseline")
    return repo, git(repo, "rev-parse", "HEAD")


def planning_bundle(repo: Path, base: str, tasks: TaskSnapshot):
    caps = capabilities()
    strategy = WorkerStrategyDecision(
        task_id="task-a",
        requested=WorkerStrategyKind.DIRECT,
        resolved=WorkerStrategyKind.DIRECT,
        compatible=True,
        capability_snapshot_digest=effective_capability_digest(caps),
        execution=WorkerPhasePolicy(
            mode=WorkerMode.DEFAULT,
            sandbox=ExecutionSandboxMode.WORKSPACE_WRITE,
            approval=ApprovalPolicy.DENY_ALL,
        ),
    )
    execution_input = build_execution_input_manifest(
        repo,
        task_id="task-a",
        tasks=tasks,
        scheduler_task_snapshot_digest="scheduler-full-snapshot",
        project_state_digest=semantic_project_state_digest(
            load_project_state(repo, allow_missing=True)
        ),
        integration_target_ref=git(repo, "branch", "--show-current"),
        base_commit=base,
        now=NOW,
    )
    worker = WorkerDescriptor(
        provider="codex",
        model_profile=ModelProfile.BALANCED,
        reasoning=ReasoningLevel.MEDIUM,
    )
    plan = ExecutionPlan(
        plan_id="ep-m42a",
        project_id="repo",
        task_id="task-a",
        scheduler_decision_digest="scheduler",
        task_snapshot_digest="scheduler-full-snapshot",
        execution_input_digest=execution_input_semantic_digest(execution_input),
        project_state_digest=execution_input.project_state_digest,
        quota_snapshot_digest="quota",
        capability_snapshot_digest=effective_capability_digest(caps),
        strategy_decision_digest=digest(strategy),
        strategy=WorkerStrategyKind.DIRECT,
        base_commit=base,
        integration_target_ref=execution_input.integration_target_ref,
        worker=worker,
        execution_policy=ExecutionPolicy(),
        created_at=NOW,
    )
    return ExecutionPlanningBundle(
        plan=plan,
        capabilities=caps,
        strategy=strategy,
        execution_input=execution_input,
    )


def test_execution_input_digest_ignores_unrelated_scheduler_observation(tmp_path: Path, monkeypatch):
    repo, base = init_repo(tmp_path, monkeypatch)
    first = snapshot(
        task("task-a", status=TaskStatus.READY, dependencies=["dep"]),
        task("dep", status=TaskStatus.DONE),
        task("unrelated", status=TaskStatus.READY, title="v1"),
    )
    second = snapshot(
        task("task-a", status=TaskStatus.READY, dependencies=["dep"]),
        task("dep", status=TaskStatus.DONE),
        task("unrelated", status=TaskStatus.READY, title="v2"),
    )

    left = build_execution_input_manifest(
        repo,
        task_id="task-a",
        tasks=first,
        scheduler_task_snapshot_digest="full-v1",
        project_state_digest="state",
        integration_target_ref=git(repo, "branch", "--show-current"),
        base_commit=base,
        now=NOW,
    )
    right = build_execution_input_manifest(
        repo,
        task_id="task-a",
        tasks=second,
        scheduler_task_snapshot_digest="full-v2",
        project_state_digest="state",
        integration_target_ref=git(repo, "branch", "--show-current"),
        base_commit=base,
        now=NOW,
    )

    assert left.scheduler_task_snapshot_digest != right.scheduler_task_snapshot_digest
    assert execution_input_semantic_digest(left) == execution_input_semantic_digest(right)


def _prepare_with_mutating_claim(tmp_path: Path, monkeypatch, *, mutate_dependency: bool):
    repo, base = init_repo(tmp_path, monkeypatch)
    initial = snapshot(
        task("task-a", status=TaskStatus.READY, dependencies=["dep"]),
        task("dep", status=TaskStatus.DONE),
    )
    state = {"snapshot": initial}
    claimer = MutatingClaimer(state, mutate_dependency=mutate_dependency)
    planning = planning_bundle(repo, base, initial)

    monkeypatch.setattr(
        "projectctl.application.execution.build_next_execution_bundle",
        lambda root, **kwargs: planning,
    )
    monkeypatch.setattr(
        "projectctl.application.execution._assert_task_store_execution_capable",
        lambda root: None,
    )
    monkeypatch.setattr(
        "projectctl.application.execution._claimer",
        lambda root: claimer,
    )
    monkeypatch.setattr(
        "projectctl.application.execution_inputs.capture_task_snapshot",
        lambda *args, **kwargs: state["snapshot"],
    )
    return repo, planning, claimer


def test_prepare_accepts_expected_claim_mutation(tmp_path: Path, monkeypatch):
    repo, planning, _ = _prepare_with_mutating_claim(
        tmp_path,
        monkeypatch,
        mutate_dependency=False,
    )

    prepared = prepare_next_run(repo)

    assert prepared.record.status.value == "claimed"
    run_dir = repo / ".projectctl" / "runs" / prepared.record.run_id
    assert (run_dir / "execution-input-manifest.json").exists()
    assert (run_dir / "claim-transition.json").exists()
    transition = __import__("json").loads(
        (run_dir / "claim-transition.json").read_text(encoding="utf-8")
    )
    assert transition["preclaim_task_digest"] != transition["postclaim_task_digest"]
    assert transition["execution_input_digest"] == planning.plan.execution_input_digest


def test_prepare_rejects_relevant_dependency_drift_during_claim(tmp_path: Path, monkeypatch):
    repo, _, _ = _prepare_with_mutating_claim(
        tmp_path,
        monkeypatch,
        mutate_dependency=True,
    )

    with pytest.raises(StaleSnapshotError, match="dependency"):
        prepare_next_run(repo)


def test_public_schema_versions_include_m42a_contracts():
    from projectctl.schema_export import PUBLIC_SCHEMAS

    expected = {
        "execution-input-manifest.v1.schema.json",
        "claim-transition-evidence.v1.schema.json",
        "execution-plan.v1.schema.json",
        "execution-plan.v2.schema.json",
        "execution-plan.v3.schema.json",
        "worker-request.v1.schema.json",
        "worker-request.v2.schema.json",
        "worker-request.v3.schema.json",
        "context-manifest.v1.schema.json",
        "context-manifest.v2.schema.json",
        "context-manifest.v3.schema.json",
        "parallel-plan.v1.schema.json",
        "parallel-plan.v2.schema.json",
        "parallel-run-binding.v1.schema.json",
        "parallel-run-binding.v2.schema.json",
        "parallel-reapplication-request.v1.schema.json",
        "parallel-reapplication-request.v2.schema.json",
        "parallel-reapplication.v1.schema.json",
        "parallel-reapplication.v2.schema.json",
    }
    assert expected <= set(PUBLIC_SCHEMAS)


def test_beads_claim_transition_accepts_only_expected_lifecycle_mutation():
    from types import SimpleNamespace

    from projectctl.integrations.beads.claim import BeadsTaskClaimer

    before = NormalizedTask(
        id="bd-1",
        title="Implement",
        source=TaskSource(provider="beads", external_id="bd-1", revision="r1"),
        status=TaskStatus.READY,
        resource_class=ResourceClass.SMALL,
    )
    after = before.model_copy(
        update={
            "status": TaskStatus.RUNNING,
            "source": before.source.model_copy(update={"revision": "r2"}),
        }
    )
    changed_title = after.model_copy(update={"title": "silently changed"})

    claim = TaskClaim(
        provider="beads",
        task_id="bd-1",
        run_id="run-1",
        actor="projectctl:test",
        base_commit="a" * 40,
        integration_target_ref="main",
        claim_token="token",
        request_digest="request",
        acquired=True,
        observed_at=NOW,
    )
    fake = SimpleNamespace(validate=lambda value: value == claim)

    assert BeadsTaskClaimer.validate_transition(fake, claim, before, after) is True
    assert (
        BeadsTaskClaimer.validate_transition(fake, claim, before, changed_title)
        is False
    )


def test_verification_write_scope_rejects_outside_paths():
    from projectctl.application.verification import _write_scope_violations
    from projectctl.schemas.execution_input import (
        ExecutionInputManifest,
        ExecutionPathScope,
        ExecutionTaskInput,
    )

    selected = task("task-a", status=TaskStatus.RUNNING)
    manifest = ExecutionInputManifest(
        input_id="input",
        project_id="repo",
        task_id="task-a",
        integration_target_ref="main",
        base_commit="a" * 40,
        project_state_digest="state",
        scheduler_task_snapshot_digest="scheduler",
        task_scope_digest="scope",
        task_scope_ids=["task-a"],
        task_inputs=[
            ExecutionTaskInput(
                task_id="task-a",
                digest="task-digest",
                task=selected,
            )
        ],
        references_digest="refs",
        write_scopes=[
            ExecutionPathScope(path="src/allowed", kind="tree"),
        ],
        created_at=NOW,
    )

    assert _write_scope_violations(
        manifest,
        ["src/allowed/a.py", "src/outside.py"],
    ) == ["execution_write_scope:src/outside.py"]


def test_parallel_v1_binding_remains_readable():
    from projectctl.schemas.parallel import parse_parallel_run_binding

    payload = {
        "schema_kind": "projectctl.parallel_run_binding",
        "schema_version": 1,
        "run_id": "run-old",
        "task_id": "task-old",
        "preclaim_plan_digest": "preclaim",
        "admitted_plan": {
            "schema_kind": "projectctl.parallel_plan",
            "schema_version": 1,
            "plan_id": "old-plan",
            "project_id": "repo",
            "task_id": "task-old",
            "integration_target_ref": "main",
            "base_commit": "a" * 40,
            "project_state_digest": "state",
            "scoped_task_digest": "task",
            "scoped_task_ids": ["task-old"],
            "scope_digest": "scope",
            "inputs": [
                {
                    "scope": {"path": "src/a.py", "kind": "exact"},
                    "digest": "input",
                }
            ],
            "writes": [{"path": "src/a.py", "kind": "exact"}],
            "resources": [],
            "created_at": NOW.isoformat(),
        },
        "peer_plan_digests": [],
        "peer_decision_digests": [],
        "bound_at": NOW.isoformat(),
    }

    parsed = parse_parallel_run_binding(payload)
    assert parsed.schema_version == 1
    assert parsed.admitted_plan.schema_version == 1
