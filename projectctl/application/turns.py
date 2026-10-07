from __future__ import annotations

import uuid
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
from projectctl.core.digest import digest
from projectctl.core.enums import RunStatus
from projectctl.core.errors import ConfigurationError, PortfolioError, ProjectCtlError
from projectctl.core.time import utc_now
from projectctl.parallel.runtime import (
    build_parallel_integration_queue,
    integrate_parallel_run,
    load_parallel_run_binding,
    prepare_parallel_run,
)
from projectctl.parallel.service import assess_parallel_safety, build_parallel_plan
from projectctl.project.loader import load_project_config
from projectctl.project.locking import project_lock
from projectctl.quota import QuotaManager
from projectctl.quota.admission import project_instance_id
from projectctl.schemas.capabilities import StrategyFallbackPolicy
from projectctl.schemas.orchestration import (
    NonWorkerPhaseStep,
    OrchestrationStatus,
    ProjectMaintenanceResult,
    ProjectTurnEnvelope,
    ProjectTurnResult,
)
from projectctl.storage.runs import RunStore


_ACTIVE = {
    RunStatus.PLANNED,
    RunStatus.PREPARING,
    RunStatus.CLAIMED,
    RunStatus.RUNNING,
    RunStatus.VERIFYING,
    RunStatus.READY_TO_INTEGRATE,
    RunStatus.INTEGRATING,
    RunStatus.AWAITING_REVIEW,
}

_NON_WORKER = {
    RunStatus.VERIFYING,
    RunStatus.READY_TO_INTEGRATE,
    RunStatus.INTEGRATING,
    RunStatus.AWAITING_REVIEW,
}

_ACTION_RANK = {
    "resume_run": 0,
    "start_run": 1,
}


def _active_records(root: Path):
    return sorted(
        (
            item
            for item in RunStore(root).list(limit=1000)
            if item.status in _ACTIVE
        ),
        key=lambda item: (item.created_at, item.run_id),
    )


def _live_lease(record, now) -> bool:
    return (
        record.lease_owner is not None
        and record.lease_expires_at is not None
        and record.lease_expires_at > now
    )


def _excluded(base: ProjectTurnEnvelope, reason: str, detail: str | None = None):
    details = list(base.details)
    if detail:
        details.append(detail)
    return base.model_copy(
        update={
            "eligible": False,
            "action": None,
            "exclusion_reasons": [*base.exclusion_reasons, reason],
            "details": details,
        }
    )


def _continuation(active, *, now):
    candidates = []
    blockers = []
    non_worker = []
    for record in active:
        if _live_lease(record, now):
            if record.status in _NON_WORKER:
                non_worker.append(record)
            else:
                blockers.append((record, "active_run_leased"))
            continue
        if record.status == RunStatus.RUNNING and record.checkpoint_ref:
            candidates.append(("resume_run", record))
        elif record.status == RunStatus.CLAIMED:
            candidates.append(("start_run", record))
        elif record.status in _NON_WORKER:
            non_worker.append(record)
        elif record.status == RunStatus.RUNNING:
            blockers.append((record, "running_without_checkpoint"))
        else:
            blockers.append((record, "run_recovery_required"))
    if candidates:
        candidates.sort(
            key=lambda item: (
                _ACTION_RANK[item[0]],
                item[1].created_at,
                item[1].run_id,
            )
        )
        return candidates[0], blockers, non_worker
    return None, blockers, non_worker


def collect_project_turn_envelope(
    project_root: Path,
    *,
    now=None,
    max_active_runs: int | None = None,
) -> ProjectTurnEnvelope:
    root = project_root.resolve()
    now = now or utc_now()
    if now.tzinfo is None:
        raise ValueError("Turn-envelope evaluation time must be timezone-aware.")

    config = load_project_config(root)
    configured_max = config.orchestration.max_active_runs
    if max_active_runs is None:
        effective_max = configured_max
    else:
        if max_active_runs < 1 or max_active_runs > configured_max:
            raise ConfigurationError(
                f"Requested max_active_runs={max_active_runs} must be between 1 "
                f"and configured orchestration.max_active_runs={configured_max}."
            )
        effective_max = max_active_runs

    active = _active_records(root)
    non_worker_ids = [
        item.run_id for item in active if item.status in _NON_WORKER
    ]
    queue_head = None
    try:
        queue = build_parallel_integration_queue(root, persist=False)
        if queue.entries:
            queue_head = queue.entries[0].run_id
    except ProjectCtlError:
        queue_head = None

    base = ProjectTurnEnvelope(
        envelope_id=f"turn-{uuid.uuid4().hex}",
        observed_at=now,
        project_instance_id=project_instance_id(root),
        project_id=config.project.id,
        project_root=str(root),
        account_id=config.quota.account,
        active_run_ids=[item.run_id for item in active],
        active_run_count=len(active),
        max_active_runs=effective_max,
        non_worker_run_ids=non_worker_ids,
        integration_queue_head_run_id=queue_head,
    )

    status = collect_status(root, now=now, record_telemetry=False)
    base = base.model_copy(
        update={
            "project_state_digest": status.decision.project_state_digest,
            "task_snapshot_digest": status.decision.task_snapshot_digest,
            "quota_snapshot_digest": status.decision.quota_snapshot_digest,
            "quota_mode": status.quota_state.mode,
            "quota_stale": status.quota_state.stale,
        }
    )
    if status.quota_state.stale:
        return _excluded(base, "quota_stale")

    continuation, blockers, _ = _continuation(active, now=now)
    if blockers:
        return _excluded(
            base,
            "active_set_recovery_required",
            ",".join(
                f"{record.run_id}:{reason}" for record, reason in blockers
            ),
        )

    if continuation is not None:
        action, record = continuation
        task = next(
            (item for item in status.tasks.tasks if item.id == record.task_id),
            None,
        )
        if task is None:
            return _excluded(
                base,
                "active_task_missing",
                f"run_id={record.run_id} task_id={record.task_id}",
            )
        manager = QuotaManager(config.quota)
        if not manager.eligible_for_resource(task.resource_class, status.quota_state):
            return _excluded(base, "quota_insufficient")
        return base.model_copy(
            update={
                "eligible": True,
                "action": action,
                "run_id": record.run_id,
                "run_status": record.status,
                "task_id": record.task_id,
                "resource_class": task.resource_class,
            }
        )

    if len(active) >= effective_max:
        return _excluded(base, "active_set_capacity_reached")

    task_id = status.decision.selected_task_id
    if task_id is None:
        return _excluded(base, "no_eligible_task")
    task = next((item for item in status.tasks.tasks if item.id == task_id), None)
    if task is None:
        return _excluded(base, "selected_task_missing", f"task_id={task_id}")

    manager = QuotaManager(config.quota)
    if not manager.eligible_for_resource(task.resource_class, status.quota_state):
        return _excluded(base, "quota_insufficient")

    # If the project is configured for more than one active run, every
    # automated new run is parallel-bound from its first slot. Otherwise a
    # serial first run would become an unbound peer and make the second slot
    # impossible to admit safely.
    parallel_admission = effective_max > 1
    if parallel_admission:
        bindings = []
        for record in active:
            binding = load_parallel_run_binding(
                root,
                record.run_id,
                allow_missing=True,
            )
            if binding is None:
                return _excluded(
                    base,
                    "active_run_not_parallel_bound",
                    f"run_id={record.run_id}",
                )
            bindings.append(binding)

        try:
            proposed = build_parallel_plan(
                root,
                task_id,
                persist=False,
            )
        except ProjectCtlError as exc:
            return _excluded(
                base,
                "parallel_proof_unavailable",
                str(exc),
            )

        for binding in bindings:
            decision = assess_parallel_safety(
                proposed,
                binding.admitted_plan,
            )
            if not decision.independent:
                reasons = ",".join(
                    sorted({item.reason for item in decision.conflicts})
                )
                return _excluded(
                    base,
                    "parallel_conflict",
                    f"peer={binding.run_id} reasons={reasons}",
                )

    return base.model_copy(
        update={
            "eligible": True,
            "action": "admit_task",
            "task_id": task_id,
            "resource_class": task.resource_class,
            "parallel_admission": parallel_admission,
        }
    )


def _turn_key(value: ProjectTurnEnvelope):
    return (
        value.project_instance_id,
        value.project_id,
        value.account_id,
        value.action,
        value.run_id,
        value.run_status,
        value.task_id,
        value.project_state_digest,
        value.task_snapshot_digest,
        tuple(value.active_run_ids),
        value.max_active_runs,
        value.parallel_admission,
    )


def execute_project_turn(
    project_root: Path,
    envelope: ProjectTurnEnvelope,
    *,
    requested_strategy=None,
    fallback: StrategyFallbackPolicy | None = None,
) -> ProjectTurnResult:
    root = project_root.resolve()
    with project_lock(root, "worker-turn-dispatch"):
        current = collect_project_turn_envelope(
            root,
            max_active_runs=envelope.max_active_runs,
        )
        if not current.eligible or _turn_key(current) != _turn_key(envelope):
            raise PortfolioError(
                "Project worker-turn envelope became stale before execution."
            )
        if current.action is None or current.task_id is None:
            raise PortfolioError("Eligible project turn is incomplete.")

        prepared_new = False
        if current.action == "resume_run":
            if current.run_id is None:
                raise PortfolioError("Resume turn is missing run identity.")
            result = resume_checkpointed_run(root, current.run_id)
        elif current.action == "start_run":
            if current.run_id is None:
                raise PortfolioError("Start turn is missing run identity.")
            result = start_prepared_run(root, current.run_id)
        else:
            if (
                current.task_snapshot_digest is None
                or current.project_state_digest is None
            ):
                raise PortfolioError(
                    "Admission turn is missing scheduler input digests."
                )
            if current.parallel_admission:
                prepared = prepare_parallel_run(
                    root,
                    max_parallel_runs=current.max_active_runs,
                    requested_strategy=requested_strategy,
                    fallback=fallback,
                    expected_task_id=current.task_id,
                    expected_task_snapshot_digest=current.task_snapshot_digest,
                    expected_project_state_digest=current.project_state_digest,
                )
            else:
                prepared = prepare_next_run(
                    root,
                    requested_strategy=requested_strategy,
                    fallback=fallback,
                    expected_task_id=current.task_id,
                    expected_task_snapshot_digest=current.task_snapshot_digest,
                    expected_project_state_digest=current.project_state_digest,
                )
            prepared_new = True
            result = start_prepared_run(root, prepared.record.run_id)

        return ProjectTurnResult(
            envelope=current,
            run_id=result.record.run_id,
            run_status=result.record.status,
            prepared_new_run=prepared_new,
        )

def collect_orchestration_status(project_root: Path) -> OrchestrationStatus:
    root = project_root.resolve()
    now = utc_now()
    envelope = collect_project_turn_envelope(root, now=now)
    from projectctl.project.bootstrap import projectctl_home
    from projectctl.quota.admission import AccountAdmissionStore

    admission = AccountAdmissionStore(projectctl_home(), clock=lambda: now).get(
        envelope.account_id
    )
    account_busy = admission is not None and admission.expires_at > now
    return OrchestrationStatus(
        generated_at=now,
        project_instance_id=envelope.project_instance_id,
        project_id=envelope.project_id,
        project_root=envelope.project_root,
        account_id=envelope.account_id,
        active_run_ids=envelope.active_run_ids,
        active_run_count=envelope.active_run_count,
        max_active_runs=envelope.max_active_runs,
        non_worker_run_ids=envelope.non_worker_run_ids,
        integration_queue_head_run_id=envelope.integration_queue_head_run_id,
        next_worker_turn=envelope,
        account_admission_run_id=(
            admission.run_id if account_busy and admission is not None else None
        ),
        account_admission_project_instance_id=(
            admission.project_instance_id
            if account_busy and admission is not None
            else None
        ),
        account_busy=account_busy,
    )



def advance_non_worker_phases(
    project_root: Path,
) -> ProjectMaintenanceResult:
    """Advance only lifecycle phases that do not consume a worker turn."""
    root = project_root.resolve()
    config = load_project_config(root)
    steps: list[NonWorkerPhaseStep] = []

    for record in _active_records(root):
        started = record.status
        action = "phase_wait"
        detail = None
        final = record
        try:
            if record.status == RunStatus.PLANNED:
                action = "unsafe_planned"
                detail = (
                    "PLANNED has no durable claim/worktree proof; automatic "
                    "maintenance will not guess prepare progress."
                )
            elif record.status == RunStatus.PREPARING:
                action = "recover_prepare"
                recover_run(root, record.run_id)
                final = RunStore(root).get(record.run_id)
            elif record.status == RunStatus.RUNNING:
                if record.checkpoint_ref:
                    action = "skip_worker_turn"
                    detail = "Checkpointed RUNNING requires a portfolio worker turn."
                else:
                    action = "recover_running"
                    recover_run(root, record.run_id)
                    final = RunStore(root).get(record.run_id)
            elif record.status == RunStatus.CLAIMED:
                action = "skip_worker_turn"
                detail = "CLAIMED requires a portfolio worker turn."
            elif record.status == RunStatus.VERIFYING:
                action = "verify"
                verify_run(root, record.run_id)
                final = RunStore(root).get(record.run_id)
            elif record.status == RunStatus.READY_TO_INTEGRATE:
                action = "integrate"
                binding = load_parallel_run_binding(
                    root,
                    record.run_id,
                    allow_missing=True,
                )
                if binding is None:
                    integrate_run(root, record.run_id)
                else:
                    integrate_parallel_run(root, record.run_id)
                final = RunStore(root).get(record.run_id)
            elif record.status in {
                RunStatus.INTEGRATING,
                RunStatus.AWAITING_REVIEW,
            }:
                action = "recover_delivery"
                recover_run(root, record.run_id)
                final = RunStore(root).get(record.run_id)
        except ProjectCtlError as exc:
            final = RunStore(root).get(record.run_id)
            detail = str(exc)

        steps.append(
            NonWorkerPhaseStep(
                run_id=record.run_id,
                task_id=record.task_id,
                started_status=started,
                final_status=final.status,
                action=action,
                detail=detail,
            )
        )

    return ProjectMaintenanceResult(
        generated_at=utc_now(),
        project_id=config.project.id,
        project_root=str(root),
        steps=steps,
        active_run_ids_after=[
            item.run_id for item in _active_records(root)
        ],
    )
