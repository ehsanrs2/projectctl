from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from projectctl.core.digest import digest
from projectctl.core.errors import TaskStoreError
from projectctl.integrations.linear.client import LinearIssuesClient
from projectctl.integrations.linear.lifecycle import (
    COMPLETED_COLOR,
    COMPLETED_LABEL,
    NEEDS_DECISION_COLOR,
    NEEDS_DECISION_LABEL,
)
from projectctl.schemas.delivery import PublicationManifest
from projectctl.schemas.evidence import EvidenceManifest
from projectctl.schemas.execution import EvidenceReference


_TERMINAL = {"completed", "canceled"}
_NON_BLOCKING_RELATIONS = {"related", "duplicate", "similar"}


class LinearTaskCompletionWriter:
    """Additive Linear lifecycle writer.

    ProjectCTL never moves the native Linear workflow state. Lifecycle state is
    represented with team-scoped reserved labels added through Linear's
    additive label mutation. This avoids replacing human labels or overwriting
    a concurrent human workflow transition.
    """

    def __init__(
        self,
        project_root: Path,
        *,
        team_id: str,
        client: LinearIssuesClient | None = None,
    ):
        self.project_root = project_root.resolve()
        self.client = client or LinearIssuesClient(
            self.project_root,
            team_id=team_id,
        )

    @staticmethod
    def _identifier(task_id: str) -> str:
        value = str(task_id).strip()
        if not value.startswith("lin-") or len(value) <= 4:
            raise TaskStoreError(
                f"Linear task id must use the normalized lin-<identifier> form: {task_id!r}."
            )
        return value[4:]

    @staticmethod
    def _state_type(issue: dict[str, Any]) -> str:
        state = issue.get("state")
        return (
            str(state.get("type") or "").strip().casefold()
            if isinstance(state, dict)
            else ""
        )

    @staticmethod
    def _label_ids(issue: dict[str, Any]) -> set[str]:
        values = issue.get("labelIds")
        if not isinstance(values, list):
            raise TaskStoreError("Linear issue response is missing labelIds.")
        return {str(value) for value in values if str(value).strip()}

    def _validate_evidence(self, evidence: EvidenceReference) -> None:
        path = (self.project_root / evidence.path).resolve()
        if not path.is_relative_to(self.project_root) or not path.exists():
            raise TaskStoreError(
                "Linear completion requires durable ProjectCTL evidence inside the project."
            )
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise TaskStoreError(
                f"Linear completion evidence is invalid JSON: {exc}"
            ) from exc
        if not isinstance(payload, dict):
            raise TaskStoreError(
                "Linear completion evidence must be a JSON object."
            )

        schema_kind = str(payload.get("schema_kind") or "").strip()
        try:
            if schema_kind == "projectctl.evidence_manifest":
                manifest = EvidenceManifest.model_validate(payload)
                if not manifest.overall_pass:
                    raise TaskStoreError(
                        "Linear completion requires passing verification evidence."
                    )
            elif schema_kind == "projectctl.publication_manifest":
                manifest = PublicationManifest.model_validate(payload)
                if (
                    not manifest.published
                    or manifest.remote_after != manifest.candidate_commit
                ):
                    raise TaskStoreError(
                        "Linear completion requires proof that the exact candidate "
                        "is visible on the configured publication target."
                    )
            else:
                raise TaskStoreError(
                    f"Unsupported Linear completion evidence kind: "
                    f"{schema_kind or 'missing'}."
                )
        except TaskStoreError:
            raise
        except Exception as exc:
            raise TaskStoreError(
                f"Linear completion evidence contract is invalid: {exc}"
            ) from exc

        if digest(manifest) != evidence.digest:
            raise TaskStoreError(
                "Linear completion evidence digest does not match the durable artifact."
            )

    def _assert_completion_safe(self, issue: dict[str, Any]) -> None:
        issue_id = str(issue.get("id") or "").strip()
        if not issue_id:
            raise TaskStoreError("Linear issue is missing its stable id.")

        state_type = self._state_type(issue)
        if state_type == "canceled":
            raise TaskStoreError(
                "Linear task was canceled by the task authority; refusing completion."
            )
        if not state_type:
            raise TaskStoreError(
                "Linear task is missing workflow state; completion is ambiguous."
            )

        for relation in self.client.list_inverse_relations(issue_id):
            relation_type = str(relation.get("type") or "").strip().casefold()
            if relation_type in _NON_BLOCKING_RELATIONS:
                continue
            if relation_type != "blocks":
                raise TaskStoreError(
                    "Linear task has an unknown incoming relation; completion is ambiguous."
                )

            target = relation.get("relatedIssue")
            blocker = relation.get("issue")
            if not isinstance(target, dict) or not isinstance(blocker, dict):
                raise TaskStoreError(
                    "Linear blocks relation is missing source/target metadata."
                )
            target_id = str(target.get("id") or "").strip()
            target_team = target.get("team")
            target_team_id = (
                str(target_team.get("id") or "").strip()
                if isinstance(target_team, dict)
                else ""
            )
            if target_id != issue_id or target_team_id != self.client.team_id:
                raise TaskStoreError(
                    "Linear blocks relation direction/team changed during completion."
                )

            blocker_state = blocker.get("state")
            blocker_state_type = (
                str(blocker_state.get("type") or "").strip().casefold()
                if isinstance(blocker_state, dict)
                else ""
            )
            if not blocker_state_type:
                raise TaskStoreError(
                    "Linear blocker is missing workflow state during completion."
                )
            if blocker_state_type not in _TERMINAL:
                blocker_id = str(blocker.get("identifier") or blocker.get("id") or "unknown")
                raise TaskStoreError(
                    f"Linear task has unresolved blocker {blocker_id!r}; refusing completion."
                )

    def _decision_label(self) -> dict[str, Any]:
        return self.client.ensure_team_label(
            NEEDS_DECISION_LABEL,
            color=NEEDS_DECISION_COLOR,
            description="ProjectCTL stopped this task for explicit human review.",
        )

    def _completed_label(self) -> dict[str, Any]:
        return self.client.ensure_team_label(
            COMPLETED_LABEL,
            color=COMPLETED_COLOR,
            description="ProjectCTL independently verified and completed this task.",
        )

    def complete(self, task_id: str, *, evidence: EvidenceReference) -> None:
        identifier = self._identifier(task_id)
        issue = self.client.show(identifier)
        state_type = self._state_type(issue)
        if state_type == "completed":
            return
        if state_type == "canceled":
            raise TaskStoreError(
                f"Linear task {task_id} was canceled externally; refusing to overwrite human intent."
            )

        self._validate_evidence(evidence)
        self._assert_completion_safe(issue)

        issue_id = str(issue.get("id") or "").strip()
        decision = self._decision_label()
        decision_id = str(decision.get("id") or "").strip()
        completed = self._completed_label()
        completed_id = str(completed.get("id") or "").strip()
        if not decision_id or not completed_id:
            raise TaskStoreError("Linear lifecycle labels are missing stable ids.")

        # Fail-closed two-phase marker protocol:
        # 1. add needs-decision guard;
        # 2. add completed marker;
        # 3. revalidate current provider state/relations;
        # 4. remove guard only after success.
        #
        # Any crash before step 4 leaves either needs-decision alone or both
        # ProjectCTL markers. Both shapes normalize to NEEDS_DECISION.
        guarded = self.client.add_issue_label(issue_id, decision_id)
        if decision_id not in self._label_ids(guarded):
            raise TaskStoreError(
                f"Linear task {task_id} does not contain the completion guard."
            )

        try:
            staged = self.client.add_issue_label(issue_id, completed_id)
            staged_ids = self._label_ids(staged)
            if completed_id not in staged_ids or decision_id not in staged_ids:
                raise TaskStoreError(
                    "Linear completion staging did not preserve both ProjectCTL markers."
                )

            current = self.client.show(issue_id)
            current_ids = self._label_ids(current)
            if completed_id not in current_ids or decision_id not in current_ids:
                raise TaskStoreError(
                    "Linear lifecycle markers changed concurrently during completion."
                )
            self._assert_completion_safe(current)

            final = self.client.remove_issue_label(issue_id, decision_id)
            final_ids = self._label_ids(final)
            if completed_id not in final_ids or decision_id in final_ids:
                raise TaskStoreError(
                    "Linear completion could not prove the final marker state."
                )
            if self._state_type(final) == "canceled":
                raise TaskStoreError(
                    f"Linear task {task_id} was canceled during completion."
                )
        except Exception:
            # Do not remove the needs-decision guard on any failure. If the
            # completed label was already added, both markers intentionally
            # remain and normalize to NEEDS_DECISION for deterministic recovery.
            raise

    def mark_needs_decision(self, task_id: str, *, reason: str) -> None:
        del reason
        identifier = self._identifier(task_id)
        issue = self.client.show(identifier)
        if self._state_type(issue) in _TERMINAL:
            return

        decision = self._decision_label()
        decision_id = str(decision.get("id") or "").strip()
        if not decision_id:
            raise TaskStoreError("Linear needs-decision label has no stable id.")

        issue_id = str(issue.get("id") or "").strip()
        updated = self.client.add_issue_label(issue_id, decision_id)
        if (
            self._state_type(updated) not in _TERMINAL
            and decision_id not in self._label_ids(updated)
        ):
            raise TaskStoreError(
                f"Linear task {task_id} does not contain the needs-decision marker."
            )
