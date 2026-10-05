from __future__ import annotations

from typing import Any

from projectctl.core.digest import digest
from projectctl.core.enums import ResourceClass, RiskLevel, TaskStatus, TaskType
from projectctl.core.errors import ProviderUnavailableError, TaskStoreError
from projectctl.core.time import utc_now
from projectctl.integrations.jira.client import (
    JIRA_LIFECYCLE_PROPERTY,
    JiraCloudClient,
)
from projectctl.schemas.config import JiraLinkRule, JiraWorkflowPolicy
from projectctl.schemas.jira_lifecycle import JiraLifecycleMarker
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

_TERMINAL = {TaskStatus.DONE, TaskStatus.CANCELLED}
_TODO_CATEGORIES = {"new", "to-do", "todo"}
_PROGRESS_CATEGORIES = {"indeterminate", "in-flight", "in_progress"}
_DONE_CATEGORIES = {"done", "completed"}


def _cycle_nodes(tasks: dict[str, NormalizedTask], *, hierarchy: bool) -> set[str]:
    graph: dict[str, list[str]] = {}
    for task_id, task in tasks.items():
        edges = task.hierarchy.sub_issues if hierarchy else task.dependencies
        graph[task_id] = [edge for edge in edges if edge in tasks]

    color: dict[str, int] = {}
    stack: list[str] = []
    stack_index: dict[str, int] = {}
    cyclic: set[str] = set()

    def visit(node: str) -> None:
        color[node] = 1
        stack_index[node] = len(stack)
        stack.append(node)
        for target in graph.get(node, []):
            state = color.get(target, 0)
            if state == 0:
                visit(target)
            elif state == 1:
                cyclic.update(stack[stack_index[target] :])
        stack.pop()
        stack_index.pop(node, None)
        color[node] = 2

    for node in sorted(graph):
        if color.get(node, 0) == 0:
            visit(node)
    return cyclic


class JiraIssuesTaskStore:
    """Jira Cloud authority with explicit M3.3b scheduler semantics.

    Workflow readiness is configured by stable Jira status id. Issue-link
    semantics are configured by stable link-type id plus pinned provider labels;
    ProjectCTL never guesses dependency direction from customizable Jira text.
    """

    def __init__(
        self,
        project_root,
        *,
        site: str,
        project_key: str,
        policy: JiraWorkflowPolicy | None = None,
        client: JiraCloudClient | None = None,
        lifecycle_enabled: bool = True,
    ):
        self.project_root = project_root.resolve()
        self.client = client or JiraCloudClient(
            self.project_root,
            site=site,
            project_key=project_key,
        )
        self.site = self.client.site
        self.project_key = self.client.project_key
        self.policy = policy or JiraWorkflowPolicy()
        self.lifecycle_enabled = lifecycle_enabled
        self._ready_by_id = {
            item.id: item
            for item in self.policy.ready_statuses
        }
        self._link_rule_by_id = {
            item.type_id: item
            for item in self.policy.link_rules
        }

    @staticmethod
    def _task_id(key: str) -> str:
        return f"jira-{key}"

    @staticmethod
    def _mark_needs_decision(task: NormalizedTask, note: str) -> None:
        if note not in task.normalization_notes:
            task.normalization_notes.append(note)
        task.human_decision_required = True
        if task.status not in _TERMINAL:
            task.status = TaskStatus.NEEDS_DECISION

    def _status(self, fields: dict[str, Any]) -> tuple[TaskStatus, bool, list[str]]:
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

        status_id = str(status.get("id") or "").strip()
        status_name = str(status.get("name") or "").strip() or "unknown"
        category_key = str(category.get("key") or "").strip().casefold()
        if not status_id:
            return (
                TaskStatus.NEEDS_DECISION,
                True,
                ["Jira status is missing its stable id."],
            )

        if category_key in _DONE_CATEGORIES:
            resolution = fields.get("resolution")
            resolution_name = (
                str(resolution.get("name") or "").strip().casefold()
                if isinstance(resolution, dict)
                else ""
            )
            if resolution_name in _CANCEL_RESOLUTIONS:
                return TaskStatus.CANCELLED, False, notes
            return TaskStatus.DONE, False, notes

        if category_key in _PROGRESS_CATEGORIES:
            if status_id in self._ready_by_id:
                notes.append(
                    f"Configured Jira READY status id {status_id!r} is now "
                    f"in progress ({status_name!r}); policy/provider metadata drifted."
                )
                return TaskStatus.NEEDS_DECISION, True, notes
            notes.append(
                f"Jira status {status_name!r} is in progress; ProjectCTL observes "
                "it as running but does not own the workflow transition."
            )
            return TaskStatus.RUNNING, False, notes

        if category_key in _TODO_CATEGORIES:
            ready = self._ready_by_id.get(status_id)
            if ready is None:
                notes.append(
                    f"Jira status {status_name!r} is not explicitly configured as "
                    "scheduler-ready; ProjectCTL does not infer scheduler readiness "
                    "from Jira workflow categories."
                )
                return TaskStatus.PLANNED, False, notes
            if ready.name != status_name:
                notes.append(
                    f"Jira READY status id {status_id!r} changed name from "
                    f"{ready.name!r} to {status_name!r}; explicit policy review is required."
                )
                return TaskStatus.NEEDS_DECISION, True, notes
            return TaskStatus.READY, False, notes

        notes.append(
            f"Unknown Jira status category {category_key or 'missing'!r}; "
            "human normalization is required."
        )
        return TaskStatus.NEEDS_DECISION, True, notes

    @staticmethod
    def _issue_type(
        fields: dict[str, Any],
        notes: list[str],
    ) -> tuple[TaskType, str | None]:
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
                "Jira due date is date-only; ProjectCTL preserves it as a tag "
                "rather than inventing a timezone-aware due_at value."
            )

        tags: list[str] = []
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
                assignees=sorted(set(assignees), key=str.casefold),
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

    @staticmethod
    def _property_value(raw: dict[str, Any], key: str) -> Any | None:
        properties = raw.get("properties")
        if properties is None:
            return None
        if isinstance(properties, dict):
            return properties.get(key)
        if isinstance(properties, list):
            matches = [
                item.get("value")
                for item in properties
                if isinstance(item, dict) and item.get("key") == key
            ]
            if len(matches) > 1:
                raise TaskStoreError(
                    f"Jira issue contains duplicate property values for {key!r}."
                )
            return matches[0] if matches else None
        raise TaskStoreError("Jira issue properties metadata is malformed.")

    def _apply_lifecycle(
        self,
        task: NormalizedTask,
        raw: dict[str, Any],
    ) -> None:
        if not self.lifecycle_enabled:
            return
        try:
            value = self._property_value(raw, JIRA_LIFECYCLE_PROPERTY)
        except TaskStoreError as exc:
            self._mark_needs_decision(task, str(exc))
            return
        if value is None:
            return
        try:
            marker = JiraLifecycleMarker.model_validate(value)
        except Exception:
            self._mark_needs_decision(
                task,
                "Jira ProjectCTL lifecycle property is malformed; human review is required.",
            )
            return

        issue_id = str(raw.get("id") or "").strip()
        if marker.task_id != task.id or marker.issue_id != issue_id:
            self._mark_needs_decision(
                task,
                "Jira ProjectCTL lifecycle marker identity does not match this issue.",
            )
            return

        # Native Jira terminal state remains authoritative.
        if task.status in _TERMINAL:
            return

        if marker.state in {"needs_decision", "completion_pending"}:
            self._mark_needs_decision(
                task,
                "Jira ProjectCTL lifecycle requires human decision."
                if marker.state == "needs_decision"
                else "Jira ProjectCTL completion is pending/recoverable.",
            )
            return

        assert marker.state == "completed"
        if task.human_decision_required or task.dependencies:
            self._mark_needs_decision(
                task,
                "Jira ProjectCTL completion marker conflicts with current "
                "dependency/provider safety state.",
            )
            return

        task.status = TaskStatus.DONE
        task.human_decision_required = False
        task.normalization_notes.append(
            "Jira task is completed by the verified ProjectCTL lifecycle property."
        )

    @staticmethod
    def _link_side(link: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
        inward = link.get("inwardIssue")
        outward = link.get("outwardIssue")
        has_inward = isinstance(inward, dict)
        has_outward = isinstance(outward, dict)
        if has_inward == has_outward:
            return None
        return ("inward", inward) if has_inward else ("outward", outward)

    @staticmethod
    def _rule_matches_provider(
        rule: JiraLinkRule,
        link_type: dict[str, Any],
    ) -> bool:
        return (
            str(link_type.get("id") or "").strip() == rule.type_id
            and str(link_type.get("name") or "").strip() == rule.name
            and str(link_type.get("inward") or "").strip() == rule.inward_label
            and str(link_type.get("outward") or "").strip() == rule.outward_label
        )

    @staticmethod
    def _linked_terminal(linked: dict[str, Any]) -> bool | None:
        fields = linked.get("fields")
        if not isinstance(fields, dict):
            return None
        status = fields.get("status")
        if not isinstance(status, dict):
            return None
        category = status.get("statusCategory")
        if not isinstance(category, dict):
            return None
        category_key = str(category.get("key") or "").strip().casefold()
        if not category_key:
            return None
        return category_key in _DONE_CATEGORIES

    def _external_identity(self, issue_id: str) -> str:
        return f"jira:{self.site}:{issue_id}"

    def _build_tasks(self) -> list[NormalizedTask]:
        raw_all = self.client.list_all()
        tasks: list[NormalizedTask] = []
        external_issue_cache: dict[str, dict[str, Any]] = {}
        by_key: dict[str, NormalizedTask] = {}
        by_external_id: dict[str, NormalizedTask] = {}
        raw_by_key: dict[str, dict[str, Any]] = {}

        for raw in raw_all:
            key = str(raw.get("key") or "").strip().upper()
            issue_id = str(raw.get("id") or "").strip()
            if not key or not issue_id:
                raise ValueError("Jira issue list contains an issue without stable id/key.")
            if key in by_key:
                raise ValueError(f"Jira issue key appears more than once: {key}.")
            if issue_id in by_external_id:
                raise ValueError(f"Jira issue id appears more than once: {issue_id}.")
            task = self._normalize(raw)
            tasks.append(task)
            by_key[key] = task
            by_external_id[issue_id] = task
            raw_by_key[key] = raw

        # Parent/sub-task hierarchy remains observational and never implies
        # dependency eligibility.
        for key, raw in raw_by_key.items():
            fields = raw.get("fields")
            assert isinstance(fields, dict)
            parent = fields.get("parent")
            if parent is None:
                continue
            task = by_key[key]
            if not isinstance(parent, dict):
                self._mark_needs_decision(task, "Jira parent metadata is not an object.")
                continue

            parent_key = str(parent.get("key") or "").strip().upper()
            parent_id = str(parent.get("id") or "").strip()
            if not parent_key:
                self._mark_needs_decision(
                    task,
                    "Jira parent metadata is missing a key.",
                )
                continue

            local_parent = (
                by_external_id.get(parent_id)
                if parent_id
                else by_key.get(parent_key)
            )
            if local_parent is not None:
                if local_parent.id != self._task_id(parent_key):
                    self._mark_needs_decision(
                        task,
                        "Jira parent stable id/key disagree with the project snapshot.",
                    )
                    continue
                task.hierarchy.parent = local_parent.id
                if task.id not in local_parent.hierarchy.sub_issues:
                    local_parent.hierarchy.sub_issues.append(task.id)
            else:
                task.hierarchy.parent = (
                    self._external_identity(parent_id)
                    if parent_id
                    else f"jira-key:{self.site}:{parent_key}"
                )
                task.normalization_notes.append(
                    "Jira parent is outside the configured project snapshot; "
                    "hierarchy remains observational."
                )

        # Jira issue links are customizable. Only explicitly pinned link-type
        # ids/labels and side semantics are allowed to affect dependencies.
        for key, raw in raw_by_key.items():
            task = by_key[key]
            fields = raw.get("fields")
            assert isinstance(fields, dict)
            links = fields.get("issuelinks")
            if links is None:
                continue
            if not isinstance(links, list):
                self._mark_needs_decision(
                    task,
                    "Jira issuelinks metadata is not a list.",
                )
                continue

            for link in links:
                if not isinstance(link, dict):
                    self._mark_needs_decision(
                        task,
                        "Jira issue link entry is not an object.",
                    )
                    continue
                link_type = link.get("type")
                if not isinstance(link_type, dict):
                    self._mark_needs_decision(
                        task,
                        "Jira issue link is missing link-type metadata.",
                    )
                    continue

                type_id = str(link_type.get("id") or "").strip()
                rule = self._link_rule_by_id.get(type_id)
                if not type_id or rule is None:
                    self._mark_needs_decision(
                        task,
                        f"Jira issue link type {type_id or 'missing'!r} has no "
                        "explicit ProjectCTL semantics.",
                    )
                    continue
                if not self._rule_matches_provider(rule, link_type):
                    self._mark_needs_decision(
                        task,
                        f"Jira issue link type {type_id!r} metadata changed from "
                        "the pinned ProjectCTL policy.",
                    )
                    continue

                sided = self._link_side(link)
                if sided is None:
                    self._mark_needs_decision(
                        task,
                        f"Jira issue link type {type_id!r} does not contain exactly "
                        "one inwardIssue/outwardIssue endpoint.",
                    )
                    continue
                side, linked = sided
                semantic = rule.inward if side == "inward" else rule.outward
                if semantic == "ignore":
                    continue

                linked_id = str(linked.get("id") or "").strip()
                linked_key = str(linked.get("key") or "").strip().upper()
                if not linked_id or not linked_key:
                    self._mark_needs_decision(
                        task,
                        f"Jira {semantic} link is missing linked issue id/key.",
                    )
                    continue

                local = by_external_id.get(linked_id)
                if local is not None and local.id != self._task_id(linked_key):
                    self._mark_needs_decision(
                        task,
                        "Jira linked issue stable id/key disagree with the project snapshot.",
                    )
                    continue

                if local is not None:
                    is_terminal = local.status in _TERMINAL
                    linked_identity = local.id
                    embedded_terminal = self._linked_terminal(linked)
                    if (
                        embedded_terminal is not None
                        and embedded_terminal != is_terminal
                    ):
                        self._mark_needs_decision(
                            task,
                            f"Jira linked issue {linked_key} status disagrees with "
                            "its project snapshot row.",
                        )
                        continue
                else:
                    try:
                        current_external = external_issue_cache.get(linked_id)
                        if current_external is None:
                            current_external = self.client.show_linked(linked_key)
                            external_issue_cache[linked_id] = current_external
                    except (ProviderUnavailableError, TaskStoreError) as exc:
                        self._mark_needs_decision(
                            task,
                            f"Jira external linked issue {linked_key} could not be "
                            f"revalidated safely: {exc}",
                        )
                        continue

                    current_id = str(current_external.get("id") or "").strip()
                    current_key = str(current_external.get("key") or "").strip().upper()
                    if current_id != linked_id or current_key != linked_key:
                        self._mark_needs_decision(
                            task,
                            f"Jira external linked issue {linked_key} changed stable "
                            "id/key during revalidation.",
                        )
                        continue

                    embedded_terminal = self._linked_terminal(linked)
                    current_terminal = self._linked_terminal(current_external)
                    if current_terminal is None:
                        self._mark_needs_decision(
                            task,
                            f"Jira external linked issue {linked_key} has no "
                            "trustworthy current status category.",
                        )
                        continue
                    if (
                        embedded_terminal is not None
                        and embedded_terminal != current_terminal
                    ):
                        task.normalization_notes.append(
                            f"Jira external linked issue {linked_key} embedded status "
                            "was stale; current linked-issue read is authoritative."
                        )
                    is_terminal = current_terminal
                    linked_identity = self._external_identity(linked_id)

                if is_terminal:
                    continue

                if semantic == "dependency":
                    if linked_identity not in task.dependencies:
                        task.dependencies.append(linked_identity)
                    if local is not None and task.id not in local.blocks:
                        local.blocks.append(task.id)
                    if local is None:
                        task.normalization_notes.append(
                            f"Open external Jira blocker {linked_identity} blocks this task."
                        )
                elif semantic == "blocks":
                    if linked_identity not in task.blocks:
                        task.blocks.append(linked_identity)
                    if local is not None and task.id not in local.dependencies:
                        local.dependencies.append(task.id)
                        if local.status == TaskStatus.READY:
                            local.status = TaskStatus.BLOCKED
                else:
                    self._mark_needs_decision(
                        task,
                        f"Unsupported Jira relationship semantic {semantic!r}.",
                    )

            task.dependencies.sort()
            task.blocks.sort()
            overlap = sorted(set(task.dependencies) & set(task.blocks))
            if overlap:
                self._mark_needs_decision(
                    task,
                    "Jira relationship policy produced the same issue as both a "
                    f"dependency and a blocked target: {', '.join(overlap)}.",
                )
            if task.status == TaskStatus.READY and task.dependencies:
                task.status = TaskStatus.BLOCKED

        # Derive reverse local blocks edges from canonical dependency edges.
        task_by_id = {task.id: task for task in tasks}
        for task in tasks:
            for dependency in task.dependencies:
                local = task_by_id.get(dependency)
                if local is not None and task.id not in local.blocks:
                    local.blocks.append(task.id)

        for task in tasks:
            task.blocks = sorted(set(task.blocks))
            task.hierarchy.sub_issues = sorted(set(task.hierarchy.sub_issues))

        dependency_cycles = _cycle_nodes(task_by_id, hierarchy=False)
        for task_id in dependency_cycles:
            self._mark_needs_decision(
                task_by_id[task_id],
                "Jira dependency graph contains a cycle involving this task.",
            )

        hierarchy_cycles = _cycle_nodes(task_by_id, hierarchy=True)
        for task_id in hierarchy_cycles:
            self._mark_needs_decision(
                task_by_id[task_id],
                "Jira parent/sub-task hierarchy contains a cycle involving this task.",
            )

        for key, raw in raw_by_key.items():
            self._apply_lifecycle(by_key[key], raw)

        return sorted(tasks, key=lambda task: task.id.casefold())

    def get(self, task_id: str) -> NormalizedTask:
        normalized_id = str(task_id).strip()
        if not normalized_id.startswith("jira-"):
            normalized_id = self._task_id(normalized_id.upper())
        for task in self._build_tasks():
            if task.id == normalized_id:
                return task
        raise ValueError(f"Jira task {task_id!r} is not present in the authority snapshot.")

    def list_all(self) -> list[NormalizedTask]:
        return self._build_tasks()

    def list_ready(self) -> list[NormalizedTask]:
        return [
            task
            for task in self._build_tasks()
            if task.status == TaskStatus.READY
            and not task.human_decision_required
            and not task.dependencies
        ]

    def list_blocked(self) -> list[NormalizedTask]:
        return [
            task
            for task in self._build_tasks()
            if task.status in {TaskStatus.BLOCKED, TaskStatus.NEEDS_DECISION}
            or task.human_decision_required
            or bool(task.dependencies)
        ]

    def snapshot(
        self,
        *,
        tasks: list[NormalizedTask] | None = None,
    ) -> TaskSnapshot:
        values = tasks if tasks is not None else self._build_tasks()
        tasks_sorted = sorted(values, key=lambda task: task.id.casefold())
        material: list[dict[str, Any]] = []
        for task in tasks_sorted:
            value = task.model_dump(mode="json")
            if isinstance(value.get("source"), dict):
                value["source"].pop("observed_at", None)
            material.append(value)

        return TaskSnapshot(
            provider="jira",
            captured_at=utc_now(),
            source_revision=digest(
                {
                    "site": self.site,
                    "project": self.project_key,
                    "contract": self.client.version(),
                    "policy": self.policy.model_dump(mode="json"),
                    "tasks": material,
                }
            ),
            tasks=tasks_sorted,
        )
