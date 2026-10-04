from __future__ import annotations

from typing import Any

from projectctl.core.digest import digest
from projectctl.core.enums import ResourceClass, RiskLevel, TaskStatus, TaskType
from projectctl.core.time import utc_now
from projectctl.integrations.github.client import GitHubIssuesClient
from projectctl.schemas.task import (
    NormalizedTask,
    TaskHierarchy,
    TaskIssueField,
    TaskMilestoneMetadata,
    TaskSnapshot,
    TaskSource,
    TaskTeamMetadata,
)


_PRIORITY = {
    "p0": 10,
    "p1": 8,
    "p2": 5,
    "p3": 3,
    "p4": 1,
}
_TYPE = {
    "task": TaskType.TASK,
    "feature": TaskType.FEATURE,
    "bug": TaskType.BUG,
    "refactor": TaskType.REFACTOR,
    "research": TaskType.RESEARCH,
    "experiment": TaskType.EXPERIMENT,
    "architecture": TaskType.ARCHITECTURE,
    "security": TaskType.SECURITY,
    "docs": TaskType.DOCS,
    "chore": TaskType.CHORE,
}
_RESOURCE = {value.value: value for value in ResourceClass if value != ResourceClass.UNKNOWN}
_RISK = {value.value: value for value in RiskLevel if value != RiskLevel.UNKNOWN}
_LIFECYCLE = {
    "projectctl:planned": TaskStatus.PLANNED,
    "projectctl:running": TaskStatus.RUNNING,
    "projectctl:blocked": TaskStatus.BLOCKED,
    "projectctl:needs-decision": TaskStatus.NEEDS_DECISION,
    "projectctl:completed": TaskStatus.DONE,
}
_TERMINAL = {TaskStatus.DONE, TaskStatus.CANCELLED}


def _labels(raw: dict[str, Any]) -> list[str]:
    result: list[str] = []
    for item in raw.get("labels") or []:
        if isinstance(item, str):
            name = item
        elif isinstance(item, dict):
            name = item.get("name")
        else:
            name = None
        if name is not None and str(name).strip():
            result.append(str(name).strip())
    return sorted(set(result), key=str.casefold)


def _single_prefixed(
    labels: list[str],
    prefix: str,
    *,
    notes: list[str],
) -> tuple[str | None, bool]:
    by_folded: dict[str, str] = {}
    for label in labels:
        if not label.casefold().startswith(prefix.casefold()) or ":" not in label:
            continue
        raw = label.split(":", 1)[1].strip()
        if raw:
            by_folded.setdefault(raw.casefold(), raw)
    values = [by_folded[key] for key in sorted(by_folded)]
    if len(values) == 1:
        return values[0], False
    if len(values) > 1:
        notes.append(
            f"Conflicting {prefix.rstrip(':')} labels: {', '.join(values)}."
        )
        return None, True
    return None, False


def _issue_repository(raw: dict[str, Any]) -> str | None:
    repository_url = str(raw.get("repository_url") or "").strip()
    prefix = "https://api.github.com/repos/"
    if repository_url.startswith(prefix):
        value = repository_url[len(prefix):].strip("/")
        if value.count("/") == 1:
            return value

    html_url = str(raw.get("html_url") or "").strip()
    html_prefix = "https://github.com/"
    if html_url.startswith(html_prefix):
        parts = html_url[len(html_prefix):].strip("/").split("/")
        if len(parts) >= 2 and parts[0] and parts[1]:
            return f"{parts[0]}/{parts[1]}"
    return None


def _relation_id(
    raw: dict[str, Any],
    *,
    current_repository: str,
) -> tuple[str | None, bool, bool, str | None]:
    number = raw.get("number")
    if not isinstance(number, int) or number <= 0:
        return None, False, False, "GitHub relation is missing a positive issue number."

    repository = _issue_repository(raw)
    if repository is None:
        return (
            None,
            False,
            False,
            f"GitHub relation #{number} has no trustworthy repository identity.",
        )

    state = str(raw.get("state") or "").casefold()
    state_reason = str(raw.get("state_reason") or "").casefold()
    satisfied = state == "closed" and state_reason != "not_planned"
    is_pull_request = "pull_request" in raw

    if repository.casefold() == current_repository.casefold() and not is_pull_request:
        return f"gh-{number}", True, satisfied, None

    kind = "github-pr" if is_pull_request else "github"
    return f"{kind}:{repository}#{number}", False, satisfied, None


def _assignees(raw: dict[str, Any], *, notes: list[str]) -> list[str]:
    result: list[str] = []
    for item in raw.get("assignees") or []:
        if not isinstance(item, dict):
            notes.append("GitHub assignee metadata contains a non-object entry.")
            continue
        login = str(item.get("login") or "").strip()
        if not login:
            notes.append("GitHub assignee metadata contains an entry without login.")
            continue
        result.append(login)
    return sorted(set(result), key=str.casefold)


def _issue_type_name(raw: dict[str, Any]) -> str | None:
    value = raw.get("type")
    if isinstance(value, str):
        result = value.strip()
        return result or None
    if isinstance(value, dict):
        result = str(value.get("name") or "").strip()
        return result or None
    return None


def _issue_field(
    raw: dict[str, Any],
    *,
    notes: list[str],
) -> TaskIssueField | None:
    field_id = raw.get("issue_field_id") or raw.get("node_id")
    name = str(raw.get("issue_field_name") or "").strip()
    data_type = str(raw.get("data_type") or "").strip()
    if field_id is None or not name or not data_type:
        notes.append("GitHub issue field metadata is missing id, name, or data_type.")
        return None

    value: str | int | float | bool | list[str] | None
    if data_type == "single_select":
        option = raw.get("single_select_option")
        value = (
            str(option.get("name")).strip()
            if isinstance(option, dict) and option.get("name") is not None
            else None
        )
    elif data_type == "multi_select":
        values: list[str] = []
        for option in raw.get("multi_select_options") or []:
            if isinstance(option, dict) and option.get("name") is not None:
                name_value = str(option["name"]).strip()
                if name_value:
                    values.append(name_value)
        value = sorted(set(values), key=str.casefold)
    else:
        raw_value = raw.get("value")
        if raw_value is None or isinstance(raw_value, (str, int, float, bool)):
            value = raw_value
        elif isinstance(raw_value, list) and all(
            isinstance(item, str) for item in raw_value
        ):
            value = sorted(set(raw_value), key=str.casefold)
        else:
            notes.append(
                f"GitHub issue field {name!r} has an unsupported value shape; value omitted."
            )
            value = None

    return TaskIssueField(
        field_id=str(field_id),
        name=name,
        data_type=data_type,
        value=value,
    )


def _issue_fields(
    raw_values: list[dict[str, Any]] | None,
    *,
    notes: list[str],
) -> list[TaskIssueField]:
    fields = [
        field
        for raw in raw_values or []
        if (field := _issue_field(raw, notes=notes)) is not None
    ]
    return sorted(fields, key=lambda field: (field.name.casefold(), field.field_id))


def _milestone_metadata(raw: Any) -> TaskMilestoneMetadata | None:
    if not isinstance(raw, dict):
        return None
    title = str(raw.get("title") or "").strip()
    if not title:
        return None
    number = raw.get("number")
    return TaskMilestoneMetadata(
        number=number if isinstance(number, int) else None,
        title=title,
        state=str(raw.get("state")).strip() if raw.get("state") is not None else None,
        due_on=raw.get("due_on"),
        external_url=(
            str(raw.get("html_url")).strip()
            if raw.get("html_url") is not None
            else None
        ),
        open_issues=raw.get("open_issues") if isinstance(raw.get("open_issues"), int) else None,
        closed_issues=(
            raw.get("closed_issues")
            if isinstance(raw.get("closed_issues"), int)
            else None
        ),
    )


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
                start = stack_index[target]
                cyclic.update(stack[start:])
        stack.pop()
        stack_index.pop(node, None)
        color[node] = 2

    for node in sorted(graph):
        if color.get(node, 0) == 0:
            visit(node)
    return cyclic


class GitHubIssuesTaskStore:
    """GitHub Issues task adapter with structured team relations.

    Native GitHub issue dependencies drive scheduler blocking. Sub-issues are
    hierarchy only and never become dependencies implicitly.
    """

    def __init__(
        self,
        project_root,
        *,
        repository: str | None = None,
        client: GitHubIssuesClient | None = None,
    ):
        self.project_root = project_root.resolve()
        self.client = client or GitHubIssuesClient(
            self.project_root,
            repository=repository,
        )

    def _normalize(
        self,
        raw: dict[str, Any],
        *,
        blocked_by: list[dict[str, Any]] | None = None,
        sub_issues: list[dict[str, Any]] | None = None,
        issue_fields: list[dict[str, Any]] | None = None,
    ) -> NormalizedTask:
        number = raw.get("number")
        if not isinstance(number, int) or number <= 0:
            raise ValueError("GitHub issue payload is missing a positive issue number.")
        task_id = f"gh-{number}"
        labels = _labels(raw)
        folded = {label.casefold() for label in labels}
        notes: list[str] = []

        state = str(raw.get("state") or "open").casefold()
        state_reason = str(raw.get("state_reason") or "").casefold()
        lifecycle = sorted(
            {status for label, status in _LIFECYCLE.items() if label in folded},
            key=lambda value: value.value,
        )

        human_decision = "projectctl:needs-decision" in folded
        if state == "closed":
            status = (
                TaskStatus.CANCELLED
                if state_reason == "not_planned"
                else TaskStatus.DONE
            )
        elif len(lifecycle) > 1:
            status = TaskStatus.NEEDS_DECISION
            human_decision = True
            notes.append(
                "Conflicting ProjectCTL lifecycle labels; task is not auto-eligible."
            )
        elif lifecycle:
            status = lifecycle[0]
        else:
            status = TaskStatus.READY

        metadata_conflict = False

        native_issue_type = _issue_type_name(raw)
        native_task_type = (
            _TYPE.get(native_issue_type.casefold(), TaskType.UNKNOWN)
            if native_issue_type
            else TaskType.UNKNOWN
        )

        explicit_type, conflicted = _single_prefixed(labels, "type:", notes=notes)
        metadata_conflict = metadata_conflict or conflicted
        if explicit_type is not None:
            task_type = _TYPE.get(explicit_type, TaskType.UNKNOWN)
            if task_type == TaskType.UNKNOWN:
                notes.append(f"Unknown GitHub task type label: type:{explicit_type}.")
            if (
                task_type != TaskType.UNKNOWN
                and native_task_type != TaskType.UNKNOWN
                and task_type != native_task_type
            ):
                metadata_conflict = True
                notes.append(
                    "GitHub native issue type conflicts with explicit ProjectCTL type label: "
                    f"{native_issue_type!r} vs type:{explicit_type}."
                )
        elif native_task_type != TaskType.UNKNOWN:
            task_type = native_task_type
        elif "bug" in folded:
            task_type = TaskType.BUG
        elif "enhancement" in folded:
            task_type = TaskType.FEATURE
        elif "documentation" in folded:
            task_type = TaskType.DOCS
        elif "security" in folded:
            task_type = TaskType.SECURITY
        else:
            task_type = TaskType.UNKNOWN

        priority_key, conflicted = _single_prefixed(labels, "priority:", notes=notes)
        metadata_conflict = metadata_conflict or conflicted
        priority = _PRIORITY.get(priority_key or "", 5)
        if priority_key is not None and priority_key not in _PRIORITY:
            notes.append(
                f"Unknown GitHub priority label: priority:{priority_key}; using medium."
            )

        resource_key, conflicted = _single_prefixed(labels, "resource:", notes=notes)
        metadata_conflict = metadata_conflict or conflicted
        resource = _RESOURCE.get(resource_key or "", ResourceClass.UNKNOWN)
        if resource_key is not None and resource_key not in _RESOURCE:
            notes.append(f"Unknown GitHub resource label: resource:{resource_key}.")

        risk_key, conflicted = _single_prefixed(labels, "risk:", notes=notes)
        metadata_conflict = metadata_conflict or conflicted
        risk = _RISK.get(risk_key or "", RiskLevel.UNKNOWN)
        if risk_key is not None and risk_key not in _RISK:
            notes.append(f"Unknown GitHub risk label: risk:{risk_key}.")

        information_gain = 0
        info_key, conflicted = _single_prefixed(labels, "info-gain:", notes=notes)
        metadata_conflict = metadata_conflict or conflicted
        if info_key is not None:
            try:
                parsed = int(info_key)
            except ValueError:
                parsed = -1
            if 0 <= parsed <= 5:
                information_gain = parsed
            else:
                notes.append(
                    f"Invalid GitHub information-gain label: info-gain:{info_key}."
                )

        native_milestone = raw.get("milestone")
        milestone_metadata = _milestone_metadata(native_milestone)
        native_title = milestone_metadata.title if milestone_metadata else None
        label_milestone, conflicted = _single_prefixed(labels, "milestone:", notes=notes)
        metadata_conflict = metadata_conflict or conflicted
        milestone = native_title or label_milestone
        if (
            native_title
            and label_milestone
            and native_title.casefold() != label_milestone.casefold()
        ):
            milestone = None
            metadata_conflict = True
            notes.append(
                "GitHub milestone and milestone: label disagree; milestone scoring disabled."
            )

        dependencies: list[str] = []
        unresolved_dependency = False
        for relation in blocked_by or []:
            relation_id, local, satisfied, error = _relation_id(
                relation,
                current_repository=self.client.repository,
            )
            if error:
                human_decision = True
                notes.append(error)
                continue
            if relation_id is None:
                continue
            if local:
                dependencies.append(relation_id)
                if not satisfied:
                    unresolved_dependency = True
            elif not satisfied:
                dependencies.append(relation_id)
                unresolved_dependency = True
                notes.append(
                    f"Open external GitHub dependency {relation_id} blocks this task."
                )
            else:
                notes.append(
                    f"External GitHub dependency {relation_id} is already closed/completed."
                )

        hierarchy_children: list[str] = []
        for relation in sub_issues or []:
            relation_id, _local, _satisfied, error = _relation_id(
                relation,
                current_repository=self.client.repository,
            )
            if error:
                human_decision = True
                notes.append(error)
                continue
            if relation_id is not None:
                hierarchy_children.append(relation_id)

        if state != "closed" and metadata_conflict:
            status = TaskStatus.NEEDS_DECISION
            human_decision = True
            notes.append(
                "Conflicting GitHub scheduling metadata requires human normalization."
            )
        elif status == TaskStatus.READY and unresolved_dependency:
            status = TaskStatus.BLOCKED

        if state != "closed" and human_decision and status not in {
            TaskStatus.RUNNING,
            TaskStatus.BLOCKED,
            TaskStatus.PLANNED,
        }:
            status = TaskStatus.NEEDS_DECISION

        return NormalizedTask(
            id=task_id,
            title=str(raw.get("title") or task_id),
            source=TaskSource(
                provider="github",
                external_id=str(number),
                revision=str(raw.get("updated_at")) if raw.get("updated_at") else None,
                external_url=str(raw.get("html_url")) if raw.get("html_url") else None,
                observed_at=utc_now(),
            ),
            type=task_type,
            status=status,
            priority=priority,
            milestone=milestone,
            created_at=raw.get("created_at"),
            ready_since=None,
            due_at=(
                milestone_metadata.due_on
                if milestone_metadata is not None and milestone is not None
                else None
            ),
            dependencies=sorted(set(dependencies)),
            blocks=[],
            hierarchy=TaskHierarchy(
                sub_issues=sorted(set(hierarchy_children)),
            ),
            team=TaskTeamMetadata(
                assignees=_assignees(raw, notes=notes),
                issue_type=native_issue_type,
                milestone=milestone_metadata,
                issue_fields=_issue_fields(issue_fields, notes=notes),
            ),
            risk=risk,
            resource_class=resource,
            information_gain=information_gain,
            human_decision_required=human_decision,
            tags=labels,
            normalization_notes=notes,
        )

    @staticmethod
    def _mark_needs_decision(task: NormalizedTask, note: str) -> None:
        if note not in task.normalization_notes:
            task.normalization_notes.append(note)
        task.human_decision_required = True
        if task.status not in _TERMINAL:
            task.status = TaskStatus.NEEDS_DECISION

    def _build_tasks(self) -> list[NormalizedTask]:
        raw_all = self.client.list_all()
        blocked_by: dict[int, list[dict[str, Any]]] = {}
        sub_issues: dict[int, list[dict[str, Any]]] = {}
        issue_fields: dict[int, list[dict[str, Any]]] = {}

        for raw in raw_all:
            number = raw.get("number")
            if not isinstance(number, int) or number <= 0:
                raise ValueError("GitHub issue list contains an invalid issue number.")
            blocked_by[number] = self.client.list_blocked_by(number)
            sub_issues[number] = self.client.list_sub_issues(number)
            issue_fields[number] = self.client.list_issue_field_values(number)

        tasks = [
            self._normalize(
                raw,
                blocked_by=blocked_by[int(raw["number"])],
                sub_issues=sub_issues[int(raw["number"])],
                issue_fields=issue_fields[int(raw["number"])],
            )
            for raw in raw_all
        ]
        by_id = {task.id: task for task in tasks}

        # Reverse dependency edges are derived from the canonical blocked_by
        # relation, avoiding a second independent representation.
        for task in tasks:
            for dependency in task.dependencies:
                if dependency in by_id and task.id not in by_id[dependency].blocks:
                    by_id[dependency].blocks.append(task.id)
                    by_id[dependency].blocks.sort()

        # Parent pointers are derived from the canonical sub-issue lists.
        parents: dict[str, str] = {}
        for task in tasks:
            for child in task.hierarchy.sub_issues:
                if child not in by_id:
                    continue
                previous = parents.get(child)
                if previous is not None and previous != task.id:
                    self._mark_needs_decision(
                        by_id[child],
                        f"GitHub sub-issue {child} has multiple parents: {previous}, {task.id}.",
                    )
                    self._mark_needs_decision(
                        task,
                        f"Sub-issue hierarchy conflicts for {child}.",
                    )
                    self._mark_needs_decision(
                        by_id[previous],
                        f"Sub-issue hierarchy conflicts for {child}.",
                    )
                    continue
                parents[child] = task.id

        for child, parent in parents.items():
            by_id[child].hierarchy.parent = parent

        # Missing same-repository dependency nodes are ambiguous: the relation
        # endpoint proved they exist, but they are absent from the authority
        # snapshot (for example due to visibility or filtering).
        for task in tasks:
            missing = [
                dependency
                for dependency in task.dependencies
                if dependency.startswith("gh-") and dependency not in by_id
            ]
            if missing:
                self._mark_needs_decision(
                    task,
                    "GitHub dependencies are absent from the current task snapshot: "
                    + ", ".join(sorted(missing))
                    + ".",
                )

        dependency_cycles = _cycle_nodes(by_id, hierarchy=False)
        for task_id in dependency_cycles:
            self._mark_needs_decision(
                by_id[task_id],
                "GitHub dependency graph contains a cycle involving this task.",
            )

        hierarchy_cycles = _cycle_nodes(by_id, hierarchy=True)
        for task_id in hierarchy_cycles:
            self._mark_needs_decision(
                by_id[task_id],
                "GitHub sub-issue hierarchy contains a cycle involving this task.",
            )

        return sorted(tasks, key=lambda task: int(task.source.external_id))

    def get(self, task_id: str) -> NormalizedTask:
        for task in self._build_tasks():
            if task.id == task_id:
                return task
        # Preserve the provider's precise not-found/error behavior.
        self.client.show(task_id)
        raise ValueError(f"GitHub task {task_id!r} is not present in the authority snapshot.")

    def list_all(self) -> list[NormalizedTask]:
        return self._build_tasks()

    def list_ready(self) -> list[NormalizedTask]:
        tasks = self._build_tasks()
        by_id = {task.id: task for task in tasks}
        return [
            task
            for task in tasks
            if task.status == TaskStatus.READY
            and not task.human_decision_required
            and all(
                dependency in by_id and by_id[dependency].status == TaskStatus.DONE
                for dependency in task.dependencies
            )
        ]

    def list_blocked(self) -> list[NormalizedTask]:
        tasks = self._build_tasks()
        by_id = {task.id: task for task in tasks}
        return [
            task
            for task in tasks
            if task.status in {TaskStatus.BLOCKED, TaskStatus.NEEDS_DECISION}
            or task.human_decision_required
            or any(
                dependency not in by_id or by_id[dependency].status != TaskStatus.DONE
                for dependency in task.dependencies
            )
        ]

    def snapshot(self, *, tasks: list[NormalizedTask] | None = None) -> TaskSnapshot:
        values = tasks if tasks is not None else self._build_tasks()
        tasks_sorted = sorted(values, key=lambda task: int(task.source.external_id))
        material = []
        for task in tasks_sorted:
            value = task.model_dump(mode="json")
            if isinstance(value.get("source"), dict):
                value["source"].pop("observed_at", None)
            value.pop("team", None)
            material.append(value)
        content_revision = digest(material)
        version = self.client.version()
        suffix = f";{version}" if version else ""
        return TaskSnapshot(
            provider="github",
            captured_at=utc_now(),
            source_revision=f"{content_revision};repo={self.client.repository}{suffix}",
            tasks=tasks_sorted,
        )
