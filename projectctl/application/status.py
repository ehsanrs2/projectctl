from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from projectctl.application.tasks import capture_task_snapshot
from projectctl.core.digest import digest
from projectctl.core.enums import TaskStatus
from projectctl.core.time import utc_now
from projectctl.project.loader import load_project_config
from projectctl.project.state import load_project_state
from projectctl.quota import QuotaManager, QuotaState, read_current_quota
from projectctl.scheduler import SchedulerService
from projectctl.schemas.project_state import ProjectState
from projectctl.schemas.quota import QuotaSnapshot
from projectctl.schemas.scheduler import SchedulerDecision
from projectctl.schemas.status import ProjectStatus, StatusSourceDigests, TaskCounts
from projectctl.schemas.task import TaskSnapshot
from projectctl.telemetry import record_event


@dataclass(frozen=True)
class StatusBundle:
    status: ProjectStatus
    project_state: ProjectState
    tasks: TaskSnapshot
    quota: QuotaSnapshot
    quota_state: QuotaState
    decision: SchedulerDecision
    source_digest: str


def _task_counts(snapshot: TaskSnapshot) -> TaskCounts:
    counts = TaskCounts(total=len(snapshot.tasks))
    values = counts.model_dump()
    mapping = {
        TaskStatus.READY: "ready",
        TaskStatus.BLOCKED: "blocked",
        TaskStatus.RUNNING: "running",
        TaskStatus.DONE: "done",
        TaskStatus.FAILED: "failed",
        TaskStatus.NEEDS_DECISION: "needs_decision",
    }
    for task in snapshot.tasks:
        field = mapping.get(task.status)
        if field:
            values[field] += 1
    return TaskCounts.model_validate(values)


def collect_status(
    project_root: Path,
    *,
    now: datetime | None = None,
    record_telemetry: bool = True,
) -> StatusBundle:
    now = now or utc_now()
    config = load_project_config(project_root)
    project_state = load_project_state(project_root, allow_missing=True)
    tasks = capture_task_snapshot(project_root, state="all")
    quota = read_current_quota(config.quota.account)
    quota_state = QuotaManager(config.quota).state(quota, now=now)
    decision = SchedulerService().decide(
        config=config,
        tasks=tasks,
        quota=quota,
        project_state=project_state,
        now=now,
    )

    selected = next(
        (c for c in decision.candidates if c.task_id == decision.selected_task_id),
        None,
    )
    digests = StatusSourceDigests(
        project_state=decision.project_state_digest,
        tasks=decision.task_snapshot_digest,
        quota=decision.quota_snapshot_digest,
    )
    status = ProjectStatus(
        generated_at=now,
        project_id=config.project.id,
        current_goal=project_state.current_goal,
        active_milestone=project_state.active_milestone,
        task_counts=_task_counts(tasks),
        quota_mode=quota_state.mode,
        quota_stale=quota_state.stale,
        next_task_id=decision.selected_task_id,
        next_model_profile=selected.model.profile if selected and selected.model else None,
        next_reasoning=selected.model.reasoning if selected and selected.model else None,
        source_digests=digests,
    )
    source_digest = digest(digests)
    if record_telemetry:
        record_event(project_root, "project.status", status)
        record_event(project_root, "scheduler.decision", decision)
        if selected and selected.model:
            record_event(project_root, "model.recommendation", selected.model)
    return StatusBundle(
        status=status,
        project_state=project_state,
        tasks=tasks,
        quota=quota,
        quota_state=quota_state,
        decision=decision,
        source_digest=source_digest,
    )
