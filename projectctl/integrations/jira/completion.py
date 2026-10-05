from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from projectctl.core.digest import digest
from projectctl.core.enums import TaskStatus
from projectctl.core.errors import TaskStoreError
from projectctl.core.time import utc_now
from projectctl.integrations.jira.client import (
    JIRA_LIFECYCLE_PROPERTY,
    JiraCloudClient,
)
from projectctl.integrations.jira.task_store import JiraIssuesTaskStore
from projectctl.schemas.config import JiraWorkflowPolicy
from projectctl.schemas.delivery import PublicationManifest, ReviewReceipt
from projectctl.schemas.evidence import EvidenceManifest
from projectctl.schemas.execution import EvidenceReference
from projectctl.schemas.jira_lifecycle import JiraLifecycleMarker


class JiraTaskCompletionWriter:
    """CAS-backed additive Jira lifecycle writer.

    ProjectCTL never transitions native Jira workflow state. A dedicated issue
    property stores only ProjectCTL lifecycle state. Mutations use Jira's bulk
    issue-property filter with currentValue/hasProperty and are verified by
    read-back, so an unexpected human/app property change is never overwritten.
    """

    def __init__(
        self,
        project_root: Path,
        *,
        site: str,
        project_key: str,
        policy: JiraWorkflowPolicy,
        client: JiraCloudClient | None = None,
    ):
        self.project_root = project_root.resolve()
        self.client = client or JiraCloudClient(
            self.project_root,
            site=site,
            project_key=project_key,
        )
        self.policy = policy
        self.store = JiraIssuesTaskStore(
            self.project_root,
            site=site,
            project_key=project_key,
            policy=policy,
            client=self.client,
            lifecycle_enabled=False,
        )

    @staticmethod
    def _issue_key(task_id: str) -> str:
        value = str(task_id).strip()
        if not value.startswith("jira-") or len(value) <= 5:
            raise TaskStoreError(
                f"Jira task id must use normalized jira-<issue-key> form: {task_id!r}."
            )
        return value[5:].upper()

    def _validate_evidence(
        self,
        task_id: str,
        evidence: EvidenceReference,
    ) -> Any:
        path = (self.project_root / evidence.path).resolve()
        if not path.is_relative_to(self.project_root) or not path.exists():
            raise TaskStoreError(
                "Jira completion requires durable ProjectCTL evidence inside the project."
            )
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise TaskStoreError(
                f"Jira completion evidence is invalid JSON: {exc}"
            ) from exc
        if not isinstance(payload, dict):
            raise TaskStoreError("Jira completion evidence must be a JSON object.")

        schema_kind = str(payload.get("schema_kind") or "").strip()
        try:
            if schema_kind == "projectctl.evidence_manifest":
                manifest = EvidenceManifest.model_validate(payload)
                if not manifest.overall_pass:
                    raise TaskStoreError(
                        "Jira completion requires passing verification evidence."
                    )
            elif schema_kind == "projectctl.publication_manifest":
                manifest = PublicationManifest.model_validate(payload)
                if (
                    not manifest.published
                    or manifest.remote_after != manifest.candidate_commit
                ):
                    raise TaskStoreError(
                        "Jira completion requires exact-candidate publication proof."
                    )
            elif schema_kind == "projectctl.review_receipt":
                manifest = ReviewReceipt.model_validate(payload)
                if (
                    not manifest.delivery_complete
                    or manifest.state != "merged"
                    or manifest.head_commit != manifest.candidate_commit
                ):
                    raise TaskStoreError(
                        "Jira completion requires merged exact-candidate review proof."
                    )
            else:
                raise TaskStoreError(
                    f"Unsupported Jira completion evidence kind: "
                    f"{schema_kind or 'missing'}."
                )
        except TaskStoreError:
            raise
        except Exception as exc:
            raise TaskStoreError(
                f"Jira completion evidence contract is invalid: {exc}"
            ) from exc

        if getattr(manifest, "task_id", None) != task_id:
            raise TaskStoreError(
                "Jira completion evidence task_id does not match the task."
            )
        if digest(manifest) != evidence.digest:
            raise TaskStoreError(
                "Jira completion evidence digest does not match the durable artifact."
            )
        return manifest

    def _current_task(self, task_id: str):
        task = self.store.get(task_id)
        if task.status == TaskStatus.CANCELLED:
            raise TaskStoreError(
                f"Jira task {task_id} was canceled externally; refusing completion."
            )
        if task.status == TaskStatus.DONE:
            return task
        if task.human_decision_required:
            raise TaskStoreError(
                f"Jira task {task_id} requires human decision; refusing completion."
            )
        if task.dependencies:
            raise TaskStoreError(
                f"Jira task {task_id} has unresolved dependencies; refusing completion."
            )
        return task

    def _read_marker(self, issue_key: str) -> JiraLifecycleMarker | None:
        value = self.client.get_issue_property(
            issue_key,
            JIRA_LIFECYCLE_PROPERTY,
        )
        if value is None:
            return None
        try:
            return JiraLifecycleMarker.model_validate(value)
        except Exception as exc:
            raise TaskStoreError(
                "Jira ProjectCTL lifecycle property is malformed or foreign; "
                "refusing to overwrite it."
            ) from exc

    def _cas(
        self,
        issue_id: str,
        *,
        expected: JiraLifecycleMarker | None,
        desired: JiraLifecycleMarker,
    ) -> None:
        changed = self.client.compare_and_set_issue_property(
            issue_id,
            JIRA_LIFECYCLE_PROPERTY,
            expected=(
                expected.model_dump(mode="json")
                if expected is not None
                else None
            ),
            desired=desired.model_dump(mode="json"),
        )
        if not changed:
            raise TaskStoreError(
                "Jira lifecycle property changed concurrently; refusing overwrite."
            )

    @staticmethod
    def _marker(
        *,
        task_id: str,
        issue_id: str,
        state: str,
        generation: int,
        run_id: str | None = None,
        evidence: EvidenceReference | None = None,
    ) -> JiraLifecycleMarker:
        return JiraLifecycleMarker(
            task_id=task_id,
            issue_id=issue_id,
            state=state,
            generation=generation,
            run_id=run_id,
            evidence_path=evidence.path if evidence is not None else None,
            evidence_digest=evidence.digest if evidence is not None else None,
            updated_at=utc_now(),
        )

    def complete(self, task_id: str, *, evidence: EvidenceReference) -> None:
        issue_key = self._issue_key(task_id)
        manifest = self._validate_evidence(task_id, evidence)
        task = self._current_task(task_id)
        if task.status == TaskStatus.DONE:
            return

        issue = self.client.show(issue_key)
        issue_id = str(issue.get("id") or "").strip()
        if not issue_id:
            raise TaskStoreError("Jira issue is missing its stable id.")

        current = self._read_marker(issue_key)
        if current is not None:
            if current.task_id != task_id or current.issue_id != issue_id:
                raise TaskStoreError(
                    "Jira lifecycle marker identity differs from the current task."
                )
            if current.state == "completed":
                if (
                    current.run_id == getattr(manifest, "run_id", None)
                    and current.evidence_digest == evidence.digest
                    and current.evidence_path == evidence.path
                ):
                    return
                raise TaskStoreError(
                    "Jira task already contains a different completion marker."
                )
            if current.state == "needs_decision":
                raise TaskStoreError(
                    "Jira task is durably marked needs-decision; refusing completion."
                )
            if (
                current.run_id != getattr(manifest, "run_id", None)
                or current.evidence_digest != evidence.digest
                or current.evidence_path != evidence.path
            ):
                raise TaskStoreError(
                    "Jira completion-pending marker belongs to different evidence."
                )
            pending = current
        else:
            pending = self._marker(
                task_id=task_id,
                issue_id=issue_id,
                state="completion_pending",
                generation=1,
                run_id=getattr(manifest, "run_id", None),
                evidence=evidence,
            )
            self._cas(issue_id, expected=None, desired=pending)

        # Re-read provider truth after the durable guard exists. A crash before
        # this point leaves completion_pending, which normalizes fail-closed.
        self._current_task(task_id)

        completed = self._marker(
            task_id=task_id,
            issue_id=issue_id,
            state="completed",
            generation=pending.generation + 1,
            run_id=getattr(manifest, "run_id", None),
            evidence=evidence,
        )
        self._cas(issue_id, expected=pending, desired=completed)

        observed = self._read_marker(issue_key)
        if observed != completed:
            raise TaskStoreError(
                "Jira completion marker could not be proven after CAS."
            )

    def mark_needs_decision(self, task_id: str, *, reason: str) -> None:
        del reason
        issue_key = self._issue_key(task_id)
        issue = self.client.show(issue_key)
        fields = issue.get("fields")
        status = fields.get("status") if isinstance(fields, dict) else None
        category = (
            status.get("statusCategory")
            if isinstance(status, dict)
            else None
        )
        category_key = (
            str(category.get("key") or "").strip().casefold()
            if isinstance(category, dict)
            else ""
        )
        if category_key in {"done", "completed"}:
            return

        issue_id = str(issue.get("id") or "").strip()
        if not issue_id:
            raise TaskStoreError("Jira issue is missing its stable id.")

        current = self._read_marker(issue_key)
        if current is not None:
            if current.task_id != task_id or current.issue_id != issue_id:
                raise TaskStoreError(
                    "Jira lifecycle marker identity differs from the current task."
                )
            if current.state in {"needs_decision", "completed"}:
                return
            generation = current.generation + 1
        else:
            generation = 1

        desired = self._marker(
            task_id=task_id,
            issue_id=issue_id,
            state="needs_decision",
            generation=generation,
        )
        self._cas(issue_id, expected=current, desired=desired)
        observed = self._read_marker(issue_key)
        if observed != desired:
            raise TaskStoreError(
                "Jira needs-decision marker could not be proven after CAS."
            )
