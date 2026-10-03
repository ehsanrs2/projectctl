from __future__ import annotations

import json
import os
import tempfile
import uuid
from collections import Counter
from datetime import datetime
from pathlib import Path

from projectctl.application.execution import (
    prepare_next_run,
    resume_checkpointed_run,
    start_prepared_run,
)
from projectctl.application.integration import integrate_run
from projectctl.application.recovery import recover_run
from projectctl.application.status import collect_status
from projectctl.application.verification import verify_run
from projectctl.core.enums import (
    AutoStopReason,
    QuotaMode,
    RunStatus,
    RunTerminalReason,
)
from projectctl.core.errors import ProjectCtlError
from projectctl.core.time import utc_now
from projectctl.project.locking import project_lock
from projectctl.schemas.auto import AutoRunPolicy, AutoRunReport, AutoRunStep
from projectctl.schemas.execution import ExecutionPlan
from projectctl.schemas.capabilities import StrategyFallbackPolicy
from projectctl.storage.runs import RunStore


_ACTIVE_STATUSES = {
    RunStatus.PLANNED,
    RunStatus.PREPARING,
    RunStatus.CLAIMED,
    RunStatus.RUNNING,
    RunStatus.VERIFYING,
    RunStatus.READY_TO_INTEGRATE,
    RunStatus.INTEGRATING,
}

_RETRYABLE_REASONS = {
    RunTerminalReason.INFRASTRUCTURE_ERROR,
    RunTerminalReason.TIMEOUT,
    RunTerminalReason.WORKER_ERROR,
    RunTerminalReason.CLAIM_LOST,
    RunTerminalReason.STALE_BASE,
    RunTerminalReason.CONTEXT_INVALID,
}


def _atomic_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(
        value.model_dump(mode="json"),
        indent=2,
        sort_keys=True,
        ensure_ascii=False,
    ) + "\n"
    fd, tmp_name = tempfile.mkstemp(prefix=".projectctl-", suffix=".json", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    finally:
        try:
            Path(tmp_name).unlink()
        except FileNotFoundError:
            pass


def _has_live_lease(record, now: datetime) -> bool:
    return (
        record.lease_owner is not None
        and record.lease_expires_at is not None
        and record.lease_expires_at > now
    )


def _active_runs(store: RunStore):
    return [record for record in store.list(limit=1000) if record.status in _ACTIVE_STATUSES]


def _execution_plan_state_digest(project_root: Path, run_id: str) -> str | None:
    path = project_root / ".projectctl" / "runs" / run_id / "execution-plan.json"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return ExecutionPlan.model_validate(raw).project_state_digest
    except Exception:
        return None


def _classify_terminal(record, attempts_for_task: int, policy: AutoRunPolicy):
    if record.status == RunStatus.RUNNING and record.checkpoint_ref:
        return AutoStopReason.QUOTA_CHECKPOINTED
    if record.status == RunStatus.PASSED:
        return None
    if record.status == RunStatus.BLOCKED_POLICY:
        return AutoStopReason.POLICY_BLOCKED
    if record.status == RunStatus.NEEDS_DECISION:
        return AutoStopReason.HUMAN_DECISION_REQUIRED
    if record.status in {RunStatus.CANCELLED, RunStatus.ABANDONED}:
        return AutoStopReason.RUN_FAILED
    if record.status == RunStatus.FAILED:
        if (
            record.terminal_reason in _RETRYABLE_REASONS
            and attempts_for_task < policy.max_attempts_per_task
        ):
            return None
        if record.terminal_reason in _RETRYABLE_REASONS:
            return AutoStopReason.RETRY_BUDGET_EXHAUSTED
        return AutoStopReason.RUN_FAILED
    return AutoStopReason.RECOVERY_REQUIRED


def _advance_run(project_root: Path, run_id: str):
    store = RunStore(project_root)
    record = store.get(run_id)

    # Recover crash windows before attempting their next deterministic phase.
    if record.status == RunStatus.RUNNING:
        if record.checkpoint_ref:
            resume_checkpointed_run(project_root, run_id)
        else:
            recover_run(project_root, run_id)
        record = store.get(run_id)
    elif record.status == RunStatus.INTEGRATING:
        recover_run(project_root, run_id)
        record = store.get(run_id)

    if record.status == RunStatus.CLAIMED:
        start_prepared_run(project_root, run_id)
        record = store.get(run_id)

    if record.status == RunStatus.VERIFYING:
        verify_run(project_root, run_id)
        record = store.get(run_id)

    if record.status == RunStatus.READY_TO_INTEGRATE:
        integrate_run(project_root, run_id)
        record = store.get(run_id)

    return record


def _finalize(
    project_root: Path,
    *,
    auto_run_id: str,
    started_at,
    stop_reason: AutoStopReason,
    completed_tasks: int,
    attempted_tasks: int,
    steps: list[AutoRunStep],
) -> AutoRunReport:
    report = AutoRunReport(
        auto_run_id=auto_run_id,
        started_at=started_at,
        completed_at=utc_now(),
        stop_reason=stop_reason,
        completed_tasks=completed_tasks,
        attempted_tasks=attempted_tasks,
        steps=steps,
    )
    _atomic_json(
        project_root / ".projectctl" / "auto" / f"{auto_run_id}.json",
        report,
    )
    return report


def run_auto(project_root: Path, policy: AutoRunPolicy | None = None) -> AutoRunReport:
    root = project_root.resolve()
    policy = policy or AutoRunPolicy()
    auto_run_id = f"auto-{uuid.uuid4().hex}"
    started_at = utc_now()
    steps: list[AutoRunStep] = []
    completed_tasks = 0
    attempted_tasks = 0
    attempts_by_task: Counter[str] = Counter()

    with project_lock(root, "auto-loop"):
        while attempted_tasks < policy.max_tasks:
            store = RunStore(root)
            active = _active_runs(store)

            if len(active) > 1:
                steps.append(
                    AutoRunStep(
                        iteration=len(steps) + 1,
                        action="multiple_active_runs",
                        details=[record.run_id for record in active],
                    )
                )
                return _finalize(
                    root,
                    auto_run_id=auto_run_id,
                    started_at=started_at,
                    stop_reason=AutoStopReason.MULTIPLE_ACTIVE_RUNS,
                    completed_tasks=completed_tasks,
                    attempted_tasks=attempted_tasks,
                    steps=steps,
                )

            if len(active) == 1:
                record = active[0]
                if _has_live_lease(record, utc_now()):
                    steps.append(
                        AutoRunStep(
                            iteration=len(steps) + 1,
                            task_id=record.task_id,
                            run_id=record.run_id,
                            started_status=record.status,
                            final_status=record.status,
                            action="active_run_present",
                            details=[
                                f"lease_owner={record.lease_owner}",
                                f"lease_expires_at={record.lease_expires_at.isoformat()}",
                            ],
                        )
                    )
                    return _finalize(
                        root,
                        auto_run_id=auto_run_id,
                        started_at=started_at,
                        stop_reason=AutoStopReason.ACTIVE_RUN_PRESENT,
                        completed_tasks=completed_tasks,
                        attempted_tasks=attempted_tasks,
                        steps=steps,
                    )

                if record.status in {RunStatus.PLANNED, RunStatus.PREPARING}:
                    steps.append(
                        AutoRunStep(
                            iteration=len(steps) + 1,
                            task_id=record.task_id,
                            run_id=record.run_id,
                            started_status=record.status,
                            final_status=record.status,
                            action="unsafe_partial_prepare",
                            details=[
                                "Automatic recovery cannot prove whether task claim/worktree preparation completed."
                            ],
                        )
                    )
                    return _finalize(
                        root,
                        auto_run_id=auto_run_id,
                        started_at=started_at,
                        stop_reason=AutoStopReason.RECOVERY_REQUIRED,
                        completed_tasks=completed_tasks,
                        attempted_tasks=attempted_tasks,
                        steps=steps,
                    )

                attempted_tasks += 1
                attempts_by_task[record.task_id] += 1
                started_status = record.status
                details: list[str] = ["resumed unfinished run"]
                try:
                    final = _advance_run(root, record.run_id)
                except ProjectCtlError as exc:
                    details.append(str(exc))
                    final = RunStore(root).get(record.run_id)

                stop = _classify_terminal(
                    final,
                    attempts_by_task[record.task_id],
                    policy,
                )
                if final.status != RunStatus.PASSED:
                    steps.append(
                        AutoRunStep(
                            iteration=len(steps) + 1,
                            task_id=record.task_id,
                            run_id=record.run_id,
                            started_status=started_status,
                            final_status=final.status,
                            action="resume_run",
                            details=details,
                        )
                    )
                    if stop is not None:
                        return _finalize(
                            root,
                            auto_run_id=auto_run_id,
                            started_at=started_at,
                            stop_reason=stop,
                            completed_tasks=completed_tasks,
                            attempted_tasks=attempted_tasks,
                            steps=steps,
                        )
                    continue

                completed_tasks += 1
                status_after = collect_status(root)
                original_state_digest = _execution_plan_state_digest(root, record.run_id)
                steps.append(
                    AutoRunStep(
                        iteration=len(steps) + 1,
                        task_id=record.task_id,
                        run_id=record.run_id,
                        started_status=started_status,
                        final_status=final.status,
                        action="resume_run",
                        project_state_digest_before=original_state_digest,
                        project_state_digest_after=status_after.decision.project_state_digest,
                        quota_mode=status_after.quota_state.mode,
                        quota_stale=status_after.quota_state.stale,
                        details=details,
                    )
                )
                if (
                    policy.stop_on_material_project_state_change
                    and original_state_digest is not None
                    and original_state_digest
                    != status_after.decision.project_state_digest
                ):
                    return _finalize(
                        root,
                        auto_run_id=auto_run_id,
                        started_at=started_at,
                        stop_reason=AutoStopReason.MATERIAL_PROJECT_STATE_CHANGE,
                        completed_tasks=completed_tasks,
                        attempted_tasks=attempted_tasks,
                        steps=steps,
                    )
                continue

            status_before = collect_status(root)
            if policy.stop_on_stale_quota and status_before.quota_state.stale:
                steps.append(
                    AutoRunStep(
                        iteration=len(steps) + 1,
                        action="quota_checkpoint",
                        project_state_digest_before=status_before.decision.project_state_digest,
                        quota_mode=status_before.quota_state.mode,
                        quota_stale=True,
                        details=["Autonomous mode requires a fresh quota snapshot by default."],
                    )
                )
                return _finalize(
                    root,
                    auto_run_id=auto_run_id,
                    started_at=started_at,
                    stop_reason=AutoStopReason.QUOTA_STALE,
                    completed_tasks=completed_tasks,
                    attempted_tasks=attempted_tasks,
                    steps=steps,
                )

            if (
                policy.stop_on_critical_quota
                and status_before.quota_state.mode == QuotaMode.CRITICAL
            ):
                steps.append(
                    AutoRunStep(
                        iteration=len(steps) + 1,
                        action="quota_checkpoint",
                        project_state_digest_before=status_before.decision.project_state_digest,
                        quota_mode=status_before.quota_state.mode,
                        quota_stale=status_before.quota_state.stale,
                        details=["Quota is in critical mode."],
                    )
                )
                return _finalize(
                    root,
                    auto_run_id=auto_run_id,
                    started_at=started_at,
                    stop_reason=AutoStopReason.QUOTA_CRITICAL,
                    completed_tasks=completed_tasks,
                    attempted_tasks=attempted_tasks,
                    steps=steps,
                )

            task_id = status_before.decision.selected_task_id
            if task_id is None:
                done = (
                    status_before.status.task_counts.total > 0
                    and status_before.status.task_counts.done
                    == status_before.status.task_counts.total
                )
                reason = (
                    AutoStopReason.COMPLETED
                    if done
                    else AutoStopReason.NO_ELIGIBLE_TASK
                )
                steps.append(
                    AutoRunStep(
                        iteration=len(steps) + 1,
                        action="scheduler_stop",
                        project_state_digest_before=status_before.decision.project_state_digest,
                        quota_mode=status_before.quota_state.mode,
                        quota_stale=status_before.quota_state.stale,
                        details=["Scheduler selected no eligible task."],
                    )
                )
                return _finalize(
                    root,
                    auto_run_id=auto_run_id,
                    started_at=started_at,
                    stop_reason=reason,
                    completed_tasks=completed_tasks,
                    attempted_tasks=attempted_tasks,
                    steps=steps,
                )

            if attempts_by_task[task_id] >= policy.max_attempts_per_task:
                steps.append(
                    AutoRunStep(
                        iteration=len(steps) + 1,
                        task_id=task_id,
                        action="retry_budget_exhausted",
                        project_state_digest_before=status_before.decision.project_state_digest,
                        quota_mode=status_before.quota_state.mode,
                        quota_stale=status_before.quota_state.stale,
                    )
                )
                return _finalize(
                    root,
                    auto_run_id=auto_run_id,
                    started_at=started_at,
                    stop_reason=AutoStopReason.RETRY_BUDGET_EXHAUSTED,
                    completed_tasks=completed_tasks,
                    attempted_tasks=attempted_tasks,
                    steps=steps,
                )

            run_id: str | None = None
            details: list[str] = []
            attempted_tasks += 1
            attempts_by_task[task_id] += 1
            try:
                prepared = prepare_next_run(
                    root,
                    requested_strategy=policy.requested_strategy,
                    fallback=StrategyFallbackPolicy(
                        allow_goal_to_plan_then_execute=policy.allow_goal_fallback,
                        allow_plan_to_direct=policy.allow_plan_fallback,
                    ),
                )
                run_id = prepared.record.run_id
                final = _advance_run(root, run_id)
            except ProjectCtlError as exc:
                details.append(str(exc))
                if run_id is None:
                    steps.append(
                        AutoRunStep(
                            iteration=len(steps) + 1,
                            task_id=task_id,
                            action="prepare_failed",
                            project_state_digest_before=status_before.decision.project_state_digest,
                            quota_mode=status_before.quota_state.mode,
                            quota_stale=status_before.quota_state.stale,
                            details=details,
                        )
                    )
                    return _finalize(
                        root,
                        auto_run_id=auto_run_id,
                        started_at=started_at,
                        stop_reason=AutoStopReason.RUN_FAILED,
                        completed_tasks=completed_tasks,
                        attempted_tasks=attempted_tasks,
                        steps=steps,
                    )
                final = RunStore(root).get(run_id)

            stop = _classify_terminal(
                final,
                attempts_by_task[task_id],
                policy,
            )
            if final.status != RunStatus.PASSED:
                steps.append(
                    AutoRunStep(
                        iteration=len(steps) + 1,
                        task_id=task_id,
                        run_id=run_id,
                        started_status=RunStatus.CLAIMED if run_id else None,
                        final_status=final.status,
                        action="execute_task",
                        project_state_digest_before=status_before.decision.project_state_digest,
                        quota_mode=status_before.quota_state.mode,
                        quota_stale=status_before.quota_state.stale,
                        details=details,
                    )
                )
                if stop is not None:
                    return _finalize(
                        root,
                        auto_run_id=auto_run_id,
                        started_at=started_at,
                        stop_reason=stop,
                        completed_tasks=completed_tasks,
                        attempted_tasks=attempted_tasks,
                        steps=steps,
                    )
                continue

            completed_tasks += 1
            status_after = collect_status(root)
            steps.append(
                AutoRunStep(
                    iteration=len(steps) + 1,
                    task_id=task_id,
                    run_id=run_id,
                    started_status=RunStatus.CLAIMED if run_id else None,
                    final_status=final.status,
                    action="execute_task",
                    project_state_digest_before=status_before.decision.project_state_digest,
                    project_state_digest_after=status_after.decision.project_state_digest,
                    quota_mode=status_after.quota_state.mode,
                    quota_stale=status_after.quota_state.stale,
                    details=details,
                )
            )

            if (
                policy.stop_on_material_project_state_change
                and status_after.decision.project_state_digest
                != status_before.decision.project_state_digest
            ):
                return _finalize(
                    root,
                    auto_run_id=auto_run_id,
                    started_at=started_at,
                    stop_reason=AutoStopReason.MATERIAL_PROJECT_STATE_CHANGE,
                    completed_tasks=completed_tasks,
                    attempted_tasks=attempted_tasks,
                    steps=steps,
                )

        return _finalize(
            root,
            auto_run_id=auto_run_id,
            started_at=started_at,
            stop_reason=AutoStopReason.MAX_TASKS_REACHED,
            completed_tasks=completed_tasks,
            attempted_tasks=attempted_tasks,
            steps=steps,
        )
