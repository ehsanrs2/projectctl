from __future__ import annotations

import os
import subprocess
from pathlib import Path

from projectctl.core.digest import digest
from projectctl.core.errors import IntegrationError, TaskStoreError
from projectctl.core.time import utc_now
from projectctl.integrations.github.repository import parse_github_repository
from projectctl.schemas.delivery import PublicationManifest, PublicationRequest


class GitRemotePublisher:
    """Exact-base, fast-forward-only publication to one Git remote."""

    def __init__(
        self,
        project_root: Path,
        *,
        repository: str,
        remote_name: str = "origin",
        timeout_seconds: int = 60,
    ):
        self.project_root = project_root.resolve()
        self.repository = repository
        self.remote_name = remote_name
        self.timeout_seconds = timeout_seconds

    def _git(
        self,
        *args: str,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env["GIT_TERMINAL_PROMPT"] = "0"
        try:
            result = subprocess.run(
                [
                    "git",
                    "-c",
                    "core.hooksPath=/dev/null",
                    "-C",
                    str(self.project_root),
                    *args,
                ],
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                check=False,
                env=env,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise IntegrationError(f"Git publication command failed: {exc}") from exc
        if check and result.returncode != 0:
            message = (result.stderr or result.stdout or "git error").strip()
            raise IntegrationError(
                f"git {' '.join(args)} failed ({result.returncode}): {message}"
            )
        return result

    @staticmethod
    def _target_ref(target_ref: str) -> str:
        value = target_ref.strip()
        if value.startswith("refs/heads/"):
            value = value[len("refs/heads/") :]
        if not value or value.startswith("refs/") or ".." in value:
            raise IntegrationError(
                f"Unsupported publication target branch: {target_ref!r}"
            )
        return f"refs/heads/{value}"

    def _assert_remote_identity(self) -> None:
        url = self._git("remote", "get-url", self.remote_name).stdout.strip()
        observed = parse_github_repository(url)
        if observed != self.repository:
            raise IntegrationError(
                "Publication remote identity does not match task authority repository: "
                f"remote={observed or 'non-github/unknown'}, configured={self.repository}."
            )

    def observe(self, target_ref: str) -> str | None:
        ref = self._target_ref(target_ref)
        result = self._git(
            "ls-remote",
            "--refs",
            self.remote_name,
            ref,
        )
        rows = [line for line in result.stdout.splitlines() if line.strip()]
        if not rows:
            return None
        if len(rows) != 1:
            raise IntegrationError(
                f"Remote publication observation for {ref!r} returned {len(rows)} rows."
            )
        sha, observed_ref = rows[0].split("\t", 1)
        if observed_ref != ref:
            raise IntegrationError(
                f"Remote publication observation returned unexpected ref {observed_ref!r}."
            )
        return sha

    def _validate_request(self, request: PublicationRequest) -> str:
        if request.provider != "github":
            raise IntegrationError(
                f"Git publisher cannot publish provider {request.provider!r}."
            )
        if request.repository != self.repository:
            raise IntegrationError(
                "Publication request repository differs from configured GitHub authority."
            )
        if request.remote_name != self.remote_name:
            raise IntegrationError(
                "Publication request remote differs from configured publication remote."
            )
        self._assert_remote_identity()

        base_exists = self._git(
            "cat-file", "-e", f"{request.base_commit}^{{commit}}", check=False
        )
        candidate_exists = self._git(
            "cat-file", "-e", f"{request.candidate_commit}^{{commit}}", check=False
        )
        if base_exists.returncode != 0 or candidate_exists.returncode != 0:
            raise IntegrationError(
                "Publication base/candidate commit is not available in the local repository."
            )
        ancestor = self._git(
            "merge-base",
            "--is-ancestor",
            request.base_commit,
            request.candidate_commit,
            check=False,
        )
        if ancestor.returncode != 0:
            raise IntegrationError(
                "Publication candidate is not a fast-forward descendant of the verified base."
            )
        return self._target_ref(request.target_ref)

    def reconcile(self, request: PublicationRequest) -> PublicationManifest:
        self._validate_request(request)
        current = self.observe(request.target_ref)
        if current == request.candidate_commit:
            return PublicationManifest(
                run_id=request.run_id,
                task_id=request.task_id,
                provider=request.provider,
                repository=request.repository,
                remote_name=request.remote_name,
                target_ref=request.target_ref,
                base_commit=request.base_commit,
                candidate_commit=request.candidate_commit,
                evidence_manifest=request.evidence_manifest,
                evidence_digest=request.evidence_digest,
                request_digest=digest(request),
                remote_before=current,
                remote_after=current,
                published=True,
                observed_at=utc_now(),
                reason="Verified candidate is already visible on the publication target.",
            )
        reason = (
            "Remote publication target remains at the verified base."
            if current == request.base_commit
            else (
                "Remote publication target does not match verified base or candidate."
                if current is not None
                else "Remote publication target is missing."
            )
        )
        return PublicationManifest(
            run_id=request.run_id,
            task_id=request.task_id,
            provider=request.provider,
            repository=request.repository,
            remote_name=request.remote_name,
            target_ref=request.target_ref,
            base_commit=request.base_commit,
            candidate_commit=request.candidate_commit,
            evidence_manifest=request.evidence_manifest,
            evidence_digest=request.evidence_digest,
            request_digest=digest(request),
            remote_before=current,
            remote_after=current,
            published=False,
            observed_at=utc_now(),
            reason=reason,
        )

    def publish(self, request: PublicationRequest) -> PublicationManifest:
        target = self._validate_request(request)
        before = self.observe(request.target_ref)
        if before == request.candidate_commit:
            return self.reconcile(request)
        if before != request.base_commit:
            return PublicationManifest(
                run_id=request.run_id,
                task_id=request.task_id,
                provider=request.provider,
                repository=request.repository,
                remote_name=request.remote_name,
                target_ref=request.target_ref,
                base_commit=request.base_commit,
                candidate_commit=request.candidate_commit,
                evidence_manifest=request.evidence_manifest,
                evidence_digest=request.evidence_digest,
                request_digest=digest(request),
                remote_before=before,
                remote_after=before,
                published=False,
                observed_at=utc_now(),
                reason="Remote publication target changed before publication.",
            )

        result = self._git(
            "push",
            "--porcelain",
            f"--force-with-lease={target}:{request.base_commit}",
            self.remote_name,
            f"{request.candidate_commit}:{target}",
            check=False,
        )
        after = self.observe(request.target_ref)
        if after == request.candidate_commit:
            return PublicationManifest(
                run_id=request.run_id,
                task_id=request.task_id,
                provider=request.provider,
                repository=request.repository,
                remote_name=request.remote_name,
                target_ref=request.target_ref,
                base_commit=request.base_commit,
                candidate_commit=request.candidate_commit,
                evidence_manifest=request.evidence_manifest,
                evidence_digest=request.evidence_digest,
                request_digest=digest(request),
                remote_before=before,
                remote_after=after,
                published=True,
                observed_at=utc_now(),
                reason=None,
            )

        message = (result.stderr or result.stdout or "remote publication failed").strip()
        if after != request.base_commit:
            reason = (
                "Remote publication target changed concurrently; "
                f"observed {after or 'missing'}."
            )
        else:
            reason = (
                "Remote rejected or did not apply the exact-base publication: "
                f"{message}"
            )
        return PublicationManifest(
            run_id=request.run_id,
            task_id=request.task_id,
            provider=request.provider,
            repository=request.repository,
            remote_name=request.remote_name,
            target_ref=request.target_ref,
            base_commit=request.base_commit,
            candidate_commit=request.candidate_commit,
            evidence_manifest=request.evidence_manifest,
            evidence_digest=request.evidence_digest,
            request_digest=digest(request),
            remote_before=before,
            remote_after=after,
            published=False,
            observed_at=utc_now(),
            reason=reason,
        )
