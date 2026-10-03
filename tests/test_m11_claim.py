from pathlib import Path

from projectctl.core.errors import TaskStoreError
from projectctl.integrations.beads.claim import BeadsTaskClaimer


class FakeClient:
    def __init__(self, mode="success"):
        self.mode = mode
        self.released = []

    def claim_issue(self, task_id):
        if self.mode == "success":
            return {"id": task_id, "status": "in_progress", "assignee": "beads-user"}
        raise TaskStoreError("claim lost")

    def show(self, task_id):
        if self.mode == "conflict":
            return {"id": task_id, "status": "in_progress", "assignee": "other"}
        return {"id": task_id, "status": "open", "assignee": ""}

    def release_issue(self, task_id):
        self.released.append(task_id)


def test_beads_claim_success_uses_observed_assignee(tmp_path: Path):
    claimer = BeadsTaskClaimer(tmp_path, client=FakeClient("success"))
    result = claimer.claim("bd-1", actor="projectctl")
    assert result.claimed is True
    assert result.actor == "beads-user"


def test_beads_claim_conflict_is_nonexceptional_result(tmp_path: Path):
    claimer = BeadsTaskClaimer(tmp_path, client=FakeClient("conflict"))
    result = claimer.claim("bd-1", actor="projectctl")
    assert result.claimed is False
    assert "not claimable" in result.reason


def test_beads_release_delegates_to_supported_release_sequence(tmp_path: Path):
    client = FakeClient()
    claimer = BeadsTaskClaimer(tmp_path, client=client)
    claimer.release("bd-1", actor="projectctl")
    assert client.released == ["bd-1"]
