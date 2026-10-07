from __future__ import annotations

import json
import os
import tempfile
import uuid
from collections import Counter
from datetime import datetime
from pathlib import Path

from projectctl.application.portfolio import request_fair_project_turn
from projectctl.application.status import collect_status
from projectctl.application.turns import advance_non_worker_phases
from projectctl.core.enums import (
    AutoStopReason,
    QuotaMode,
    RunStatus,
    RunTerminalReason,
)
from projectctl.core.time import utc_now
from projectctl.project.locking import project_lock
from projectctl.schemas.auto import AutoRunPolicy, AutoRunReport, AutoRunStep
from projectctl.schemas.capabilities import StrategyFallbackPolicy
from projectctl.schemas.execution import ExecutionPlan, parse_execution_plan
from projectctl.storage.runs import RunStore


_ACTIVE_STATUSES = {
    RunStatus.PLANNED,
    RunStatus.PREPARING,
    RunStatus.CLAIMED,
    RunStatus.RUNNING,
    RunStatus.VERIFYING,
    RunStatus.READY_TO_INTEGRATE,
    RunStatus.INTEGRATING,
    RunStatus.AWAITING_REVIEW,
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
    fd, tmp_name = tempfile.mkstemp(
        prefix=".projectctl-",
        suffix=".json",
        dir=path.parent,
    )
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
    return sorted(
        (
            record
            for record in store.list(limit=1000)
            if record.status in _ACTIVE_STATUSES
        ),
        key=lambda item: (item.created_at, item.run_id),
    )


def _execution_plan_state_digest(project_root: Path, run_id: str) -> str | None:
    path = (
        project_root
        / ".projectctl"
        / "runs"
        / run_id
        / "execution-plan.json"
    )
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return parse_execution_plan(raw).project_state_digest
    except Exception:
        return None


def _classify_terminal(
    record,
    attempts_for_task: int,
    policy: AutoRunPolicy,
):
    if (
        record.status == RunStatus.RUNNING
        and getattr(record, "checkpoint_ref", None)
    ):
        return AutoStopReason.QUOTA_CHECKPOINTED
    if record.status == RunStatus.PASSED:
        return None
    if record.status == RunStatus.AWAITING_REVIEW:
        return AutoStopReason.REVIEW_PENDING
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


def _maintenance_details(result) -> list[str]:
    details = []
    for step in result.steps:
        text = (
            f"maintenance:{step.run_id}:{step.action}:"
            f"{step.started_status.value}->{step.final_status.value}"
        )
        if step.detail:
            text += f":{step.detail}"
        details.append(text)
    return details


def _drain_non_worker_phases(
    project_root: Path,
    *,
    max_passes: int = 8,
) -> list[str]:
    details: list[str] = []
    previous = None
    for _ in range(max_passes):
        before = tuple(
            (item.run_id, item.status.value)
            for item in _active_runs(RunStore(project_root))
        )
        if before == previous:
            break
        previous = before
        result = advance_non_worker_phases(project_root)
        details.extend(_maintenance_details(result))
        after = tuple(
            (item.run_id, item.status.value)
            for item in _active_runs(RunStore(project_root))
        )
        if after == before or not after:
            break
    return details


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


def _portfolio_yield_step(
    *,
    iteration: int,
    decision,
    task_id: str | None = None,
    run_id: str | None = None,
    started_status: RunStatus | None = None,
    details: list[str] | None = None,
) -> AutoRunStep:
    extra = list(details or [])
    if decision.account_busy:
        extra.append(
            "account_busy:"
            f"project={decision.active_project_instance_id}:"
            f"run={decision.active_run_id}"
        )
    elif decision.selected_project_instance_id is not None:
        extra.append(
            "portfolio_selected_other_project:"
            f"{decision.selected_project_id}/"
            f"{decision.selected_project_instance_id}"
        )
    else:
        extra.append("portfolio_has_no_eligible_worker_turn")
    return AutoRunStep(
        iteration=iteration,
        task_id=task_id,
        run_id=run_id,
        started_status=started_status,
        final_status=started_status,
        action="portfolio_yield",
        details=extra,
    )


def run_auto(
    project_root: Path,
    policy: AutoRunPolicy | None = None,
) -> AutoRunReport:
    root = project_root.resolve()
    policy = policy or AutoRunPolicy()
    auto_run_id = f"auto-{uuid.uuid4().hex}"
    started_at = utc_now()
    steps: list[AutoRunStep] = []
    completed_tasks = 0
    attempted_tasks = 0
    attempts_by_task: Counter[str] = Counter()
    fallback = StrategyFallbackPolicy(
        allow_goal_to_plan_then_execute=policy.allow_goal_fallback,
        allow_plan_to_direct=policy.allow_plan_fallback,
    )

    with project_lock(root, "auto-loop"):
        while attempted_tasks < policy.max_tasks:
            maintenance_details: list[str] = []
            store = RunStore(root)
            active = _active_runs(store)

            # Serial auto intentionally does not adopt a parallel active-set.
            # Worker turns are still globally fair; parallel ownership belongs
            # to the explicit parallel/portfolio orchestrator.
            if len(active) > 1:
                steps.append(
                    AutoRunStep(
                        iteration=len(steps) + 1,
                        action="multiple_active_runs",
                        details=[
                            *maintenance_details,
                            *[record.run_id for record in active],
                        ],
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

            if active:
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
                                (
                                    "lease_expires_at="
                                    f"{record.lease_expires_at.isoformat()}"
                                ),
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

                if record.status == RunStatus.PLANNED:
                    steps.append(
                        AutoRunStep(
                            iteration=len(steps) + 1,
                            task_id=record.task_id,
                            run_id=record.run_id,
                            started_status=record.status,
                            final_status=record.status,
                            action="unsafe_partial_prepare",
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

                if (
                    attempts_by_task[record.task_id]
                    >= policy.max_attempts_per_task
                ):
                    return _finalize(
                        root,
                        auto_run_id=auto_run_id,
                        started_at=started_at,
                        stop_reason=AutoStopReason.RETRY_BUDGET_EXHAUSTED,
                        completed_tasks=completed_tasks,
                        attempted_tasks=attempted_tasks,
                        steps=steps,
                    )

                attempted_tasks += 1
                attempts_by_task[record.task_id] += 1
                started_status = record.status
                state_before = _execution_plan_state_digest(
                    root,
                    record.run_id,
                )

                worker_ready = (
                    record.status == RunStatus.CLAIMED
                    or (
                        record.status == RunStatus.RUNNING
                        and record.checkpoint_ref
                    )
                )
                if not worker_ready:
                    maintenance_details = _drain_non_worker_phases(root)
                    final = RunStore(root).get(record.run_id)

                    if final.status == RunStatus.PASSED:
                        completed_tasks += 1
                        status_after = collect_status(root)
                        steps.append(
                            AutoRunStep(
                                iteration=len(steps) + 1,
                                task_id=record.task_id,
                                run_id=record.run_id,
                                started_status=started_status,
                                final_status=final.status,
                                action="resume_non_worker",
                                project_state_digest_before=state_before,
                                project_state_digest_after=(
                                    status_after.decision.project_state_digest
                                ),
                                quota_mode=status_after.quota_state.mode,
                                quota_stale=status_after.quota_state.stale,
                                details=maintenance_details,
                            )
                        )
                        if (
                            policy.stop_on_material_project_state_change
                            and state_before is not None
                            and state_before
                            != status_after.decision.project_state_digest
                        ):
                            return _finalize(
                                root,
                                auto_run_id=auto_run_id,
                                started_at=started_at,
                                stop_reason=(
                                    AutoStopReason.MATERIAL_PROJECT_STATE_CHANGE
                                ),
                                completed_tasks=completed_tasks,
                                attempted_tasks=attempted_tasks,
                                steps=steps,
                            )
                        continue

                    worker_ready = (
                        final.status == RunStatus.CLAIMED
                        or (
                            final.status == RunStatus.RUNNING
                            and final.checkpoint_ref
                        )
                    )
                    if not worker_ready:
                        stop = _classify_terminal(
                            final,
                            attempts_by_task[record.task_id],
                            policy,
                        )
                        steps.append(
                            AutoRunStep(
                                iteration=len(steps) + 1,
                                task_id=record.task_id,
                                run_id=record.run_id,
                                started_status=started_status,
                                final_status=final.status,
                                action="resume_non_worker",
                                project_state_digest_before=state_before,
                                details=maintenance_details,
                            )
                        )
                        return _finalize(
                            root,
                            auto_run_id=auto_run_id,
                            started_at=started_at,
                            stop_reason=(
                                stop or AutoStopReason.RECOVERY_REQUIRED
                            ),
                            completed_tasks=completed_tasks,
                            attempted_tasks=attempted_tasks,
                            steps=steps,
                        )
                    record = final

                decision, turn = request_fair_project_turn(
                    root,
                    requested_strategy=policy.requested_strategy,
                    fallback=fallback,
                )
                if turn is None:
                    steps.append(
                        _portfolio_yield_step(
                            iteration=len(steps) + 1,
                            decision=decision,
                            task_id=record.task_id,
                            run_id=record.run_id,
                            started_status=started_status,
                            details=maintenance_details,
                        )
                    )
                    return _finalize(
                        root,
                        auto_run_id=auto_run_id,
                        started_at=started_at,
                        stop_reason=AutoStopReason.PORTFOLIO_YIELD,
                        completed_tasks=completed_tasks,
                        attempted_tasks=attempted_tasks,
                        steps=steps,
                    )
                if turn.run_id != record.run_id:
                    steps.append(
                        AutoRunStep(
                            iteration=len(steps) + 1,
                            task_id=record.task_id,
                            run_id=record.run_id,
                            started_status=started_status,
                            final_status=record.status,
                            action="turn_identity_mismatch",
                            details=[
                                *maintenance_details,
                                f"dispatcher_run={turn.run_id}",
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

                details = [
                    *maintenance_details,
                    *_drain_non_worker_phases(root),
                ]
                final = RunStore(root).get(record.run_id)
                stop = _classify_terminal(
                    final,
                    attempts_by_task[record.task_id],
                    policy,
                )
                status_after = collect_status(root)
                steps.append(
                    AutoRunStep(
                        iteration=len(steps) + 1,
                        task_id=record.task_id,
                        run_id=record.run_id,
                        started_status=started_status,
                        final_status=final.status,
                        action=turn.project_turn.envelope.action or "worker_turn",
                        project_state_digest_before=state_before,
                        project_state_digest_after=(
                            status_after.decision.project_state_digest
                        ),
                        quota_mode=status_after.quota_state.mode,
                        quota_stale=status_after.quota_state.stale,
                        details=details,
                    )
                )
                if final.status == RunStatus.PASSED:
                    completed_tasks += 1
                    if (
                        policy.stop_on_material_project_state_change
                        and state_before is not None
                        and state_before
                        != status_after.decision.project_state_digest
                    ):
                        return _finalize(
                            root,
                            auto_run_id=auto_run_id,
                            started_at=started_at,
                            stop_reason=(
                                AutoStopReason.MATERIAL_PROJECT_STATE_CHANGE
                            ),
                            completed_tasks=completed_tasks,
                            attempted_tasks=attempted_tasks,
                            steps=steps,
                        )
                    continue
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

            status_before = collect_status(root)
            if (
                policy.stop_on_stale_quota
                and status_before.quota_state.stale
            ):
                steps.append(
                    AutoRunStep(
                        iteration=len(steps) + 1,
                        action="quota_checkpoint",
                        project_state_digest_before=(
                            status_before.decision.project_state_digest
                        ),
                        quota_mode=status_before.quota_state.mode,
                        quota_stale=True,
                        details=[
                            "Autonomous mode requires a fresh quota snapshot."
                        ],
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
                        project_state_digest_before=(
                            status_before.decision.project_state_digest
                        ),
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
                return _finalize(
                    root,
                    auto_run_id=auto_run_id,
                    started_at=started_at,
                    stop_reason=(
                        AutoStopReason.COMPLETED
                        if done
                        else AutoStopReason.NO_ELIGIBLE_TASK
                    ),
                    completed_tasks=completed_tasks,
                    attempted_tasks=attempted_tasks,
                    steps=steps,
                )

            if (
                attempts_by_task[task_id]
                >= policy.max_attempts_per_task
            ):
                return _finalize(
                    root,
                    auto_run_id=auto_run_id,
                    started_at=started_at,
                    stop_reason=AutoStopReason.RETRY_BUDGET_EXHAUSTED,
                    completed_tasks=completed_tasks,
                    attempted_tasks=attempted_tasks,
                    steps=steps,
                )

            attempted_tasks += 1
            attempts_by_task[task_id] += 1
            decision, turn = request_fair_project_turn(
                root,
                requested_strategy=policy.requested_strategy,
                fallback=fallback,
            )
            if turn is None:
                steps.append(
                    _portfolio_yield_step(
                        iteration=len(steps) + 1,
                        decision=decision,
                        task_id=task_id,
                    )
                )
                return _finalize(
                    root,
                    auto_run_id=auto_run_id,
                    started_at=started_at,
                    stop_reason=AutoStopReason.PORTFOLIO_YIELD,
                    completed_tasks=completed_tasks,
                    attempted_tasks=attempted_tasks,
                    steps=steps,
                )

            after_details = _drain_non_worker_phases(root)
            final = RunStore(root).get(turn.run_id)
            stop = _classify_terminal(
                final,
                attempts_by_task[task_id],
                policy,
            )
            status_after = collect_status(root)
            steps.append(
                AutoRunStep(
                    iteration=len(steps) + 1,
                    task_id=task_id,
                    run_id=turn.run_id,
                    started_status=RunStatus.CLAIMED,
                    final_status=final.status,
                    action=turn.project_turn.envelope.action or "worker_turn",
                    project_state_digest_before=(
                        status_before.decision.project_state_digest
                    ),
                    project_state_digest_after=(
                        status_after.decision.project_state_digest
                    ),
                    quota_mode=status_after.quota_state.mode,
                    quota_stale=status_after.quota_state.stale,
                    details=after_details,
                )
            )
            if final.status == RunStatus.PASSED:
                completed_tasks += 1
                if (
                    policy.stop_on_material_project_state_change
                    and status_after.decision.project_state_digest
                    != status_before.decision.project_state_digest
                ):
                    return _finalize(
                        root,
                        auto_run_id=auto_run_id,
                        started_at=started_at,
                        stop_reason=(
                            AutoStopReason.MATERIAL_PROJECT_STATE_CHANGE
                        ),
                        completed_tasks=completed_tasks,
                        attempted_tasks=attempted_tasks,
                        steps=steps,
                    )
                continue
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

        return _finalize(
            root,
            auto_run_id=auto_run_id,
            started_at=started_at,
            stop_reason=AutoStopReason.MAX_TASKS_REACHED,
            completed_tasks=completed_tasks,
            attempted_tasks=attempted_tasks,
            steps=steps,
        )
