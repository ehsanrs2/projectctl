from __future__ import annotations

from projectctl.core.digest import digest
from projectctl.schemas.task import TaskSnapshot


def semantic_task_snapshot_digest(snapshot: TaskSnapshot) -> str:
    tasks = []
    for task in sorted(snapshot.tasks, key=lambda item: item.id):
        raw = task.model_dump(mode="json", exclude_none=False)
        if isinstance(raw.get("source"), dict):
            raw["source"].pop("observed_at", None)
        # Team metadata is audit/explanation context in M3.1b. It does not
        # affect eligibility, scoring, claim ownership, or execution policy.
        raw.pop("team", None)
        tasks.append(raw)
    return digest({"provider": snapshot.provider, "source_revision": snapshot.source_revision, "tasks": tasks})
