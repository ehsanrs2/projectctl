from __future__ import annotations

import json
from pathlib import Path

from projectctl.core.digest import digest
from projectctl.core.errors import ClaimConflictError, TaskStoreError
from projectctl.core.time import utc_now
from projectctl.project.locking import project_lock
from projectctl.schemas.task_claim import TaskClaim, TaskClaimRequest


class LocalTaskClaimer:
    """Project-local exact ownership for installations without a Git remote.

    This protects concurrent ProjectCTL processes sharing the same project
    filesystem. It is intentionally not described as a cross-machine or
    internet-distributed lock.
    """

    def __init__(self, project_root: Path, *, provider: str):
        self.project_root = project_root.resolve()
        self.provider = provider

    def _relative_ref(self, task_id: str) -> str:
        key = digest({"provider": self.provider, "task_id": task_id})[:32]
        return f".projectctl/locks/task-claims/{key}.json"

    def _path(self, task_id: str) -> Path:
        return self.project_root / self._relative_ref(task_id)

    def _record(self, request: TaskClaimRequest) -> dict[str, str]:
        return {
            "schema": "projectctl.local_task_claim_marker.v1",
            "provider": self.provider,
            "task_id": request.task_id,
            "run_id": request.run_id,
            "claim_token": request.claim_token,
            "request_digest": digest(request),
        }

    @staticmethod
    def _read(path: Path) -> dict | None:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except Exception as exc:
            raise TaskStoreError(f"Local task claim marker is unreadable: {exc}") from exc
        if not isinstance(value, dict):
            raise TaskStoreError("Local task claim marker must be a JSON object.")
        return value

    def claim(self, request: TaskClaimRequest) -> TaskClaim:
        path = self._path(request.task_id)
        expected = self._record(request)
        expected_digest = digest(expected)
        path.parent.mkdir(parents=True, exist_ok=True)

        with project_lock(self.project_root, "local-task-claim-op"):
            current = self._read(path)
            if current is None:
                payload = json.dumps(expected, sort_keys=True, separators=(",", ":")) + "\n"
                fd = path.open("x", encoding="utf-8")
                try:
                    fd.write(payload)
                    fd.flush()
                finally:
                    fd.close()
                acquired = True
                reason = None
            elif digest(current) == expected_digest:
                acquired = True
                reason = "Existing local claim matches this exact claim request."
            else:
                acquired = False
                reason = "Task is already claimed by another local ProjectCTL run."

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
            repository=None,
            ownership_ref=self._relative_ref(request.task_id),
            ownership_sha=expected_digest,
        )

    def reconcile(self, request: TaskClaimRequest) -> TaskClaim:
        path = self._path(request.task_id)
        expected = self._record(request)
        expected_digest = digest(expected)
        current = self._read(path)
        acquired = current is not None and digest(current) == expected_digest
        reason = (
            "Local claim matches the durable request."
            if acquired
            else "Durable request does not own the current local claim marker."
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
            repository=None,
            ownership_ref=self._relative_ref(request.task_id),
            ownership_sha=expected_digest,
        )

    def validate(self, claim: TaskClaim) -> bool:
        if (
            not claim.acquired
            or claim.provider != self.provider
            or not claim.ownership_ref
            or not claim.ownership_sha
        ):
            return False
        expected_ref = self._relative_ref(claim.task_id)
        if claim.ownership_ref != expected_ref:
            return False
        current = self._read(self.project_root / expected_ref)
        return current is not None and digest(current) == claim.ownership_sha

    def release(self, claim: TaskClaim) -> None:
        if not claim.acquired:
            raise TaskStoreError("Cannot release a task claim that was not acquired.")
        if claim.provider != self.provider:
            raise TaskStoreError(
                f"Local claimer for {self.provider!r} cannot release "
                f"provider {claim.provider!r}."
            )
        if not claim.ownership_ref or not claim.ownership_sha:
            raise TaskStoreError("Local task claim is missing ownership evidence.")

        path = self.project_root / claim.ownership_ref
        with project_lock(self.project_root, "local-task-claim-op"):
            current = self._read(path)
            if current is None:
                return
            if digest(current) != claim.ownership_sha:
                raise ClaimConflictError(
                    "Local task claim ownership changed; refusing deletion."
                )
            path.unlink()

    def release_legacy(self, task_id: str, *, actor: str) -> None:
        del task_id, actor
        raise TaskStoreError(
            "Local exact claims cannot be released without durable ownership evidence."
        )
