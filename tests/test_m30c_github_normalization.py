from pathlib import Path

from projectctl.core.enums import TaskStatus
from projectctl.integrations.github.task_store import GitHubIssuesTaskStore


class FakeClient:
    repository = "acme/widget"

    def __init__(self, issue):
        self.issue = issue

    def list_all(self):
        return [self.issue]

    def list_blocked_by(self, issue_number):
        return []

    def list_sub_issues(self, issue_number):
        return []

    def show(self, issue_number):
        return self.issue

    def version(self):
        return "gh version test"


def issue(*, state="open", state_reason=None, labels=None):
    return {
        "number": 7,
        "title": "Deliver feature",
        "state": state,
        "state_reason": state_reason,
        "created_at": "2026-10-04T06:00:00Z",
        "updated_at": "2026-10-04T08:00:00Z",
        "labels": [{"name": value} for value in (labels or [])],
        "milestone": None,
    }


def test_open_issue_with_projectctl_completed_label_is_done(tmp_path: Path):
    store = GitHubIssuesTaskStore(
        tmp_path,
        client=FakeClient(issue(labels=["projectctl:completed"])),
    )
    task = store.list_all()[0]
    assert task.status == TaskStatus.DONE


def test_native_not_planned_close_wins_over_completion_label(tmp_path: Path):
    store = GitHubIssuesTaskStore(
        tmp_path,
        client=FakeClient(
            issue(
                state="closed",
                state_reason="not_planned",
                labels=["projectctl:completed"],
            )
        ),
    )
    task = store.list_all()[0]
    assert task.status == TaskStatus.CANCELLED
