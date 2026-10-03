from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from projectctl.application.tasks import capture_task_snapshot
from projectctl.core.time import utc_now
from projectctl.project.loader import load_project_config
from projectctl.project.state import load_project_state
from projectctl.quota.manual import ManualQuotaProvider
from projectctl.scheduler import SchedulerService
from projectctl.schemas.config import ProjectConfig
from projectctl.schemas.project_state import ProjectState
from projectctl.schemas.quota import QuotaSnapshot
from projectctl.schemas.scheduler import SchedulerDecision
from projectctl.schemas.task import TaskSnapshot
from projectctl.telemetry import record_event


@dataclass(frozen=True)
class SchedulingBundle:
    config: ProjectConfig
    tasks: TaskSnapshot
    quota: QuotaSnapshot
    project_state: ProjectState
    decision: SchedulerDecision


def current_quota(project_root: Path) -> QuotaSnapshot:
    config = load_project_config(project_root)
    return ManualQuotaProvider().get_snapshot(config.quota.account)


def collect_scheduling_bundle(
    project_root: Path,
    *,
    now: datetime | None = None,
    record_telemetry: bool = True,
) -> SchedulingBundle:
    evaluation_time = now or utc_now()
    config = load_project_config(project_root)
    tasks = capture_task_snapshot(project_root, state="all")
    quota = ManualQuotaProvider().get_snapshot(config.quota.account)
    project_state = load_project_state(project_root, allow_missing=True)
    decision = SchedulerService().decide(
        config=config,
        tasks=tasks,
        quota=quota,
        project_state=project_state,
        now=evaluation_time,
    )
    if record_telemetry:
        record_event(project_root, "scheduler.decision", decision)
        if decision.selected_task_id:
            selected = next(
                (c for c in decision.candidates if c.task_id == decision.selected_task_id),
                None,
            )
            if selected and selected.model:
                record_event(project_root, "model.recommendation", selected.model)
    return SchedulingBundle(
        config=config,
        tasks=tasks,
        quota=quota,
        project_state=project_state,
        decision=decision,
    )


def scheduling_decision(project_root: Path, *, now: datetime | None = None) -> SchedulerDecision:
    return collect_scheduling_bundle(project_root, now=now).decision
