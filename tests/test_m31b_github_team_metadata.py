from datetime import datetime, timezone
from pathlib import Path

from projectctl.core.enums import TaskStatus, TaskType
from projectctl.integrations.github.task_store import GitHubIssuesTaskStore
from projectctl.scheduler.digests import semantic_task_snapshot_digest


def raw_issue(assignees=None, issue_type=None, milestone=None, labels=None):
    return {
        "number": 7,
        "title": "Team metadata",
        "state": "open",
        "state_reason": None,
        "created_at": "2026-10-04T08:00:00Z",
        "updated_at": "2026-10-04T09:00:00Z",
        "repository_url": "https://api.github.com/repos/acme/widget",
        "html_url": "https://github.com/acme/widget/issues/7",
        "assignees": assignees or [],
        "type": issue_type,
        "labels": [{"name": value} for value in (labels or [])],
        "milestone": milestone,
    }


class Client:
    repository = "acme/widget"

    def __init__(self, raw):
        self.raw = raw

    def list_all(self):
        return [self.raw]

    def list_blocked_by(self, issue_number):
        return []

    def list_sub_issues(self, issue_number):
        return []

    def show(self, issue_number):
        return self.raw

    def version(self):
        return "gh version metadata-test"


def native_milestone(due_on="2026-10-20T12:00:00Z"):
    return {
        "number": 3,
        "title": "M3.1",
        "state": "open",
        "due_on": due_on,
        "html_url": "https://github.com/acme/widget/milestone/3",
        "open_issues": 4,
        "closed_issues": 8,
    }


def test_team_metadata_normalizes_assignees_type_and_milestone(tmp_path: Path):
    task = GitHubIssuesTaskStore(
        tmp_path,
        client=Client(
            raw_issue(
                assignees=[{"login": "zoe"}, {"login": "alice"}, {"login": "alice"}],
                issue_type={"name": "Feature"},
                milestone=native_milestone(),
            )
        ),
    ).list_all()[0]

    assert task.team.assignees == ["alice", "zoe"]
    assert task.team.issue_type == "Feature"
    assert task.type == TaskType.FEATURE
    assert task.milestone == "M3.1"
    assert task.due_at == datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)
    assert task.team.milestone.number == 3
    assert task.team.milestone.open_issues == 4
    assert task.team.milestone.closed_issues == 8


def test_native_type_conflict_fails_closed(tmp_path: Path):
    task = GitHubIssuesTaskStore(
        tmp_path,
        client=Client(raw_issue(issue_type="Feature", labels=["type:bug"])),
    ).list_all()[0]
    assert task.status == TaskStatus.NEEDS_DECISION
    assert task.human_decision_required is True
    assert task.type == TaskType.BUG
    assert any("native issue type conflicts" in note for note in task.normalization_notes)


def test_matching_native_and_explicit_type_is_safe(tmp_path: Path):
    task = GitHubIssuesTaskStore(
        tmp_path,
        client=Client(raw_issue(issue_type={"name": "Bug"}, labels=["type:bug"])),
    ).list_all()[0]
    assert task.status == TaskStatus.READY
    assert task.type == TaskType.BUG


def test_team_only_change_is_not_semantic(tmp_path: Path):
    a = GitHubIssuesTaskStore(
        tmp_path, client=Client(raw_issue(assignees=[{"login": "alice"}]))
    ).snapshot()
    b = GitHubIssuesTaskStore(
        tmp_path, client=Client(raw_issue(assignees=[{"login": "bob"}]))
    ).snapshot()
    assert a.source_revision == b.source_revision
    assert semantic_task_snapshot_digest(a) == semantic_task_snapshot_digest(b)


def test_milestone_due_date_is_semantic(tmp_path: Path):
    a = GitHubIssuesTaskStore(
        tmp_path,
        client=Client(raw_issue(milestone=native_milestone("2026-10-20T12:00:00Z"))),
    ).snapshot()
    b = GitHubIssuesTaskStore(
        tmp_path,
        client=Client(raw_issue(milestone=native_milestone("2026-10-21T12:00:00Z"))),
    ).snapshot()
    assert a.source_revision != b.source_revision
    assert semantic_task_snapshot_digest(a) != semantic_task_snapshot_digest(b)


def test_milestone_conflict_disables_scheduling_milestone_and_due_date(tmp_path: Path):
    task = GitHubIssuesTaskStore(
        tmp_path,
        client=Client(
            raw_issue(
                milestone=native_milestone(),
                labels=["milestone:Other"],
            )
        ),
    ).list_all()[0]
    assert task.status == TaskStatus.NEEDS_DECISION
    assert task.milestone is None
    assert task.due_at is None
    assert task.team.milestone is not None
    assert task.team.milestone.title == "M3.1"


def test_malformed_assignee_metadata_is_observational_only(tmp_path: Path):
    task = GitHubIssuesTaskStore(
        tmp_path,
        client=Client(
            raw_issue(
                assignees=[{"login": "alice"}, {}, 42],
            )
        ),
    ).list_all()[0]
    assert task.status == TaskStatus.READY
    assert task.human_decision_required is False
    assert task.team.assignees == ["alice"]
    assert any("assignee metadata" in note for note in task.normalization_notes)
