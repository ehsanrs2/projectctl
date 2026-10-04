from __future__ import annotations

from pathlib import Path

from projectctl.core.errors import TaskStoreError
from projectctl.core.time import utc_now
from projectctl.integrations.beads.client import BeadsClient
from projectctl.core.digest import digest
from projectctl.schemas.task_claim import TaskClaim, TaskClaimRequest


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

        assignee = str(raw.get("assignee") or actor)
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

    def release(self, claim: TaskClaim) -> None:
        if not claim.acquired:
            raise TaskStoreError("Cannot release a task claim that was not acquired.")
        if claim.provider != "beads":
            raise TaskStoreError(
                f"Beads claimer cannot release provider {claim.provider!r}."
            )
        self.client.release_issue(claim.task_id)
