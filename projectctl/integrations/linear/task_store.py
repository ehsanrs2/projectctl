from __future__ import annotations

from typing import Any

from projectctl.core.digest import digest
from projectctl.core.enums import ResourceClass, RiskLevel, TaskStatus, TaskType
from projectctl.core.time import utc_now
from projectctl.integrations.linear.client import LinearIssuesClient
from projectctl.integrations.linear.lifecycle import COMPLETED_LABEL, NEEDS_DECISION_LABEL
from projectctl.schemas.task import (
    NormalizedTask,
    TaskHierarchy,
    TaskSnapshot,
    TaskSource,
    TaskTeamMetadata,
)


_PRIORITY = {
    0: 5,   # Linear: no priority
    1: 10,  # urgent
    2: 8,   # high
    3: 5,   # medium
    4: 3,   # low
}

_TERMINAL_STATE_TYPES = {"completed", "canceled"}


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


class LinearIssuesTaskStore:
    """Read-only Linear authority with M3.2b dependency eligibility semantics.

    Incoming Linear `blocks` relations are canonical blocked-by edges.
    Parent/sub-issue hierarchy remains separate and never blocks implicitly.
    ProjectCTL lifecycle labels are additive authority markers. Native Linear
    terminal workflow state remains authoritative; conflicting ProjectCTL
    markers fail closed to NEEDS_DECISION.
    """

    def __init__(
        self,
        project_root,
        *,
        team_id: str,
        client: LinearIssuesClient | None = None,
    ):
        self.project_root = project_root.resolve()
        self.client = client or LinearIssuesClient(
            self.project_root,
            team_id=team_id,
        )
        self.team_id = self.client.team_id

    @staticmethod
    def _state(
        raw: dict[str, Any],
        *,
        lifecycle_label_ids: dict[str, str],
    ) -> tuple[TaskStatus, bool, list[str], list[str]]:
        notes: list[str] = []
        state = raw.get("state")
        if not isinstance(state, dict):
            return (
                TaskStatus.NEEDS_DECISION,
                True,
                ["Linear issue is missing workflow state metadata."],
                [],
            )

        state_type = str(state.get("type") or "").strip().casefold()
        state_name = str(state.get("name") or "").strip() or "unknown"

        label_ids_raw = raw.get("labelIds")
        if label_ids_raw is None:
            label_ids: set[str] = set()
        elif isinstance(label_ids_raw, list):
            label_ids = {str(value) for value in label_ids_raw if str(value).strip()}
        else:
            notes.append("Linear labelIds metadata is not a list.")
            return TaskStatus.NEEDS_DECISION, True, notes, []

        completed_id = lifecycle_label_ids.get(COMPLETED_LABEL)
        decision_id = lifecycle_label_ids.get(NEEDS_DECISION_LABEL)
        has_completed = bool(completed_id and completed_id in label_ids)
        has_decision = bool(decision_id and decision_id in label_ids)
        lifecycle_tags: list[str] = []
        if has_completed:
            lifecycle_tags.append(COMPLETED_LABEL)
        if has_decision:
            lifecycle_tags.append(NEEDS_DECISION_LABEL)

        if state_type == "completed":
            return TaskStatus.DONE, False, notes, lifecycle_tags
        if state_type == "canceled":
            return TaskStatus.CANCELLED, False, notes, lifecycle_tags

        if has_completed and has_decision:
            notes.append(
                "Conflicting ProjectCTL Linear lifecycle labels; explicit human "
                "decision is required."
            )
            return TaskStatus.NEEDS_DECISION, True, notes, lifecycle_tags
        if has_decision:
            notes.append(
                "ProjectCTL marked this Linear task as needing explicit human review."
            )
            return TaskStatus.NEEDS_DECISION, True, notes, lifecycle_tags
        if has_completed:
            notes.append(
                "ProjectCTL completion marker is present; native Linear workflow "
                "state is preserved."
            )
            return TaskStatus.DONE, False, notes, lifecycle_tags
        if state_type == "started":
            notes.append(
                f"Linear workflow state {state_name!r} is already started; "
                "ProjectCTL observes it as running but does not own it."
            )
            return TaskStatus.RUNNING, False, notes, lifecycle_tags
        if state_type == "backlog":
            notes.append(
                "Linear backlog state is planning intent, not scheduler readiness."
            )
            return TaskStatus.PLANNED, False, notes, lifecycle_tags
        if state_type == "unstarted":
            return TaskStatus.READY, False, notes, lifecycle_tags

        notes.append(
            f"Unknown Linear workflow state type {state_type or 'missing'!r}; "
            "human normalization is required."
        )
        return TaskStatus.NEEDS_DECISION, True, notes, lifecycle_tags

    @staticmethod
    def _task_id(identifier: str) -> str:
        return f"lin-{identifier}"

    def _normalize(
        self,
        raw: dict[str, Any],
        *,
        lifecycle_label_ids: dict[str, str],
    ) -> NormalizedTask:
        external_id = str(raw.get("id") or "").strip()
        identifier = str(raw.get("identifier") or "").strip()
        title = str(raw.get("title") or "").strip()

        if not external_id:
            raise ValueError("Linear issue payload is missing its stable id.")
        if not identifier:
            raise ValueError("Linear issue payload is missing its identifier.")
        if not title:
            title = identifier

        status, human_decision, notes, lifecycle_tags = self._state(
            raw,
            lifecycle_label_ids=lifecycle_label_ids,
        )

        priority_raw = raw.get("priority")
        priority = _PRIORITY.get(priority_raw, 5) if isinstance(priority_raw, int) else 5
        if priority_raw is not None and (
            not isinstance(priority_raw, int) or priority_raw not in _PRIORITY
        ):
            notes.append(
                f"Unknown Linear priority value {priority_raw!r}; using medium."
            )

        assignees: list[str] = []
        assignee = raw.get("assignee")
        if assignee is not None:
            if not isinstance(assignee, dict):
                notes.append("Linear assignee metadata is not an object.")
            else:
                name = str(assignee.get("name") or "").strip()
                if name:
                    assignees.append(name)
                else:
                    notes.append("Linear assignee metadata has no display name.")

        state = raw.get("state")
        state_name = (
            str(state.get("name") or "").strip()
            if isinstance(state, dict)
            else None
        )

        return NormalizedTask(
            id=self._task_id(identifier),
            title=title,
            source=TaskSource(
                provider="linear",
                external_id=external_id,
                revision=(
                    str(raw.get("updatedAt")).strip()
                    if raw.get("updatedAt") is not None
                    else None
                ),
                external_url=None,
                observed_at=utc_now(),
            ),
            type=TaskType.UNKNOWN,
            status=status,
            priority=priority,
            milestone=None,
            created_at=raw.get("createdAt"),
            ready_since=None,
            due_at=None,
            dependencies=[],
            blocks=[],
            hierarchy=TaskHierarchy(),
            team=TaskTeamMetadata(
                assignees=sorted(set(assignees), key=str.casefold),
                issue_type=None,
                milestone=None,
            ),
            risk=RiskLevel.UNKNOWN,
            resource_class=ResourceClass.UNKNOWN,
            information_gain=0,
            human_decision_required=human_decision,
            tags=(
                ([f"linear-state:{state_name}"] if state_name else [])
                + lifecycle_tags
            ),
            normalization_notes=notes,
        )

    @staticmethod
    def _mark_needs_decision(task: NormalizedTask, note: str) -> None:
        if note not in task.normalization_notes:
            task.normalization_notes.append(note)
        task.human_decision_required = True
        if task.status not in {TaskStatus.DONE, TaskStatus.CANCELLED}:
            task.status = TaskStatus.NEEDS_DECISION

    @staticmethod
    def _external_identity(issue_uuid: str) -> str:
        return f"linear:{issue_uuid}"

    def _build_tasks(self) -> list[NormalizedTask]:
        lifecycle_label_ids = self.client.team_label_ids(
            [COMPLETED_LABEL, NEEDS_DECISION_LABEL]
        )
        raw_all = self.client.list_all()
        tasks: list[NormalizedTask] = []
        raw_by_uuid: dict[str, dict[str, Any]] = {}
        task_by_uuid: dict[str, NormalizedTask] = {}
        task_by_id: dict[str, NormalizedTask] = {}

        for raw in raw_all:
            issue_uuid = str(raw.get("id") or "").strip()
            identifier = str(raw.get("identifier") or "").strip()
            if not issue_uuid or not identifier:
                raise ValueError(
                    "Linear issue list contains an issue without stable id/identifier."
                )
            if issue_uuid in raw_by_uuid:
                raise ValueError(f"Linear issue UUID appears more than once: {issue_uuid}.")
            task = self._normalize(
                raw,
                lifecycle_label_ids=lifecycle_label_ids,
            )
            if task.id in task_by_id:
                raise ValueError(
                    f"Linear issue identifier appears more than once: {identifier}."
                )
            raw_by_uuid[issue_uuid] = raw
            task_by_uuid[issue_uuid] = task
            task_by_id[task.id] = task
            tasks.append(task)

        # Parent is a singleton field on the team Issue page, so hierarchy can
        # be normalized without a nested paginated children connection.
        for issue_uuid, raw in raw_by_uuid.items():
            task = task_by_uuid[issue_uuid]
            parent = raw.get("parent")
            if parent is None:
                continue
            if not isinstance(parent, dict):
                self._mark_needs_decision(
                    task,
                    "Linear parent metadata is not an object.",
                )
                continue
            parent_uuid = str(parent.get("id") or "").strip()
            if not parent_uuid:
                self._mark_needs_decision(
                    task,
                    "Linear parent metadata is missing a stable id.",
                )
                continue
            if parent_uuid in task_by_uuid:
                task.hierarchy.parent = task_by_uuid[parent_uuid].id
            else:
                task.hierarchy.parent = self._external_identity(parent_uuid)
                task.normalization_notes.append(
                    "Linear parent is outside the configured team snapshot; "
                    "hierarchy is observational and does not block eligibility."
                )

        # Canonical dependencies come from incoming inverseRelations. For a
        # relation with type=blocks, relation.issue is the blocker/source and
        # relation.relatedIssue must be this task/target.
        for issue_uuid, task in task_by_uuid.items():
            for relation in self.client.list_inverse_relations(issue_uuid):
                relation_type = str(relation.get("type") or "").strip().casefold()
                if relation_type in {"related", "duplicate", "similar"}:
                    continue
                if relation_type != "blocks":
                    self._mark_needs_decision(
                        task,
                        "Linear relation has an unknown or missing type; "
                        "dependency semantics are ambiguous.",
                    )
                    continue

                target = relation.get("relatedIssue")
                blocker = relation.get("issue")
                if not isinstance(target, dict) or not isinstance(blocker, dict):
                    self._mark_needs_decision(
                        task,
                        "Linear blocks relation is missing source/target issue metadata.",
                    )
                    continue

                target_uuid = str(target.get("id") or "").strip()
                target_team = target.get("team")
                target_team_id = (
                    str(target_team.get("id") or "").strip()
                    if isinstance(target_team, dict)
                    else ""
                )
                if target_uuid != issue_uuid or target_team_id != self.team_id:
                    self._mark_needs_decision(
                        task,
                        "Linear inverse blocks relation target/team does not match "
                        "the requested authority issue; relation direction is ambiguous.",
                    )
                    continue

                blocker_uuid = str(blocker.get("id") or "").strip()
                if not blocker_uuid:
                    self._mark_needs_decision(
                        task,
                        "Linear blocker relation is missing blocker id.",
                    )
                    continue

                blocker_state = blocker.get("state")
                blocker_state_type = (
                    str(blocker_state.get("type") or "").strip().casefold()
                    if isinstance(blocker_state, dict)
                    else ""
                )
                if not blocker_state_type:
                    self._mark_needs_decision(
                        task,
                        f"Linear blocker {blocker_uuid} is missing workflow state.",
                    )
                    continue

                # Resolved blockers are satisfied even if a provider response
                # still exposes the historical relation as blocks.
                if blocker_state_type in _TERMINAL_STATE_TYPES:
                    continue

                blocker_team = blocker.get("team")
                blocker_team_id = (
                    str(blocker_team.get("id") or "").strip()
                    if isinstance(blocker_team, dict)
                    else ""
                )

                if blocker_uuid in task_by_uuid:
                    dependency = task_by_uuid[blocker_uuid].id
                    if blocker_team_id != self.team_id:
                        self._mark_needs_decision(
                            task,
                            "Linear blocker UUID is present in the configured team "
                            "snapshot but relation team identity disagrees.",
                        )
                else:
                    dependency = self._external_identity(blocker_uuid)
                    if not blocker_team_id:
                        self._mark_needs_decision(
                            task,
                            "Unresolved Linear blocker is missing team identity.",
                        )
                    elif blocker_team_id == self.team_id:
                        self._mark_needs_decision(
                            task,
                            "Unresolved Linear blocker belongs to the configured "
                            "team but is absent from the authority snapshot.",
                        )
                    else:
                        task.normalization_notes.append(
                            f"Open external Linear blocker {dependency} blocks this task."
                        )

                if dependency not in task.dependencies:
                    task.dependencies.append(dependency)

            task.dependencies.sort()
            if task.status == TaskStatus.READY and task.dependencies:
                task.status = TaskStatus.BLOCKED

        # Reverse local dependency edges from the canonical blocked-by graph.
        for task in tasks:
            for dependency in task.dependencies:
                if dependency in task_by_id:
                    blocker = task_by_id[dependency]
                    if task.id not in blocker.blocks:
                        blocker.blocks.append(task.id)
                        blocker.blocks.sort()

        # Reverse local parent pointers into sub-issue lists. External children
        # are outside this team-scoped authority snapshot and are not invented.
        for task in tasks:
            parent = task.hierarchy.parent
            if parent in task_by_id:
                parent_task = task_by_id[parent]
                if task.id not in parent_task.hierarchy.sub_issues:
                    parent_task.hierarchy.sub_issues.append(task.id)
                    parent_task.hierarchy.sub_issues.sort()

        dependency_cycles = _cycle_nodes(task_by_id, hierarchy=False)
        for task_id in dependency_cycles:
            self._mark_needs_decision(
                task_by_id[task_id],
                "Linear dependency graph contains a cycle involving this task.",
            )

        hierarchy_cycles = _cycle_nodes(task_by_id, hierarchy=True)
        for task_id in hierarchy_cycles:
            self._mark_needs_decision(
                task_by_id[task_id],
                "Linear parent/sub-issue hierarchy contains a cycle involving this task.",
            )

        return sorted(tasks, key=lambda task: task.id.casefold())

    def get(self, task_id: str) -> NormalizedTask:
        for task in self._build_tasks():
            if task.id == task_id:
                return task
        raise ValueError(f"Linear task {task_id!r} is not present in the authority snapshot.")

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

    def snapshot(self, *, tasks: list[NormalizedTask] | None = None) -> TaskSnapshot:
        values = tasks if tasks is not None else self._build_tasks()
        tasks_sorted = sorted(values, key=lambda task: task.id.casefold())
        material: list[dict[str, Any]] = []
        for task in tasks_sorted:
            value = task.model_dump(mode="json")
            if isinstance(value.get("source"), dict):
                value["source"].pop("observed_at", None)
            # Team assignment is observational and does not affect scheduling
            # or execution semantics.
            value.pop("team", None)
            material.append(value)

        return TaskSnapshot(
            provider="linear",
            captured_at=utc_now(),
            source_revision=(
                f"{digest(material)};team={self.team_id};{self.client.version()}"
            ),
            tasks=tasks_sorted,
        )
