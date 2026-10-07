from __future__ import annotations

from projectctl.core.digest import digest
from projectctl.schemas.task import NormalizedTask, TaskSnapshot


def _semantic_task_payload(task: NormalizedTask) -> dict:
    raw = task.model_dump(mode="json", exclude_none=False)
    if isinstance(raw.get("source"), dict):
        raw["source"].pop("observed_at", None)
    # Team metadata is audit/explanation context. It does not affect
    # eligibility, scoring, claim ownership, or execution policy.
    raw.pop("team", None)
    return raw


def semantic_task_digest(task: NormalizedTask) -> str:
    return digest(_semantic_task_payload(task))


def semantic_task_snapshot_digest(snapshot: TaskSnapshot) -> str:
    tasks = [
        _semantic_task_payload(task)
        for task in sorted(snapshot.tasks, key=lambda item: item.id)
    ]
    return digest(
        {
            "provider": snapshot.provider,
            "source_revision": snapshot.source_revision,
            "tasks": tasks,
        }
    )


def semantic_task_scope_digest(
    snapshot: TaskSnapshot,
    task_id: str,
) -> tuple[str, list[str]]:
    """Digest one task plus all locally represented transitive dependencies.

    Unrelated task lifecycle movement must not invalidate a scoped parallel plan.
    External dependency identities remain represented inside the selected/local
    task payloads and therefore still affect the digest when normalization changes.
    """
    by_id = {task.id: task for task in snapshot.tasks}
    if task_id not in by_id:
        raise ValueError(f"Task {task_id!r} is not present in the task snapshot.")

    included: set[str] = set()
    pending = [task_id]
    while pending:
        current = pending.pop()
        if current in included:
            continue
        task = by_id.get(current)
        if task is None:
            continue
        included.add(current)
        for dependency in task.dependencies:
            if dependency in by_id and dependency not in included:
                pending.append(dependency)

    ordered = sorted(included)
    payload = {
        "provider": snapshot.provider,
        "tasks": [_semantic_task_payload(by_id[item]) for item in ordered],
    }
    return digest(payload), ordered
