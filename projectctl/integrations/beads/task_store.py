from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from projectctl.core.digest import digest
from projectctl.core.enums import ResourceClass, RiskLevel, TaskStatus, TaskType
from projectctl.integrations.beads.client import BeadsClient
from projectctl.schemas.task import NormalizedTask, TaskSnapshot, TaskSource
from projectctl.core.time import utc_now


_BEADS_PRIORITY_TO_PROJECTCTL = {0: 10, 1: 8, 2: 5, 3: 3, 4: 1}


def _task_type(value: Any) -> TaskType:
    raw = str(value or "").lower()
    return {
        "bug": TaskType.BUG,
        "feature": TaskType.FEATURE,
        "task": TaskType.TASK,
        "chore": TaskType.CHORE,
    }.get(raw, TaskType.UNKNOWN)


def _date(value: Any) -> Any:
    # Pydantic will validate/parse ISO strings. Keep absent fields absent.
    return value if value not in ("", None) else None


def _typed_blocking_ids(items: Any) -> list[str]:
    if not isinstance(items, list):
        return []
    result: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        dep_type = item.get("dependency_type") or item.get("type")
        if dep_type not in {"blocks", "block", "blocking"}:
            continue
        identifier = item.get("depends_on_id") or item.get("id") or item.get("target_id")
        if identifier:
            result.append(str(identifier))
    return sorted(set(result))


class BeadsTaskStore:
    def __init__(self, project_root: Path, client: BeadsClient | None = None):
        self.project_root = project_root.resolve()
        self.client = client or BeadsClient(self.project_root)

    def _normalize(
        self,
        raw: dict[str, Any],
        *,
        ready_ids: set[str] | None = None,
        blocked_ids: set[str] | None = None,
    ) -> NormalizedTask:
        ready_ids = ready_ids or set()
        blocked_ids = blocked_ids or set()
        task_id = str(raw.get("id") or "")
        status_raw = str(raw.get("status") or "open").lower()
        notes: list[str] = []

        if status_raw in {"closed", "done", "completed"}:
            status = TaskStatus.DONE
        elif status_raw in {"in_progress", "in-progress", "running"}:
            status = TaskStatus.RUNNING
        elif status_raw in {"blocked"} or task_id in blocked_ids:
            status = TaskStatus.BLOCKED
        elif status_raw in {"deferred"}:
            status = TaskStatus.PLANNED
        elif task_id in ready_ids:
            status = TaskStatus.READY
        else:
            status = TaskStatus.PLANNED

        raw_priority = raw.get("priority", 2)
        try:
            beads_priority = int(raw_priority)
        except (TypeError, ValueError):
            beads_priority = 2
            notes.append(f"Unrecognized Beads priority {raw_priority!r}; normalized to medium.")
        priority = _BEADS_PRIORITY_TO_PROJECTCTL.get(beads_priority, 5)

        issue_type = str(raw.get("issue_type") or raw.get("type") or "task").lower()
        ttype = _task_type(issue_type)
        tags = [str(v) for v in (raw.get("labels") or []) if isinstance(v, (str, int, float))]
        milestone_labels = sorted({
            tag.split(":", 1)[1].strip()
            for tag in tags
            if tag.casefold().startswith("milestone:") and ":" in tag and tag.split(":", 1)[1].strip()
        })
        milestone = None
        if len(milestone_labels) == 1:
            milestone = milestone_labels[0]
        elif len(milestone_labels) > 1:
            notes.append(
                "Multiple explicit milestone labels found; milestone scoring disabled: "
                + ", ".join(milestone_labels)
            )
        if issue_type == "epic":
            tags.append("beads:epic")
            notes.append("Beads epic normalized with TaskType.UNKNOWN; epics are organizational work.")

        dependencies = _typed_blocking_ids(raw.get("dependencies"))
        blocks = _typed_blocking_ids(raw.get("dependents"))
        blocked_by = raw.get("blocked_by")
        if isinstance(blocked_by, list):
            for item in blocked_by:
                if isinstance(item, dict) and item.get("id"):
                    dependencies.append(str(item["id"]))
        dependencies = sorted(set(dependencies))

        return NormalizedTask(
            id=task_id,
            title=str(raw.get("title") or task_id),
            source=TaskSource(
                provider="beads",
                external_id=task_id,
                revision=str(raw.get("updated_at")) if raw.get("updated_at") else None,
                observed_at=utc_now(),
            ),
            type=ttype,
            status=status,
            priority=priority,
            milestone=milestone,
            created_at=_date(raw.get("created_at")),
            ready_since=None,
            due_at=_date(raw.get("due_at")),
            dependencies=dependencies,
            blocks=blocks,
            risk=RiskLevel.UNKNOWN,
            resource_class=ResourceClass.UNKNOWN,
            information_gain=0,
            human_decision_required=False,
            tags=sorted(set(tags)),
            normalization_notes=notes,
        )

    def get(self, task_id: str) -> NormalizedTask:
        raw = self.client.show(task_id)
        ready_raw = self.client.list_ready()
        blocked_raw = self.client.list_blocked()
        ready_ids = {str(x.get("id")) for x in ready_raw if x.get("id")}
        blocked_map = {str(x.get("id")): x for x in blocked_raw if x.get("id")}
        if task_id in blocked_map and blocked_map[task_id].get("blocked_by"):
            raw = {**raw, "blocked_by": blocked_map[task_id]["blocked_by"]}
        return self._normalize(raw, ready_ids=ready_ids, blocked_ids=set(blocked_map))

    def list_all(self) -> list[NormalizedTask]:
        raw_all = self.client.list_all()
        ready_raw = self.client.list_ready()
        blocked_raw = self.client.list_blocked()
        ready_ids = {str(x.get("id")) for x in ready_raw if x.get("id")}
        blocked_map = {str(x.get("id")): x for x in blocked_raw if x.get("id")}
        tasks = []
        for raw in raw_all:
            task_id = str(raw.get("id") or "")
            if task_id in blocked_map and blocked_map[task_id].get("blocked_by"):
                raw = {**raw, "blocked_by": blocked_map[task_id]["blocked_by"]}
            tasks.append(self._normalize(raw, ready_ids=ready_ids, blocked_ids=set(blocked_map)))

        # Derive reverse edges from known blocking dependencies so scheduler inputs can
        # compute unblock value without a second task-store-specific representation.
        by_id = {task.id: task for task in tasks}
        for task in tasks:
            for dependency in task.dependencies:
                if dependency in by_id and task.id not in by_id[dependency].blocks:
                    by_id[dependency].blocks.append(task.id)
                    by_id[dependency].blocks.sort()
        return sorted(tasks, key=lambda item: item.id)

    def list_ready(self) -> list[NormalizedTask]:
        tasks = [self._normalize(raw, ready_ids={str(raw.get("id"))}) for raw in self.client.list_ready()]
        return sorted(tasks, key=lambda item: item.id)

    def list_blocked(self) -> list[NormalizedTask]:
        tasks = [self._normalize(raw, blocked_ids={str(raw.get("id"))}) for raw in self.client.list_blocked()]
        return sorted(tasks, key=lambda item: item.id)

    def snapshot(self, *, tasks: list[NormalizedTask] | None = None) -> TaskSnapshot:
        tasks = sorted(tasks if tasks is not None else self.list_all(), key=lambda item: item.id)
        material = []
        for task in tasks:
            value = task.model_dump(mode="json")
            if isinstance(value.get("source"), dict):
                value["source"].pop("observed_at", None)
            material.append(value)
        content_revision = digest(material)
        version = self.client.version()
        source_revision = content_revision if not version else f"{content_revision};{version}"
        return TaskSnapshot(
            provider="beads",
            captured_at=utc_now(),
            source_revision=source_revision,
            tasks=tasks,
        )
