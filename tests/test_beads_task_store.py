from pathlib import Path

from projectctl.core.enums import TaskStatus, TaskType
from projectctl.integrations.beads.task_store import BeadsTaskStore


class FakeClient:
    def list_all(self):
        return [
            {"id": "bd-a", "title": "A", "status": "open", "priority": 1, "issue_type": "task", "created_at": "2026-09-30T08:00:00Z"},
            {"id": "bd-b", "title": "B", "status": "open", "priority": 2, "issue_type": "bug", "created_at": "2026-09-30T08:01:00Z"},
        ]

    def list_ready(self):
        return [{"id": "bd-a", "title": "A", "status": "open", "priority": 1, "issue_type": "task"}]

    def list_blocked(self):
        return [{"id": "bd-b", "title": "B", "status": "open", "priority": 2, "issue_type": "bug", "blocked_by": [{"id": "bd-a"}]}]

    def show(self, issue_id):
        return next(item for item in self.list_all() if item["id"] == issue_id)

    def version(self):
        return "bd version 1.2.2"


def test_beads_task_store_normalizes_ready_blocked_and_priority(tmp_path: Path):
    store = BeadsTaskStore(tmp_path, client=FakeClient())
    tasks = {task.id: task for task in store.list_all()}
    assert tasks["bd-a"].status == TaskStatus.READY
    assert tasks["bd-a"].type == TaskType.TASK
    assert tasks["bd-a"].priority == 8
    assert tasks["bd-b"].status == TaskStatus.BLOCKED
    assert tasks["bd-b"].type == TaskType.BUG
    assert tasks["bd-b"].dependencies == ["bd-a"]
    assert tasks["bd-a"].blocks == ["bd-b"]


def test_task_snapshot_source_revision_is_stable(tmp_path: Path):
    store = BeadsTaskStore(tmp_path, client=FakeClient())
    first = store.snapshot()
    second = store.snapshot()
    assert first.source_revision == second.source_revision
