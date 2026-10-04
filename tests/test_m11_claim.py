from datetime import datetime, timezone
from pathlib import Path

from projectctl.core.digest import digest
from projectctl.core.errors import TaskStoreError
from projectctl.integrations.beads.claim import BeadsTaskClaimer
from projectctl.schemas.task_claim import TaskClaimRequest


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


NOW = datetime(2026, 10, 4, 6, 0, tzinfo=timezone.utc)


def request() -> TaskClaimRequest:
    return TaskClaimRequest(
        task_id="bd-1",
        run_id="run-1",
        actor="projectctl",
        base_commit="a" * 40,
        integration_target_ref="main",
        claim_token="a" * 32,
        requested_at=NOW,
    )


def test_beads_claim_success_uses_observed_assignee(tmp_path: Path):
    claimer = BeadsTaskClaimer(tmp_path, client=FakeClient("success"))
    req = request()
    result = claimer.claim(req)
    assert result.acquired is True
    assert result.actor == "beads-user"
    assert result.request_digest == digest(req)


def test_beads_claim_conflict_is_nonexceptional_result(tmp_path: Path):
    claimer = BeadsTaskClaimer(tmp_path, client=FakeClient("conflict"))
    result = claimer.claim(request())
    assert result.acquired is False
    assert "not claimable" in result.reason


def test_beads_release_delegates_to_supported_release_sequence(tmp_path: Path):
    client = FakeClient()
    claimer = BeadsTaskClaimer(tmp_path, client=client)
    claim = claimer.claim(request())
    claimer.release(claim)
    assert client.released == ["bd-1"]


def test_beads_legacy_release_remains_available_for_pre_m30b2_runs(tmp_path: Path):
    client = FakeClient()
    claimer = BeadsTaskClaimer(tmp_path, client=client)
    claimer.release_legacy("bd-1", actor="projectctl")
    assert client.released == ["bd-1"]
