from __future__ import annotations

from datetime import datetime

from projectctl.core.digest import digest
from projectctl.quota.manager import QuotaManager
from projectctl.scheduler.digests import semantic_task_snapshot_digest
from projectctl.scheduler.eligibility import evaluate_eligibility
from projectctl.scheduler.router import recommend_model
from projectctl.scheduler.scoring import score_task
from projectctl.schemas.config import ProjectConfig
from projectctl.schemas.quota import QuotaSnapshot
from projectctl.schemas.scheduler import SchedulerCandidate, SchedulerDecision
from projectctl.schemas.task import NormalizedTask, TaskSnapshot


class SchedulerService:
    def decide(
        self,
        *,
        config: ProjectConfig,
        tasks: TaskSnapshot,
        quota: QuotaSnapshot,
        now: datetime,
    ) -> SchedulerDecision:
        manager = QuotaManager(config.quota)
        quota_state = manager.state(quota, now=now)
        by_id = {task.id: task for task in tasks.tasks}
        candidates: list[SchedulerCandidate] = []

        eligible_pairs: list[tuple[NormalizedTask, SchedulerCandidate]] = []
        for task in sorted(tasks.tasks, key=lambda item: item.id):
            eligibility = evaluate_eligibility(
                task,
                tasks_by_id=by_id,
                quota_manager=manager,
                quota_state=quota_state,
            )
            candidate = SchedulerCandidate(task_id=task.id, eligibility=eligibility)
            if eligibility.eligible:
                candidate.score = score_task(task, config=config.scheduler, quota_mode=quota_state.mode, now=now)
                candidate.model = recommend_model(task, quota_mode=quota_state.mode, config=config)
                eligible_pairs.append((task, candidate))
            candidates.append(candidate)

        def ranking(item: tuple[NormalizedTask, SchedulerCandidate]):
            task, candidate = item
            score = candidate.score.total if candidate.score else float("-inf")
            ready = task.ready_since or task.created_at
            ready_key = ready.timestamp() if ready else float("inf")
            return (-score, -task.priority, -len(task.blocks), ready_key, task.id)

        eligible_pairs.sort(key=ranking)
        selected = eligible_pairs[0][0].id if eligible_pairs else None

        # Eligible candidates are emitted in rank order, followed by excluded tasks by id.
        eligible_ids = {task.id for task, _ in eligible_pairs}
        ranked_candidates = [candidate for _, candidate in eligible_pairs]
        ranked_candidates.extend(c for c in candidates if c.task_id not in eligible_ids)

        return SchedulerDecision(
            evaluated_at=now,
            project_id=config.project.id,
            policy=config.scheduler.policy,
            policy_version=config.scheduler.policy_version,
            config_digest=digest(config),
            task_snapshot_digest=semantic_task_snapshot_digest(tasks),
            quota_snapshot_digest=digest(quota),
            selected_task_id=selected,
            quota_mode=quota_state.mode,
            candidates=ranked_candidates,
        )
