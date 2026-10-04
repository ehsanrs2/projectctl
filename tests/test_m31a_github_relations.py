from datetime import datetime, timezone
from pathlib import Path

from projectctl.core.enums import ConfidenceLevel, QuotaSource, TaskStatus
from projectctl.integrations.github.task_store import GitHubIssuesTaskStore
from projectctl.schema_export import PUBLIC_SCHEMAS
from projectctl.scheduler.service import SchedulerService
from projectctl.schemas.config import ProjectConfig, ProjectIdentity
from projectctl.schemas.quota import QuotaSnapshot, QuotaWindow
from projectctl.schemas.task import TaskSnapshot, TaskSnapshotV1, TaskSnapshotV2


def issue(number: int, *, state: str = "open", state_reason=None, repo="acme/widget"):
    return {
        "number": number,
        "title": f"Issue {number}",
        "state": state,
        "state_reason": state_reason,
        "created_at": "2026-10-04T08:00:00Z",
        "updated_at": "2026-10-04T09:00:00Z",
        "repository_url": f"https://api.github.com/repos/{repo}",
        "html_url": f"https://github.com/{repo}/issues/{number}",
        "labels": [],
        "milestone": None,
    }


class RelationClient:
    repository = "acme/widget"

    def __init__(self, issues, *, blocked_by=None, sub_issues=None):
        self.issues = list(issues)
        self.blocked_by = blocked_by or {}
        self.sub_issues = sub_issues or {}

    def list_all(self):
        return list(self.issues)

    def list_blocked_by(self, issue_number):
        return list(self.blocked_by.get(int(issue_number), []))

    def list_sub_issues(self, issue_number):
        return list(self.sub_issues.get(int(issue_number), []))

    def show(self, issue_number):
        number = int(str(issue_number).replace("gh-", "").replace("#", ""))
        return next(item for item in self.issues if item["number"] == number)

    def version(self):
        return "gh version relation-test"


def test_native_dependency_blocks_until_local_dependency_is_done(tmp_path: Path):
    client = RelationClient(
        [
            issue(1),
            issue(2),
            issue(3, state="closed", state_reason="completed"),
            issue(4),
        ],
        blocked_by={
            2: [issue(1)],
            4: [issue(3, state="closed", state_reason="completed")],
        },
    )
    store = GitHubIssuesTaskStore(tmp_path, client=client)
    tasks = {task.id: task for task in store.list_all()}

    assert tasks["gh-2"].dependencies == ["gh-1"]
    assert tasks["gh-2"].status == TaskStatus.BLOCKED
    assert tasks["gh-1"].blocks == ["gh-2"]

    assert tasks["gh-4"].dependencies == ["gh-3"]
    assert tasks["gh-3"].status == TaskStatus.DONE
    assert tasks["gh-4"].status == TaskStatus.READY

    assert "gh-2" not in {task.id for task in store.list_ready()}
    assert "gh-4" in {task.id for task in store.list_ready()}


def test_open_external_dependency_blocks_without_inventing_local_task(tmp_path: Path):
    client = RelationClient(
        [issue(7)],
        blocked_by={7: [issue(42, repo="other/repo")]},
    )
    task = GitHubIssuesTaskStore(tmp_path, client=client).list_all()[0]

    assert task.dependencies == ["github:other/repo#42"]
    assert task.status == TaskStatus.BLOCKED
    assert any("external GitHub dependency" in note for note in task.normalization_notes)


def test_closed_external_dependency_is_satisfied_without_missing_edge(tmp_path: Path):
    client = RelationClient(
        [issue(7)],
        blocked_by={
            7: [
                issue(
                    42,
                    repo="other/repo",
                    state="closed",
                    state_reason="completed",
                )
            ]
        },
    )
    task = GitHubIssuesTaskStore(tmp_path, client=client).list_all()[0]

    assert task.dependencies == []
    assert task.status == TaskStatus.READY
    assert any("already closed/completed" in note for note in task.normalization_notes)


def test_cancelled_external_dependency_remains_blocking(tmp_path: Path):
    client = RelationClient(
        [issue(7)],
        blocked_by={
            7: [
                issue(
                    42,
                    repo="other/repo",
                    state="closed",
                    state_reason="not_planned",
                )
            ]
        },
    )
    task = GitHubIssuesTaskStore(tmp_path, client=client).list_all()[0]

    assert task.dependencies == ["github:other/repo#42"]
    assert task.status == TaskStatus.BLOCKED


def test_sub_issue_hierarchy_is_not_implicitly_a_dependency(tmp_path: Path):
    client = RelationClient(
        [issue(10), issue(11)],
        sub_issues={10: [issue(11)]},
    )
    tasks = {
        task.id: task
        for task in GitHubIssuesTaskStore(tmp_path, client=client).list_all()
    }

    assert tasks["gh-10"].hierarchy.sub_issues == ["gh-11"]
    assert tasks["gh-11"].hierarchy.parent == "gh-10"
    assert tasks["gh-10"].dependencies == []
    assert tasks["gh-11"].dependencies == []
    assert tasks["gh-10"].status == TaskStatus.READY
    assert tasks["gh-11"].status == TaskStatus.READY


def test_dependency_cycle_fails_closed_to_human_decision(tmp_path: Path):
    client = RelationClient(
        [issue(20), issue(21)],
        blocked_by={
            20: [issue(21)],
            21: [issue(20)],
        },
    )
    tasks = GitHubIssuesTaskStore(tmp_path, client=client).list_all()

    assert {task.status for task in tasks} == {TaskStatus.NEEDS_DECISION}
    assert all(task.human_decision_required for task in tasks)
    assert all(
        any("dependency graph contains a cycle" in note for note in task.normalization_notes)
        for task in tasks
    )


def test_sub_issue_cycle_fails_closed_without_becoming_dependency(tmp_path: Path):
    client = RelationClient(
        [issue(30), issue(31)],
        sub_issues={
            30: [issue(31)],
            31: [issue(30)],
        },
    )
    tasks = GitHubIssuesTaskStore(tmp_path, client=client).list_all()

    assert {task.status for task in tasks} == {TaskStatus.NEEDS_DECISION}
    assert all(task.dependencies == [] for task in tasks)
    assert all(
        any("sub-issue hierarchy contains a cycle" in note for note in task.normalization_notes)
        for task in tasks
    )


def test_missing_same_repo_dependency_fails_closed(tmp_path: Path):
    client = RelationClient(
        [issue(40)],
        blocked_by={40: [issue(99)]},
    )
    task = GitHubIssuesTaskStore(tmp_path, client=client).list_all()[0]

    assert task.dependencies == ["gh-99"]
    assert task.status == TaskStatus.NEEDS_DECISION
    assert task.human_decision_required is True
    assert any("absent from the current task snapshot" in note for note in task.normalization_notes)


def test_task_snapshot_contract_is_additively_versioned():
    assert PUBLIC_SCHEMAS["task-snapshot.v1.schema.json"] is TaskSnapshotV1
    assert PUBLIC_SCHEMAS["task-snapshot.v2.schema.json"] is TaskSnapshotV2
    assert PUBLIC_SCHEMAS["task-snapshot.v3.schema.json"] is TaskSnapshot
    assert TaskSnapshotV1.model_fields["schema_version"].default == 1
    assert TaskSnapshotV2.model_fields["schema_version"].default == 2
    assert TaskSnapshot.model_fields["schema_version"].default == 3


def scheduler_decision(store: GitHubIssuesTaskStore):
    now = datetime(2026, 10, 4, 12, 0, tzinfo=timezone.utc)
    quota = QuotaSnapshot(
        provider="test",
        account="acct",
        observed_at=now,
        five_hour=QuotaWindow(
            remaining_ratio=.90,
            source=QuotaSource.MANUAL,
            confidence=ConfidenceLevel.MEDIUM,
        ),
        weekly=QuotaWindow(
            remaining_ratio=.90,
            source=QuotaSource.MANUAL,
            confidence=ConfidenceLevel.MEDIUM,
        ),
    )
    return SchedulerService().decide(
        config=ProjectConfig(project=ProjectIdentity(id="demo")),
        tasks=store.snapshot(),
        quota=quota,
        now=now,
    )


def test_scheduler_consumes_native_github_dependencies(tmp_path: Path):
    blocked = GitHubIssuesTaskStore(
        tmp_path,
        client=RelationClient(
            [issue(1), issue(2), issue(3)],
            blocked_by={2: [issue(1)]},
        ),
    )
    assert scheduler_decision(blocked).selected_task_id == "gh-1"

    resolved = GitHubIssuesTaskStore(
        tmp_path,
        client=RelationClient(
            [
                issue(1, state="closed", state_reason="completed"),
                issue(2),
                issue(3),
            ],
            blocked_by={
                2: [issue(1, state="closed", state_reason="completed")]
            },
        ),
    )
    assert scheduler_decision(resolved).selected_task_id == "gh-2"


def test_scheduler_never_treats_sub_issue_hierarchy_as_dependency(tmp_path: Path):
    store = GitHubIssuesTaskStore(
        tmp_path,
        client=RelationClient(
            [issue(10), issue(11)],
            sub_issues={10: [issue(11)]},
        ),
    )
    decision = scheduler_decision(store)
    assert decision.selected_task_id in {"gh-10", "gh-11"}
    assert all(candidate.eligibility.eligible for candidate in decision.candidates)
