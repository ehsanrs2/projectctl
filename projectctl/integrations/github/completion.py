from __future__ import annotations

from pathlib import Path
from typing import Any

from projectctl.core.errors import TaskStoreError
from projectctl.integrations.github.client import GitHubIssuesClient
from projectctl.schemas.execution import EvidenceReference


COMPLETED_LABEL = "projectctl:completed"
NEEDS_DECISION_LABEL = "projectctl:needs-decision"


def _label_names(issue: dict[str, Any]) -> set[str]:
    result: set[str] = set()
    for item in issue.get("labels") or []:
        if isinstance(item, str):
            name = item
        elif isinstance(item, dict):
            name = item.get("name")
        else:
            name = None
        if name is not None and str(name).strip():
            result.add(str(name).strip().casefold())
    return result


class GitHubTaskCompletionWriter:
    """Additive GitHub task lifecycle writer.

    ProjectCTL deliberately does not PATCH the native issue state because the
    issue-update endpoint does not provide the compare-and-swap semantics needed
    to avoid overwriting a concurrent human close reason.
    """

    def __init__(
        self,
        project_root: Path,
        *,
        repository: str,
        client: GitHubIssuesClient | None = None,
    ):
        self.project_root = project_root.resolve()
        self.client = client or GitHubIssuesClient(
            self.project_root,
            repository=repository,
        )

    def complete(self, task_id: str, *, evidence: EvidenceReference) -> None:
        issue = self.client.show(task_id)
        state = str(issue.get("state") or "").casefold()
        state_reason = str(issue.get("state_reason") or "").casefold()
        if state == "closed":
            if state_reason == "completed":
                return
            raise TaskStoreError(
                f"GitHub task {task_id} was closed externally with "
                f"state_reason={state_reason or 'unknown'}; refusing to overwrite human intent."
            )

        self.client.ensure_label(
            COMPLETED_LABEL,
            color="0e8a16",
            description="ProjectCTL verified, published, and completed this task.",
        )
        updated = self.client.add_issue_labels(task_id, [COMPLETED_LABEL])

        updated_state = str(updated.get("state") or "").casefold()
        updated_reason = str(updated.get("state_reason") or "").casefold()
        if updated_state == "closed" and updated_reason != "completed":
            raise TaskStoreError(
                f"GitHub task {task_id} changed state during completion; "
                "refusing to reinterpret the external decision."
            )
        if COMPLETED_LABEL.casefold() not in _label_names(updated):
            raise TaskStoreError(
                f"GitHub task {task_id} does not contain the completion label after mutation."
            )

    def mark_needs_decision(self, task_id: str, *, reason: str) -> None:
        del reason
        issue = self.client.show(task_id)
        if str(issue.get("state") or "").casefold() == "closed":
            return

        self.client.ensure_label(
            NEEDS_DECISION_LABEL,
            color="fbca04",
            description="ProjectCTL stopped this task for explicit human review.",
        )
        updated = self.client.add_issue_labels(task_id, [NEEDS_DECISION_LABEL])
        if (
            str(updated.get("state") or "").casefold() != "closed"
            and NEEDS_DECISION_LABEL.casefold() not in _label_names(updated)
        ):
            raise TaskStoreError(
                f"GitHub task {task_id} does not contain the needs-decision label after mutation."
            )
