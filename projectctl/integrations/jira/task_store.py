from __future__ import annotations

from typing import Any

from projectctl.core.digest import digest
from projectctl.core.enums import ResourceClass, RiskLevel, TaskStatus, TaskType
from projectctl.core.time import utc_now
from projectctl.integrations.jira.client import JiraCloudClient
from projectctl.schemas.task import (
    NormalizedTask,
    TaskHierarchy,
    TaskSnapshot,
    TaskSource,
    TaskTeamMetadata,
)


_PRIORITY = {
    "highest": 10,
    "high": 8,
    "medium": 5,
    "low": 3,
    "lowest": 1,
}

_CANCEL_RESOLUTIONS = {
    "cancelled",
    "canceled",
    "declined",
    "duplicate",
    "rejected",
    "won't do",
    "wont do",
}

_TYPE_MAP = {
    "bug": TaskType.BUG,
    "task": TaskType.TASK,
    "sub-task": TaskType.TASK,
    "subtask": TaskType.TASK,
    "story": TaskType.FEATURE,
    "feature": TaskType.FEATURE,
    "epic": TaskType.FEATURE,
    "research": TaskType.RESEARCH,
    "spike": TaskType.RESEARCH,
    "documentation": TaskType.DOCS,
    "docs": TaskType.DOCS,
    "chore": TaskType.CHORE,
}


class JiraIssuesTaskStore:
    """Conservative read-only Jira Cloud task authority for M3.3a.

    Jira workflow status categories are observed, but M3.3a deliberately does
    not infer scheduler readiness from a provider-specific "new"/"to do"
    category. Workflow/eligibility mapping is deferred to M3.3b.
    """

    def __init__(
        self,
        project_root,
        *,
        site: str,
        project_key: str,
        client: JiraCloudClient | None = None,
    ):
        self.project_root = project_root.resolve()
        self.client = client or JiraCloudClient(
            self.project_root,
            site=site,
            project_key=project_key,
        )
        self.site = self.client.site
        self.project_key = self.client.project_key

    @staticmethod
    def _task_id(key: str) -> str:
        return f"jira-{key}"

    @staticmethod
    def _status(fields: dict[str, Any]) -> tuple[TaskStatus, bool, list[str]]:
        notes: list[str] = []
        status = fields.get("status")
        if not isinstance(status, dict):
            return (
                TaskStatus.NEEDS_DECISION,
                True,
                ["Jira issue is missing status metadata."],
            )
        category = status.get("statusCategory")
        if not isinstance(category, dict):
            return (
                TaskStatus.NEEDS_DECISION,
                True,
                ["Jira status is missing statusCategory metadata."],
            )

        category_key = str(category.get("key") or "").strip().casefold()
        status_name = str(status.get("name") or "").strip() or "unknown"

        if category_key in {"done", "completed"}:
            resolution = fields.get("resolution")
            resolution_name = (
                str(resolution.get("name") or "").strip().casefold()
                if isinstance(resolution, dict)
                else ""
            )
            if resolution_name in _CANCEL_RESOLUTIONS:
                return TaskStatus.CANCELLED, False, notes
            return TaskStatus.DONE, False, notes

        if category_key in {"indeterminate", "in-flight", "in_progress"}:
            notes.append(
                f"Jira status {status_name!r} is in progress; ProjectCTL observes "
                "it as running but does not own the workflow transition."
            )
            return TaskStatus.RUNNING, False, notes

        if category_key in {"new", "to-do", "todo"}:
            notes.append(
                f"Jira status {status_name!r} is in a planning/to-do category. "
                "M3.3a does not infer scheduler readiness from Jira workflow "
                "categories; explicit workflow eligibility mapping is deferred."
            )
            return TaskStatus.PLANNED, False, notes

        notes.append(
            f"Unknown Jira status category {category_key or 'missing'!r}; "
            "human normalization is required."
        )
        return TaskStatus.NEEDS_DECISION, True, notes

    @staticmethod
    def _issue_type(fields: dict[str, Any], notes: list[str]) -> tuple[TaskType, str | None]:
        issue_type = fields.get("issuetype")
        if not isinstance(issue_type, dict):
            notes.append("Jira issue is missing issue type metadata.")
            return TaskType.UNKNOWN, None
        name = str(issue_type.get("name") or "").strip()
        if not name:
            notes.append("Jira issue type has no name.")
            return TaskType.UNKNOWN, None
        normalized = _TYPE_MAP.get(name.casefold(), TaskType.UNKNOWN)
        if normalized == TaskType.UNKNOWN:
            notes.append(
                f"Jira issue type {name!r} has no ProjectCTL type mapping."
            )
        return normalized, name

    @staticmethod
    def _priority(fields: dict[str, Any], notes: list[str]) -> int:
        priority = fields.get("priority")
        if priority is None:
            return 5
        if not isinstance(priority, dict):
            notes.append("Jira priority metadata is not an object; using medium.")
            return 5
        name = str(priority.get("name") or "").strip()
        mapped = _PRIORITY.get(name.casefold())
        if mapped is None:
            notes.append(
                f"Unknown Jira priority {name or 'missing'!r}; using medium."
            )
            return 5
        return mapped

    def _normalize(self, raw: dict[str, Any]) -> NormalizedTask:
        external_id = str(raw.get("id") or "").strip()
        key = str(raw.get("key") or "").strip().upper()
        fields = raw.get("fields")
        if not external_id or not key or not isinstance(fields, dict):
            raise ValueError("Jira issue payload is missing id/key/fields.")

        title = str(fields.get("summary") or "").strip() or key
        status, human_decision, notes = self._status(fields)
        task_type, issue_type = self._issue_type(fields, notes)
        priority = self._priority(fields, notes)

        assignees: list[str] = []
        assignee = fields.get("assignee")
        if assignee is not None:
            if not isinstance(assignee, dict):
                notes.append("Jira assignee metadata is not an object.")
            else:
                display_name = str(assignee.get("displayName") or "").strip()
                if display_name:
                    assignees.append(display_name)
                else:
                    notes.append("Jira assignee metadata has no displayName.")

        status_obj = fields.get("status")
        status_name = (
            str(status_obj.get("name") or "").strip()
            if isinstance(status_obj, dict)
            else ""
        )

        labels_raw = fields.get("labels")
        labels: list[str] = []
        if labels_raw is None:
            pass
        elif isinstance(labels_raw, list):
            labels = sorted(
                {
                    str(label).strip()
                    for label in labels_raw
                    if str(label).strip()
                },
                key=str.casefold,
            )
        else:
            notes.append("Jira labels metadata is not a list.")

        due = fields.get("duedate")
        if due:
            notes.append(
                "Jira due date is date-only; M3.3a preserves it as a tag rather "
                "than inventing a timezone-aware due_at value."
            )

        tags = []
        if status_name:
            tags.append(f"jira-status:{status_name}")
        tags.extend(f"jira-label:{label}" for label in labels)
        if due:
            tags.append(f"jira-due-date:{str(due).strip()}")

        return NormalizedTask(
            id=self._task_id(key),
            title=title,
            source=TaskSource(
                provider="jira",
                external_id=external_id,
                revision=(
                    str(fields.get("updated")).strip()
                    if fields.get("updated") is not None
                    else None
                ),
                external_url=f"https://{self.site}/browse/{key}",
                observed_at=utc_now(),
            ),
            type=task_type,
            status=status,
            priority=priority,
            milestone=None,
            created_at=fields.get("created"),
            ready_since=None,
            due_at=None,
            dependencies=[],
            blocks=[],
            hierarchy=TaskHierarchy(),
            team=TaskTeamMetadata(
                assignees=assignees,
                issue_type=issue_type,
                milestone=None,
            ),
            risk=RiskLevel.UNKNOWN,
            resource_class=ResourceClass.UNKNOWN,
            information_gain=0,
            human_decision_required=human_decision,
            tags=tags,
            normalization_notes=notes,
        )

    def _build_tasks(self) -> list[NormalizedTask]:
        raw_all = self.client.list_all()
        tasks: list[NormalizedTask] = []
        by_key: dict[str, NormalizedTask] = {}
        raw_by_key: dict[str, dict[str, Any]] = {}

        for raw in raw_all:
            key = str(raw.get("key") or "").strip().upper()
            if not key:
                raise ValueError("Jira issue list contains an issue without a key.")
            if key in by_key:
                raise ValueError(f"Jira issue key appears more than once: {key}.")
            task = self._normalize(raw)
            tasks.append(task)
            by_key[key] = task
            raw_by_key[key] = raw

        # Parent/sub-task hierarchy is observational and does not imply a
        # dependency. Cross-project parents are retained as external identities.
        for key, raw in raw_by_key.items():
            fields = raw.get("fields")
            assert isinstance(fields, dict)
            parent = fields.get("parent")
            if parent is None:
                continue
            if not isinstance(parent, dict):
                task = by_key[key]
                task.human_decision_required = True
                task.status = (
                    task.status
                    if task.status in {TaskStatus.DONE, TaskStatus.CANCELLED}
                    else TaskStatus.NEEDS_DECISION
                )
                task.normalization_notes.append(
                    "Jira parent metadata is not an object."
                )
                continue

            parent_key = str(parent.get("key") or "").strip().upper()
            if not parent_key:
                task = by_key[key]
                task.human_decision_required = True
                if task.status not in {TaskStatus.DONE, TaskStatus.CANCELLED}:
                    task.status = TaskStatus.NEEDS_DECISION
                task.normalization_notes.append(
                    "Jira parent metadata is missing a key."
                )
                continue

            task = by_key[key]
            if parent_key in by_key:
                task.hierarchy.parent = by_key[parent_key].id
                by_key[parent_key].hierarchy.sub_issues.append(task.id)
            else:
                task.hierarchy.parent = f"jira:{parent_key}"
                task.normalization_notes.append(
                    "Jira parent is outside the configured project snapshot; "
                    "hierarchy remains observational."
                )

        for task in tasks:
            task.hierarchy.sub_issues = sorted(set(task.hierarchy.sub_issues))

        return sorted(tasks, key=lambda task: task.id)

    def get(self, task_id: str) -> NormalizedTask:
        key = str(task_id).strip()
        if key.startswith("jira-"):
            key = key[len("jira-") :]
        raw = self.client.show(key)
        return self._normalize(raw)

    def list_all(self) -> list[NormalizedTask]:
        return self._build_tasks()

    def list_ready(self) -> list[NormalizedTask]:
        return [
            task for task in self._build_tasks()
            if task.status == TaskStatus.READY and not task.human_decision_required
        ]

    def list_blocked(self) -> list[NormalizedTask]:
        return [
            task for task in self._build_tasks()
            if task.status in {TaskStatus.BLOCKED, TaskStatus.NEEDS_DECISION}
        ]

    def snapshot(
        self,
        *,
        tasks: list[NormalizedTask] | None = None,
    ) -> TaskSnapshot:
        normalized = self._build_tasks() if tasks is None else list(tasks)
        return TaskSnapshot(
            provider="jira",
            captured_at=utc_now(),
            source_revision=digest(
                {
                    "site": self.site,
                    "project": self.project_key,
                    "contract": self.client.version(),
                    "tasks": [task.model_dump(mode="json") for task in normalized],
                }
            ),
            tasks=normalized,
        )
