from pathlib import Path

from projectctl.core.enums import ResourceClass, RiskLevel, TaskStatus, TaskType
from projectctl.integrations.github.task_store import GitHubIssuesTaskStore


class FakeClient:
    repository = "acme/widget"

    def list_all(self):
        return [
            {
                "number": 7,
                "title": "Fix login race",
                "state": "open",
                "state_reason": None,
                "created_at": "2026-10-01T10:00:00Z",
                "updated_at": "2026-10-02T11:00:00Z",
                "html_url": "https://github.com/acme/widget/issues/7",
                "labels": [
                    {"name": "bug"},
                    {"name": "priority:p1"},
                    {"name": "resource:small"},
                    {"name": "risk:high"},
                    {"name": "info-gain:3"},
                ],
                "milestone": {"title": "M3.0a"},
            },
            {
                "number": 8,
                "title": "Needs product decision",
                "state": "open",
                "created_at": "2026-10-01T10:00:00Z",
                "updated_at": "2026-10-02T11:00:00Z",
                "labels": [{"name": "projectctl:needs-decision"}],
                "milestone": None,
            },
            {
                "number": 9,
                "title": "Cancelled work",
                "state": "closed",
                "state_reason": "not_planned",
                "created_at": "2026-10-01T10:00:00Z",
                "updated_at": "2026-10-02T11:00:00Z",
                "labels": [],
                "milestone": None,
            },
        ]

    def show(self, issue_number):
        number = int(str(issue_number).replace("gh-", "").replace("#", ""))
        return next(item for item in self.list_all() if item["number"] == number)

    def version(self):
        return "gh version 2.99.0"


def test_github_issues_normalize_native_and_projectctl_metadata(tmp_path: Path):
    store = GitHubIssuesTaskStore(tmp_path, client=FakeClient())
    tasks = {task.id: task for task in store.list_all()}

    task = tasks["gh-7"]
    assert task.source.provider == "github"
    assert task.source.external_id == "7"
    assert task.source.external_url.endswith("/issues/7")
    assert task.status == TaskStatus.READY
    assert task.type == TaskType.BUG
    assert task.priority == 8
    assert task.resource_class == ResourceClass.SMALL
    assert task.risk == RiskLevel.HIGH
    assert task.information_gain == 3
    assert task.milestone == "M3.0a"

    decision = tasks["gh-8"]
    assert decision.status == TaskStatus.NEEDS_DECISION
    assert decision.human_decision_required is True

    cancelled = tasks["gh-9"]
    assert cancelled.status == TaskStatus.CANCELLED


def test_github_ready_and_blocked_views_are_derived_from_normalized_state(tmp_path: Path):
    store = GitHubIssuesTaskStore(tmp_path, client=FakeClient())
    assert [task.id for task in store.list_ready()] == ["gh-7"]
    assert [task.id for task in store.list_blocked()] == ["gh-8"]


def test_github_conflicting_metadata_fails_closed(tmp_path: Path):
    class ConflictingClient(FakeClient):
        def list_all(self):
            return [
                {
                    "number": 10,
                    "title": "Ambiguous",
                    "state": "open",
                    "created_at": "2026-10-01T10:00:00Z",
                    "updated_at": "2026-10-02T11:00:00Z",
                    "labels": [
                        {"name": "type:bug"},
                        {"name": "type:feature"},
                        {"name": "resource:small"},
                        {"name": "resource:large"},
                    ],
                    "milestone": None,
                }
            ]

    task = GitHubIssuesTaskStore(tmp_path, client=ConflictingClient()).list_all()[0]
    assert task.status == TaskStatus.NEEDS_DECISION
    assert task.human_decision_required is True
    assert task.type == TaskType.UNKNOWN
    assert task.resource_class == ResourceClass.UNKNOWN
    assert any("Conflicting type labels" in note for note in task.normalization_notes)
    assert any("human normalization" in note for note in task.normalization_notes)


def test_github_snapshot_revision_ignores_observation_time(tmp_path: Path):
    store = GitHubIssuesTaskStore(tmp_path, client=FakeClient())
    first = store.snapshot()
    second = store.snapshot()
    assert first.provider == "github"
    assert first.source_revision == second.source_revision
    assert "repo=acme/widget" in first.source_revision
