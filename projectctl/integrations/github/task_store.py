from __future__ import annotations

from typing import Any

from projectctl.core.digest import digest
from projectctl.core.enums import ResourceClass, RiskLevel, TaskStatus, TaskType
from projectctl.core.time import utc_now
from projectctl.integrations.github.client import GitHubIssuesClient
from projectctl.schemas.task import NormalizedTask, TaskSnapshot, TaskSource


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
}


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
) -> str | None:
    values = sorted(
        {
            label.split(":", 1)[1].strip().casefold()
            for label in labels
            if label.casefold().startswith(prefix.casefold())
            and ":" in label
            and label.split(":", 1)[1].strip()
        }
    )
    if len(values) == 1:
        return values[0]
    if len(values) > 1:
        notes.append(
            f"Conflicting {prefix.rstrip(':')} labels: {', '.join(values)}."
        )
    return None


class GitHubIssuesTaskStore:
    """Read-only GitHub Issues adapter for M3.0a.

    The adapter deliberately exposes no remote claim/completion mutation.
    M3.0b will add a concurrency-safe write protocol instead of pretending that
    labels or assignees provide compare-and-swap semantics.
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

    def _normalize(self, raw: dict[str, Any]) -> NormalizedTask:
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

        explicit_type = _single_prefixed(labels, "type:", notes=notes)
        if explicit_type is not None:
            task_type = _TYPE.get(explicit_type, TaskType.UNKNOWN)
            if task_type == TaskType.UNKNOWN:
                notes.append(f"Unknown GitHub task type label: type:{explicit_type}.")
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

        priority_key = _single_prefixed(labels, "priority:", notes=notes)
        priority = _PRIORITY.get(priority_key or "", 5)
        if priority_key is not None and priority_key not in _PRIORITY:
            notes.append(
                f"Unknown GitHub priority label: priority:{priority_key}; using medium."
            )

        resource_key = _single_prefixed(labels, "resource:", notes=notes)
        resource = _RESOURCE.get(resource_key or "", ResourceClass.UNKNOWN)
        if resource_key is not None and resource_key not in _RESOURCE:
            notes.append(f"Unknown GitHub resource label: resource:{resource_key}.")

        risk_key = _single_prefixed(labels, "risk:", notes=notes)
        risk = _RISK.get(risk_key or "", RiskLevel.UNKNOWN)
        if risk_key is not None and risk_key not in _RISK:
            notes.append(f"Unknown GitHub risk label: risk:{risk_key}.")

        information_gain = 0
        info_key = _single_prefixed(labels, "info-gain:", notes=notes)
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
        native_title = (
            str(native_milestone.get("title")).strip()
            if isinstance(native_milestone, dict) and native_milestone.get("title")
            else None
        )
        label_milestone = _single_prefixed(labels, "milestone:", notes=notes)
        milestone = native_title or label_milestone
        if (
            native_title
            and label_milestone
            and native_title.casefold() != label_milestone.casefold()
        ):
            milestone = None
            notes.append(
                "GitHub milestone and milestone: label disagree; milestone scoring disabled."
            )

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
            due_at=None,
            dependencies=[],
            blocks=[],
            risk=risk,
            resource_class=resource,
            information_gain=information_gain,
            human_decision_required=human_decision,
            tags=labels,
            normalization_notes=notes,
        )

    def get(self, task_id: str) -> NormalizedTask:
        return self._normalize(self.client.show(task_id))

    def list_all(self) -> list[NormalizedTask]:
        return sorted(
            (self._normalize(raw) for raw in self.client.list_all()),
            key=lambda task: int(task.source.external_id),
        )

    def list_ready(self) -> list[NormalizedTask]:
        return [
            task for task in self.list_all()
            if task.status == TaskStatus.READY and not task.human_decision_required
        ]

    def list_blocked(self) -> list[NormalizedTask]:
        return [
            task for task in self.list_all()
            if task.status in {TaskStatus.BLOCKED, TaskStatus.NEEDS_DECISION}
            or task.human_decision_required
        ]

    def snapshot(self, *, tasks: list[NormalizedTask] | None = None) -> TaskSnapshot:
        values = tasks if tasks is not None else self.list_all()
        tasks_sorted = sorted(values, key=lambda task: int(task.source.external_id))
        material = []
        for task in tasks_sorted:
            value = task.model_dump(mode="json")
            if isinstance(value.get("source"), dict):
                value["source"].pop("observed_at", None)
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
