from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from projectctl.core.enums import (
    ApprovalPolicy,
    ExecutionSandboxMode,
    ModelProfile,
    NetworkPolicy,
    ReasoningLevel,
    RunStatus,
    RunTerminalReason,
    WorkerResultStatus,
)
from projectctl.schemas.execution import ExecutionPlanV1, ExecutionPolicy, WorkerRequestV1, WorkerResult
from projectctl.schemas.run import (
    ContextManifest,
    ContextManifestV1,
    RunManifest,
    RunManifestV1,
    WorkerDescriptor,
)
from projectctl.schemas.verification import VerificationCommand

NOW = datetime(2026, 10, 3, 6, 0, tzinfo=timezone.utc)
WORKER = WorkerDescriptor(
    provider="codex",
    model_profile=ModelProfile.BALANCED,
    reasoning=ReasoningLevel.MEDIUM,
)


def test_execution_policy_defaults_fail_closed():
    policy = ExecutionPolicy()
    assert policy.sandbox == ExecutionSandboxMode.WORKSPACE_WRITE
    assert policy.network == NetworkPolicy.DISABLED
    assert policy.approval == ApprovalPolicy.DENY_ALL
    assert policy.git.allow_commit is False
    assert policy.git.allow_merge is False
    assert policy.git.allow_rebase is False
    assert policy.git.allow_push is False


def test_execution_plan_captures_all_scheduler_inputs():
    plan = ExecutionPlanV1(
        plan_id="ep-1",
        project_id="demo",
        task_id="bd-1",
        task_source_revision="rev-1",
        scheduler_decision_digest="d1",
        task_snapshot_digest="d2",
        project_state_digest="d3",
        quota_snapshot_digest="d4",
        base_commit="abcdef1",
        integration_target_ref="main",
        worker=WORKER,
        created_at=NOW,
    )
    assert plan.execution_policy.approval == ApprovalPolicy.DENY_ALL
    assert plan.verification_profile == "default"


def test_worker_result_cannot_claim_changed_files_or_test_success():
    with pytest.raises(ValidationError):
        WorkerResult.model_validate({
            "run_id": "r1",
            "task_id": "t1",
            "status": WorkerResultStatus.IMPLEMENTED,
            "summary": "done",
            "changed_files": ["x.py"],
            "tests_passed": True,
            "completed_at": NOW.isoformat(),
        })


def test_worker_request_is_bound_to_plan_context_and_worktree():
    request = WorkerRequestV1(
        run_id="r1",
        task_id="t1",
        base_commit="abcdef1",
        branch_name="projectctl/run/r1",
        worktree_id="wt-r1",
        execution_plan_digest="plan-digest",
        context_manifest_digest="ctx-digest",
        worker=WORKER,
        execution_policy=ExecutionPolicy(),
        objective="Implement the task.",
    )
    assert request.output_schema_kind == "projectctl.worker_result"


def test_run_and_context_legacy_contracts_are_retained():
    assert RunManifestV1.model_fields["schema_version"].default == 1
    assert RunManifest.model_fields["schema_version"].default == 2
    assert ContextManifestV1.model_fields["schema_version"].default == 1
    assert ContextManifestV2.model_fields["schema_version"].default == 2
    assert ContextManifest.model_fields["schema_version"].default == 3


def test_failed_run_requires_terminal_reason():
    with pytest.raises(ValidationError):
        RunManifest(
            run_id="r1",
            task_id="t1",
            execution_plan_digest="plan",
            status=RunStatus.FAILED,
            base_commit="abcdef1",
            branch_name="projectctl/run/r1",
            worktree_id="wt-r1",
            worker=WORKER,
        )


def test_passed_run_rejects_terminal_reason():
    with pytest.raises(ValidationError):
        RunManifest(
            run_id="r1",
            task_id="t1",
            execution_plan_digest="plan",
            status=RunStatus.PASSED,
            terminal_reason=RunTerminalReason.WORKER_ERROR,
            base_commit="abcdef1",
            branch_name="projectctl/run/r1",
            worktree_id="wt-r1",
            worker=WORKER,
        )


def test_verification_command_uses_argv_not_shell_string():
    cmd = VerificationCommand(id="pytest", argv=["pytest", "-q"])
    assert cmd.argv == ["pytest", "-q"]
    with pytest.raises(ValidationError):
        VerificationCommand(id="bad", argv=[])
