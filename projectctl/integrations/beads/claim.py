from __future__ import annotations

from pathlib import Path

from projectctl.core.errors import ClaimConflictError, TaskStoreError
from projectctl.core.time import utc_now
from projectctl.integrations.beads.client import BeadsClient
from projectctl.core.digest import digest
from projectctl.schemas.task_claim import TaskClaim, TaskClaimRequest
from projectctl.schemas.task import NormalizedTask
from projectctl.core.enums import TaskStatus
from projectctl.scheduler.digests import semantic_task_payload


class BeadsTaskClaimer:
    def __init__(self, project_root: Path, client: BeadsClient | None = None):
        self.project_root = project_root.resolve()
        self.client = client or BeadsClient(self.project_root)

    def claim(self, request: TaskClaimRequest) -> TaskClaim:
        task_id = request.task_id
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
                return TaskClaim(
                    provider="beads",
                    task_id=task_id,
                    run_id=request.run_id,
                    actor=request.actor,
                    base_commit=request.base_commit,
                    integration_target_ref=request.integration_target_ref,
                    claim_token=request.claim_token,
                    request_digest=digest(request),
                    acquired=False,
                    observed_at=utc_now(),
                    reason=f"Task is not claimable (status={status or 'unknown'}, assignee={assignee or 'none'}).",
                )
            raise exc

        assignee = str(raw.get("assignee") or request.actor)
        return TaskClaim(
            provider="beads",
            task_id=task_id,
            run_id=request.run_id,
            actor=assignee,
            base_commit=request.base_commit,
            integration_target_ref=request.integration_target_ref,
            claim_token=request.claim_token,
            request_digest=digest(request),
            acquired=True,
            observed_at=utc_now(),
        )

    def reconcile(self, request: TaskClaimRequest) -> TaskClaim | None:
        # Pre-M3.0b2 Beads ownership is represented by task status/assignee, but
        # the provider does not expose a token that can prove it belongs to this
        # exact durable request. Do not guess ownership during crash recovery.
        del request
        return None

    def validate(self, claim: TaskClaim) -> bool:
        if not claim.acquired or claim.provider != "beads":
            return False
        current = self.client.show(claim.task_id)
        status = str(current.get("status") or "").lower()
        assignee = str(current.get("assignee") or "").strip()
        return status == "in_progress" and assignee == claim.actor

    def validate_transition(
        self,
        claim: TaskClaim,
        before: NormalizedTask,
        after: NormalizedTask,
    ) -> bool:
        if not self.validate(claim):
            return False
        if before.id != claim.task_id or after.id != claim.task_id:
            return False
        if before.status != TaskStatus.READY or after.status != TaskStatus.RUNNING:
            return False

        left = semantic_task_payload(before)
        right = semantic_task_payload(after)
        left["status"] = "<claim-transition>"
        right["status"] = "<claim-transition>"
        if isinstance(left.get("source"), dict):
            left["source"].pop("revision", None)
        if isinstance(right.get("source"), dict):
            right["source"].pop("revision", None)
        return left == right

    def release(self, claim: TaskClaim) -> None:
        if not claim.acquired:
            raise TaskStoreError("Cannot release a task claim that was not acquired.")
        if claim.provider != "beads":
            raise TaskStoreError(
                f"Beads claimer cannot release provider {claim.provider!r}."
            )
        if not self.validate(claim):
            raise ClaimConflictError(
                f"Beads task {claim.task_id} is no longer owned by this durable claim."
            )
        self.client.release_issue(claim.task_id)

    def release_legacy(self, task_id: str, *, actor: str) -> None:
        del actor
        self.client.release_issue(task_id)
