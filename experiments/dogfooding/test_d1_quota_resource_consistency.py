"""Regression: D1 generic Beads tasks must share the scheduler's effective quota resource class."""
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from projectctl.application import execution
from projectctl.core.enums import (
    ConfidenceLevel, QuotaSource, ResourceClass, RunTerminalReason,
    TaskStatus, TaskType,
)
from projectctl.quota.manager import QuotaManager
from projectctl.scheduler.resource import effective_resource_class
from projectctl.schemas.config import ProjectConfig, ProjectIdentity
from projectctl.schemas.quota import QuotaSnapshot, QuotaWindow
from projectctl.schemas.task import NormalizedTask, TaskSource

NOW = datetime(2026, 10, 19, 10, 17, tzinfo=timezone.utc)
ROOT = Path("/d1-test-no-real-repository")


def fixture_task():
    return NormalizedTask(
        id="d1ctl-lh4",
        title="Implement normalize_user_id",
        source=TaskSource(provider="beads", external_id="d1ctl-lh4"),
        status=TaskStatus.READY,
        type=TaskType.TASK,
        resource_class=ResourceClass.UNKNOWN,
    )


def quota(five=0.98, weekly=0.61):
    return QuotaSnapshot(
        provider="codex_app_server", account="openai-default",
        observed_at=NOW,
        five_hour=QuotaWindow(
            remaining_ratio=five,
            source=QuotaSource.OFFICIAL,
            confidence=ConfidenceLevel.HIGH,
        ),
        weekly=QuotaWindow(
            remaining_ratio=weekly,
            source=QuotaSource.OFFICIAL,
            confidence=ConfidenceLevel.HIGH,
        ),
        ordinary_usage_allowed=True,
    )


class D1QuotaResourceConsistency(unittest.TestCase):
    def setUp(self):
        self.task = fixture_task()
        self.cfg = ProjectConfig(project=ProjectIdentity(id="ctl"))
        self.assertEqual(self.task.resource_class, ResourceClass.UNKNOWN)
        self.assertEqual(effective_resource_class(self.task), ResourceClass.MEDIUM)

    def test_preclaim_accepts_same_task_as_scheduler(self):
        with (patch.object(execution, "task_store_for_project",
                           return_value=SimpleNamespace(get=lambda task_id: self.task)),
              patch.object(execution, "load_project_config", return_value=self.cfg),
              patch.object(execution, "read_current_quota", return_value=quota()),
              patch.object(execution, "utc_now", return_value=NOW)):
            self.assertIsNone(execution._prepare_quota_reason(ROOT, self.task.id))

    def test_preclaim_still_denies_insufficient_real_quota(self):
        with (patch.object(execution, "task_store_for_project",
                           return_value=SimpleNamespace(get=lambda task_id: self.task)),
              patch.object(execution, "load_project_config", return_value=self.cfg),
              patch.object(execution, "read_current_quota", return_value=quota(five=0.17)),
              patch.object(execution, "utc_now", return_value=NOW)):
            self.assertEqual(
                execution._prepare_quota_reason(ROOT, self.task.id),
                RunTerminalReason.QUOTA_EXHAUSTED,
            )

    def test_worker_start_quota_revalidation_accepts_effective_medium(self):
        with (patch.object(execution, "load_project_config", return_value=self.cfg),
              patch.object(execution, "read_current_quota", return_value=quota()),
              patch.object(execution, "utc_now", return_value=NOW)):
            _cfg, snapshot, state, eligible = execution._evaluate_current_worker_quota(
                ROOT, self.task
            )
        self.assertTrue(eligible)
        self.assertFalse(state.stale)
        self.assertEqual(snapshot.five_hour.remaining_ratio, 0.98)

    def test_checkpoint_monitor_uses_same_medium_requirement(self):
        with patch.object(execution, "load_project_config", return_value=self.cfg):
            monitor = execution._quota_monitor(ROOT, self.task)
        self.assertEqual(monitor.resource_class, ResourceClass.MEDIUM)
        monitor._reader = lambda _: quota()
        monitor._clock = lambda: NOW
        self.assertIsNone(monitor.evaluate_once())
        monitor._reader = lambda _: quota(five=0.17)
        self.assertIsNotNone(monitor.evaluate_once())

    def test_legacy_plan_quota_revalidation_uses_effective_medium(self):
        plan = SimpleNamespace(
            integration_target_ref="main",
            base_commit="basecommit",
            task_snapshot_digest="tasks",
            project_state_digest="state",
            task_id=self.task.id,
        )
        tasks = SimpleNamespace(tasks=[self.task])
        with (patch.object(execution, "resolve_commit", return_value="basecommit"),
              patch.object(execution, "capture_task_snapshot", return_value=tasks),
              patch.object(execution, "semantic_task_snapshot_digest", return_value="tasks"),
              patch.object(execution, "load_project_state", return_value=object()),
              patch.object(execution, "semantic_project_state_digest", return_value="state"),
              patch.object(execution, "load_project_config", return_value=self.cfg),
              patch.object(execution, "read_current_quota", return_value=quota()),
              patch.object(execution, "utc_now", return_value=NOW)):
            self.assertIsNone(execution._validate_plan_inputs(ROOT, plan))

    def test_unresolved_unknown_is_still_denied_by_low_level_quota_api(self):
        state = QuotaManager(self.cfg.quota).state(quota(), now=NOW)
        self.assertFalse(
            QuotaManager(self.cfg.quota).eligible_for_resource(ResourceClass.UNKNOWN, state)
        )


if __name__ == "__main__":
    unittest.main()
