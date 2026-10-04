from __future__ import annotations

from typing import Any

from projectctl.core.digest import digest
from projectctl.core.enums import ResourceClass, RiskLevel, TaskStatus, TaskType
from projectctl.core.time import utc_now
from projectctl.integrations.linear.client import LinearIssuesClient
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


class LinearIssuesTaskStore:
    """Read-only Linear task authority for M3.2a.

    M3.2a intentionally withholds READY eligibility for non-terminal Linear
    issues. Dependency/sub-issue semantics and mutation ownership have not yet
    been proven, so autonomous execution remains fail-closed.
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
    def _state(raw: dict[str, Any]) -> tuple[TaskStatus, bool, list[str]]:
        notes: list[str] = []
        state = raw.get("state")
        if not isinstance(state, dict):
            return (
                TaskStatus.NEEDS_DECISION,
                True,
                ["Linear issue is missing workflow state metadata."],
            )

        state_type = str(state.get("type") or "").strip().casefold()
        state_name = str(state.get("name") or "").strip() or "unknown"

        if state_type == "completed":
            return TaskStatus.DONE, False, notes
        if state_type == "canceled":
            return TaskStatus.CANCELLED, False, notes
        if state_type == "started":
            notes.append(
                f"Linear workflow state {state_name!r} is already started; "
                "ProjectCTL observes it as running but does not own it."
            )
            return TaskStatus.RUNNING, False, notes
        if state_type in {"backlog", "unstarted"}:
            notes.append(
                "M3.2a is read-only: Linear dependency and mutation semantics "
                "are not yet proven, so this issue is PLANNED rather than READY."
            )
            return TaskStatus.PLANNED, False, notes

        notes.append(
            f"Unknown Linear workflow state type {state_type or 'missing'!r}; "
            "human normalization is required."
        )
        return TaskStatus.NEEDS_DECISION, True, notes

    @staticmethod
    def _task_id(identifier: str) -> str:
        return f"lin-{identifier}"

    def _normalize(self, raw: dict[str, Any]) -> NormalizedTask:
        external_id = str(raw.get("id") or "").strip()
        identifier = str(raw.get("identifier") or "").strip()
        title = str(raw.get("title") or "").strip()

        if not external_id:
            raise ValueError("Linear issue payload is missing its stable id.")
        if not identifier:
            raise ValueError("Linear issue payload is missing its identifier.")
        if not title:
            title = identifier

        status, human_decision, notes = self._state(raw)

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
            tags=([f"linear-state:{state_name}"] if state_name else []),
            normalization_notes=notes,
        )

    def _build_tasks(self) -> list[NormalizedTask]:
        values = [self._normalize(raw) for raw in self.client.list_all()]
        return sorted(values, key=lambda task: task.id.casefold())

    def get(self, task_id: str) -> NormalizedTask:
        for task in self._build_tasks():
            if task.id == task_id:
                return task
        raise ValueError(f"Linear task {task_id!r} is not present in the authority snapshot.")

    def list_all(self) -> list[NormalizedTask]:
        return self._build_tasks()

    def list_ready(self) -> list[NormalizedTask]:
        # Deliberately empty until Linear dependency and claim/write semantics
        # are proven in later M3.2 milestones.
        return []

    def list_blocked(self) -> list[NormalizedTask]:
        return [
            task
            for task in self._build_tasks()
            if task.status == TaskStatus.NEEDS_DECISION
            or task.human_decision_required
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
