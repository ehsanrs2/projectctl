from __future__ import annotations

from pathlib import Path

from projectctl.core.errors import TaskStoreError
from projectctl.core.time import utc_now
from projectctl.integrations.beads.client import BeadsClient
from projectctl.schemas.execution import ClaimResult


class BeadsTaskClaimer:
    def __init__(self, project_root: Path, client: BeadsClient | None = None):
        self.project_root = project_root.resolve()
        self.client = client or BeadsClient(self.project_root)

    def claim(self, task_id: str, *, actor: str) -> ClaimResult:
        try:
            raw = self.client.claim_issue(task_id)
        except TaskStoreError as exc:
            # Distinguish an expected CAS/claim loss from provider failure without
            # relying on Beads error text.
            try:
                current = self.client.show(task_id)
            except TaskStoreError:
                raise exc
            status = str(current.get("status") or "").lower()
            assignee = str(current.get("assignee") or "").strip()
            if status != "open" or assignee:
                return ClaimResult(
                    task_id=task_id,
                    actor=actor,
                    claimed=False,
                    observed_at=utc_now(),
                    reason=f"Task is not claimable (status={status or 'unknown'}, assignee={assignee or 'none'}).",
                )
            raise exc

        assignee = str(raw.get("assignee") or actor)
        return ClaimResult(
            task_id=task_id,
            actor=assignee,
            claimed=True,
            observed_at=utc_now(),
        )

    def release(self, task_id: str, *, actor: str) -> None:
        self.client.release_issue(task_id)
