from __future__ import annotations

from pathlib import Path

from projectctl.integrations.beads.client import BeadsClient
from projectctl.schemas.execution import EvidenceReference


class BeadsTaskCompletionWriter:
    def __init__(self, project_root: Path, client: BeadsClient | None = None):
        self.project_root = project_root.resolve()
        self.client = client or BeadsClient(self.project_root)

    def complete(self, task_id: str, *, evidence: EvidenceReference) -> None:
        current = self.client.show(task_id)
        status = str(current.get("status") or "").lower()
        if status in {"closed", "done", "completed"}:
            return
        reason = (
            "ProjectCTL verified and integrated. "
            f"Evidence: {evidence.path} ({evidence.digest})"
        )
        self.client.close_issue(task_id, reason)

    def mark_needs_decision(self, task_id: str, *, reason: str) -> None:
        current = self.client.show(task_id)
        status = str(current.get("status") or "").lower()
        if status in {"closed", "done", "completed"}:
            return
        self.client.update_status(task_id, "blocked")
