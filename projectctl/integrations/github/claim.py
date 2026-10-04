from __future__ import annotations

import json
from pathlib import Path

from projectctl.core.digest import digest
from projectctl.core.errors import TaskStoreError
from projectctl.core.time import utc_now
from projectctl.git.ref_lease import RemoteRefLease
from projectctl.integrations.github.repository import parse_github_repository
from projectctl.schemas.task_claim import TaskClaim, TaskClaimRequest


class GitHubTaskClaimer:
    """Concurrency-safe GitHub task claim backed by an exact remote Git ref lease."""

    def __init__(
        self,
        project_root: Path,
        *,
        repository: str,
        remote_name: str = "origin",
        lease: RemoteRefLease | None = None,
    ):
        self.project_root = project_root.resolve()
        self.repository = repository
        self.remote_name = remote_name
        self.lease = lease or RemoteRefLease(
            self.project_root,
            remote_name=remote_name,
        )

    @staticmethod
    def _issue_number(task_id: str) -> int:
        value = str(task_id).strip()
        if not value.startswith("gh-") or not value[3:].isdigit():
            raise TaskStoreError(
                f"GitHub task claims require normalized issue ids like 'gh-123'; got {task_id!r}."
            )
        number = int(value[3:])
        if number <= 0:
            raise TaskStoreError(f"Invalid GitHub issue task id: {task_id!r}")
        return number

    @staticmethod
    def _claim_ref(issue_number: int) -> str:
        return f"refs/heads/projectctl/claims/issue-{issue_number}"

    def _assert_remote_identity(self) -> None:
        observed = parse_github_repository(self.lease.remote_url())
        if observed != self.repository:
            raise TaskStoreError(
                "GitHub claim remote identity does not match task_store.repository: "
                f"remote={observed or 'non-github/unknown'}, configured={self.repository}."
            )

    @staticmethod
    def _marker_message(request: TaskClaimRequest) -> str:
        payload = {
            "schema": "projectctl.github_task_claim_marker.v1",
            "task_id": request.task_id,
            "run_id": request.run_id,
            "base_commit": request.base_commit,
            "integration_target_ref": request.integration_target_ref,
            "claim_token": request.claim_token,
            "requested_at": request.requested_at.isoformat(),
        }
        return (
            "ProjectCTL GitHub task claim\n\n"
            + json.dumps(payload, sort_keys=True, separators=(",", ":"))
        )

    def claim(self, request: TaskClaimRequest) -> TaskClaim:
        issue_number = self._issue_number(request.task_id)
        self._assert_remote_identity()

        remote_target = self.lease.remote_branch(request.integration_target_ref)
        if remote_target is None:
            raise TaskStoreError(
                f"Remote integration target {request.integration_target_ref!r} does not exist."
            )
        if remote_target != request.base_commit:
            raise TaskStoreError(
                "Remote integration target differs from the execution base; "
                f"remote={remote_target}, base={request.base_commit}."
            )

        claim_ref = self._claim_ref(issue_number)
        marker_sha = self.lease.create_marker_commit(
            base_commit=request.base_commit,
            message=self._marker_message(request),
            timestamp=request.requested_at,
        )

        current = self.lease.observe(claim_ref)
        if current == marker_sha:
            acquired = True
            reason = "Existing remote claim matches this exact claim request."
        elif current is not None:
            acquired = False
            reason = (
                f"Task is already claimed by remote ref {claim_ref} at {current}."
            )
        else:
            acquired = self.lease.acquire(
                ref=claim_ref,
                ownership_sha=marker_sha,
            )
            reason = None if acquired else (
                f"Task claim lost to another owner at {claim_ref}."
            )

        return TaskClaim(
            provider="github",
            task_id=request.task_id,
            run_id=request.run_id,
            actor=request.actor,
            base_commit=request.base_commit,
            integration_target_ref=request.integration_target_ref,
            claim_token=request.claim_token,
            request_digest=digest(request),
            acquired=acquired,
            observed_at=utc_now(),
            reason=reason,
            repository=self.repository,
            ownership_ref=claim_ref,
            ownership_sha=marker_sha,
        )

    def release(self, claim: TaskClaim) -> None:
        if not claim.acquired:
            raise TaskStoreError("Cannot release a task claim that was not acquired.")
        if claim.provider != "github":
            raise TaskStoreError(
                f"GitHub claimer cannot release provider {claim.provider!r}."
            )
        if claim.repository != self.repository:
            raise TaskStoreError(
                "GitHub claim repository does not match configured task authority."
            )
        if not claim.ownership_ref or not claim.ownership_sha:
            raise TaskStoreError(
                "GitHub task claim is missing remote ownership evidence."
            )

        self._assert_remote_identity()
        self.lease.release(
            ref=claim.ownership_ref,
            ownership_sha=claim.ownership_sha,
        )

    def release_legacy(self, task_id: str, *, actor: str) -> None:
        del task_id, actor
        raise TaskStoreError(
            "GitHub claims cannot be released without durable ownership evidence."
        )
