from __future__ import annotations

import json
import re
from pathlib import Path

from projectctl.core.digest import digest
from projectctl.core.errors import TaskStoreError
from projectctl.core.time import utc_now
from projectctl.git.ref_lease import RemoteRefLease
from projectctl.git.remote import normalize_git_remote_identity
from projectctl.schemas.task_claim import TaskClaim, TaskClaimRequest
from projectctl.schemas.task import NormalizedTask
from projectctl.scheduler.digests import semantic_task_digest


_SAFE = re.compile(r"[^a-zA-Z0-9._-]+")


class GitRemoteTaskClaimer:
    """Task-provider-neutral ownership backed by an exact remote Git ref lease."""

    def __init__(
        self,
        project_root: Path,
        *,
        provider: str,
        remote_name: str,
        remote_identity: str,
        lease: RemoteRefLease | None = None,
    ):
        self.project_root = project_root.resolve()
        self.provider = provider
        self.remote_name = remote_name
        self.remote_identity = remote_identity
        self.lease = lease or RemoteRefLease(
            self.project_root,
            remote_name=remote_name,
        )

    def _claim_ref(self, task_id: str) -> str:
        # Preserve the historical GitHub claim namespace for compatibility.
        if self.provider == "github" and task_id.startswith("gh-") and task_id[3:].isdigit():
            return f"refs/heads/projectctl/claims/issue-{int(task_id[3:])}"

        slug = _SAFE.sub("-", task_id).strip("-._")[:48] or "task"
        suffix = digest({"provider": self.provider, "task_id": task_id})[:12]
        return f"refs/heads/projectctl/claims/{self.provider}/{slug}-{suffix}"

    def _assert_remote_identity(self) -> None:
        observed = normalize_git_remote_identity(self.lease.remote_url())
        if observed != self.remote_identity:
            raise TaskStoreError(
                "Git claim remote identity does not match code_transport.remote_identity: "
                f"remote={observed or 'unknown'}, configured={self.remote_identity}."
            )

    def _marker_message(self, request: TaskClaimRequest) -> str:
        payload = {
            "schema": "projectctl.git_task_claim_marker.v1",
            "task_provider": self.provider,
            "task_id": request.task_id,
            "run_id": request.run_id,
            "base_commit": request.base_commit,
            "integration_target_ref": request.integration_target_ref,
            "claim_token": request.claim_token,
            "requested_at": request.requested_at.isoformat(),
        }
        return (
            "ProjectCTL Git task claim\n\n"
            + json.dumps(payload, sort_keys=True, separators=(",", ":"))
        )

    def _marker_sha(self, request: TaskClaimRequest) -> str:
        return self.lease.create_marker_commit(
            base_commit=request.base_commit,
            message=self._marker_message(request),
            timestamp=request.requested_at,
        )

    def claim(self, request: TaskClaimRequest) -> TaskClaim:
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

        claim_ref = self._claim_ref(request.task_id)
        marker_sha = self._marker_sha(request)
        current = self.lease.observe(claim_ref)

        if current == marker_sha:
            acquired = True
            reason = "Existing remote claim matches this exact claim request."
        elif current is not None:
            acquired = False
            reason = f"Task is already claimed by remote ref {claim_ref} at {current}."
        else:
            acquired = self.lease.acquire(ref=claim_ref, ownership_sha=marker_sha)
            reason = None if acquired else f"Task claim lost to another owner at {claim_ref}."

        return TaskClaim(
            provider=self.provider,
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
            repository=self.remote_identity,
            ownership_ref=claim_ref,
            ownership_sha=marker_sha,
        )

    def reconcile(self, request: TaskClaimRequest) -> TaskClaim:
        self._assert_remote_identity()
        claim_ref = self._claim_ref(request.task_id)
        marker_sha = self._marker_sha(request)
        current = self.lease.observe(claim_ref)
        acquired = current == marker_sha
        reason = (
            "Remote claim matches the durable claim request."
            if acquired
            else (
                "Durable claim request exists but no remote claim ref is present."
                if current is None
                else "Remote claim ref is owned by a different marker."
            )
        )
        return TaskClaim(
            provider=self.provider,
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
            repository=self.remote_identity,
            ownership_ref=claim_ref,
            ownership_sha=marker_sha,
        )

    def validate(self, claim: TaskClaim) -> bool:
        if (
            not claim.acquired
            or claim.provider != self.provider
            or claim.repository != self.remote_identity
            or not claim.ownership_ref
            or not claim.ownership_sha
        ):
            return False
        self._assert_remote_identity()
        return self.lease.observe(claim.ownership_ref) == claim.ownership_sha

    def validate_transition(
        self,
        before: NormalizedTask,
        after: NormalizedTask,
        claim: TaskClaim,
    ) -> bool:
        return (
            claim.acquired
            and before.id == claim.task_id
            and after.id == claim.task_id
            and before.source.provider == after.source.provider == claim.provider
            and semantic_task_digest(before) == semantic_task_digest(after)
        )

    def release(self, claim: TaskClaim) -> None:
        if not claim.acquired:
            raise TaskStoreError("Cannot release a task claim that was not acquired.")
        if claim.provider != self.provider:
            raise TaskStoreError(
                f"Git remote claimer for {self.provider!r} cannot release "
                f"provider {claim.provider!r}."
            )
        if claim.repository != self.remote_identity:
            raise TaskStoreError("Git claim remote identity changed.")
        if not claim.ownership_ref or not claim.ownership_sha:
            raise TaskStoreError("Git remote task claim is missing ownership evidence.")

        self._assert_remote_identity()
        self.lease.release(
            ref=claim.ownership_ref,
            ownership_sha=claim.ownership_sha,
        )

    def release_legacy(self, task_id: str, *, actor: str) -> None:
        del task_id, actor
        raise TaskStoreError(
            "Git remote claims cannot be released without durable ownership evidence."
        )
