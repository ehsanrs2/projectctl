from __future__ import annotations

from pathlib import Path

from projectctl.core.enums import RunStatus, RunTerminalReason
from projectctl.core.errors import ConfigurationError
from projectctl.integrations.beads.claim import BeadsTaskClaimer
from projectctl.integrations.beads.completion import BeadsTaskCompletionWriter
from projectctl.project.loader import load_project_config
from projectctl.storage.runs import RunStore


def _provider(project_root: Path) -> str:
    return load_project_config(project_root).task_store.provider


def release_task_for_retry(project_root: Path, task_id: str, *, actor: str) -> None:
    provider = _provider(project_root)
    if provider == "beads":
        BeadsTaskClaimer(project_root).release(task_id, actor=actor)
        return
    raise ConfigurationError(
        f"Task release is not implemented for provider {provider!r}."
    )


def block_task_for_decision(project_root: Path, task_id: str, *, reason: str) -> None:
    provider = _provider(project_root)
    if provider == "beads":
        BeadsTaskCompletionWriter(project_root).mark_needs_decision(
            task_id,
            reason=reason,
        )
        return
    raise ConfigurationError(
        f"Task decision blocking is not implemented for provider {provider!r}."
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
                record.task_id,
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
