from __future__ import annotations

from pathlib import Path

from projectctl.application.claims import (
    load_durable_claim,
    record_claim_release,
)
from projectctl.core.digest import digest
from projectctl.core.enums import RunStatus, RunTerminalReason
from projectctl.integrations.execution_ownership import resolve_execution_ownership
from projectctl.integrations.task_authority import (
    resolve_task_authority,
    task_delivery_policy,
)
from projectctl.storage.runs import RunStore


def release_task_for_retry(
    project_root: Path,
    *,
    store: RunStore,
    run_id: str,
    actor: str,
) -> None:
    claimer = resolve_execution_ownership(project_root).claimer
    durable = load_durable_claim(
        project_root,
        store=store,
        run_id=run_id,
        allow_legacy_missing=True,
        require_acquired=False,
    )
    if durable is None:
        record = store.get(run_id)
        claimer.release_legacy(record.task_id, actor=actor)
        store.append_event(
            run_id,
            "task.claim.released_legacy",
            {"task_id": record.task_id},
        )
        return
    _, claim = durable
    if not claim.acquired:
        store.append_event(
            run_id,
            "task.claim.release_not_required",
            {"claim_digest": digest(claim)},
        )
        return
    if not claimer.validate(claim):
        store.append_event(
            run_id,
            "task.claim.ownership_lost",
            {
                "claim_digest": digest(claim),
                "ownership_ref": claim.ownership_ref,
                "ownership_sha": claim.ownership_sha,
            },
        )
        return
    claimer.release(claim)
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
            policy = task_delivery_policy(project_root)
            if policy.release_claim_after_decision_block:
                release_task_for_retry(
                    project_root,
                    store=store,
                    run_id=run_id,
                    actor=actor,
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
