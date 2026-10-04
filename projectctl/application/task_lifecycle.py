from __future__ import annotations

from pathlib import Path

from projectctl.application.claims import (
    load_durable_claim,
    record_claim_release,
)
from projectctl.core.enums import RunStatus, RunTerminalReason
from projectctl.integrations.task_authority import resolve_task_authority
from projectctl.storage.runs import RunStore


def release_task_for_retry(
    project_root: Path,
    *,
    store: RunStore,
    run_id: str,
    actor: str,
) -> None:
    del actor
    _, claim = load_durable_claim(
        project_root,
        store=store,
        run_id=run_id,
    )
    resolve_task_authority(project_root).require_claimer().release(claim)
    record_claim_release(store, claim)


def block_task_for_decision(project_root: Path, task_id: str, *, reason: str) -> None:
    resolve_task_authority(project_root).require_completion_writer().mark_needs_decision(
        task_id,
        reason=reason,
    )


def reconcile_terminal_task(
    project_root: Path,
    *,
    store: RunStore,
    run_id: str,
    actor: str,
):
    """Make canonical task state agree with a terminal/blocked run state.

    Retryable terminal outcomes release the task. Human-decision outcomes
    unassign and block it. Reconciliation failure escalates the run to a
    durable RECOVERY_UNSAFE decision state instead of silently stranding the
    task in RUNNING.
    """

    record = store.get(run_id)
    action: str | None = None
    try:
        if record.status in {
            RunStatus.FAILED,
            RunStatus.CANCELLED,
            RunStatus.ABANDONED,
        }:
            release_task_for_retry(
                project_root,
                store=store,
                run_id=run_id,
                actor=actor,
            )
            action = "released"
        elif record.status in {
            RunStatus.NEEDS_DECISION,
            RunStatus.BLOCKED_POLICY,
        }:
            reason = (
                record.terminal_reason.value
                if record.terminal_reason is not None
                else "human_decision_required"
            )
            block_task_for_decision(
                project_root,
                record.task_id,
                reason=reason,
            )
            action = "blocked"
        else:
            return record

        store.append_event(
            run_id,
            "task.reconciled",
            {"action": action, "run_status": record.status.value},
        )
        return store.get(run_id)
    except Exception as exc:
        store.append_event(
            run_id,
            "task.reconcile_failed",
            {
                "run_status": record.status.value,
                "error": str(exc),
            },
        )
        if not (
            record.status == RunStatus.NEEDS_DECISION
            and record.terminal_reason == RunTerminalReason.RECOVERY_UNSAFE
        ):
            try:
                store.transition(
                    run_id,
                    expected={record.status},
                    status=RunStatus.NEEDS_DECISION,
                    terminal_reason=RunTerminalReason.RECOVERY_UNSAFE,
                )
            except Exception:
                pass
        return store.get(run_id)
