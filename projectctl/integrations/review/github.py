from __future__ import annotations

import json
import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode

from projectctl.core.digest import digest
from projectctl.core.errors import IntegrationError, ProviderUnavailableError
from projectctl.core.time import utc_now
from projectctl.git.review import ReviewGitTransport
from projectctl.schemas.delivery import ReviewReceipt, ReviewRequest


_GITHUB_API_VERSION = "2026-03-10"


def _parse_time(value) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise IntegrationError(f"GitHub review timestamp is invalid: {value!r}") from exc


class GitHubReviewDeliveryAdapter:
    """GitHub PR delivery adapter. It creates/reconciles review; it never merges."""

    def __init__(
        self,
        project_root: Path,
        *,
        remote_name: str,
        remote_identity: str,
        executable: str | None = None,
        timeout_seconds: int = 60,
    ):
        self.project_root = project_root.resolve()
        self.remote_name = remote_name
        self.remote_identity = remote_identity
        if not remote_identity.startswith("github.com/"):
            raise IntegrationError(
                "Built-in GitHub review delivery currently requires a github.com remote identity."
            )
        self.repository = remote_identity[len("github.com/") :]
        parts = self.repository.split("/")
        if len(parts) != 2 or not all(parts):
            raise IntegrationError(
                "GitHub review delivery requires github.com/<owner>/<repository>."
            )
        self.owner = parts[0]
        self.executable = executable or shutil.which("gh")
        if not self.executable:
            raise ProviderUnavailableError(
                "GitHub review delivery requires the authenticated gh CLI."
            )
        self.timeout_seconds = timeout_seconds
        self.transport = ReviewGitTransport(
            self.project_root,
            remote_name=remote_name,
            remote_identity=remote_identity,
            timeout_seconds=timeout_seconds,
        )

    def _api(self, method: str, endpoint: str, payload: dict | None = None):
        args = [
            self.executable,
            "api",
            "--hostname",
            "github.com",
            "--method",
            method,
            "-H",
            "Accept: application/vnd.github+json",
            "-H",
            f"X-GitHub-Api-Version: {_GITHUB_API_VERSION}",
            endpoint,
        ]
        input_text = None
        if payload is not None:
            args.extend(["--input", "-"])
            input_text = json.dumps(payload, sort_keys=True)
        env = os.environ.copy()
        env["GH_PROMPT_DISABLED"] = "1"
        try:
            result = subprocess.run(
                args,
                input=input_text,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                check=False,
                cwd=self.project_root,
                env=env,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ProviderUnavailableError(
                f"GitHub review API command failed: {exc}"
            ) from exc
        if result.returncode != 0:
            message = (result.stderr or result.stdout or "GitHub API error").strip()
            raise IntegrationError(
                f"GitHub review API {method} {endpoint} failed: {message}"
            )
        try:
            return json.loads(result.stdout) if result.stdout.strip() else None
        except json.JSONDecodeError as exc:
            raise IntegrationError(
                "GitHub review API returned invalid JSON."
            ) from exc

    def _receipt(self, request: ReviewRequest, raw: dict | None) -> ReviewReceipt:
        if raw is None:
            return ReviewReceipt(
                run_id=request.run_id,
                task_id=request.task_id,
                review_provider="github",
                request_digest=digest(request),
                source_ref=request.source_ref,
                target_ref=request.target_ref,
                state="missing",
                observed_at=utc_now(),
                reason="No GitHub pull request exists for the deterministic review branch.",
            )
        if not isinstance(raw, dict):
            raise IntegrationError("GitHub pull request response is not an object.")

        head = raw.get("head")
        base = raw.get("base")
        if not isinstance(head, dict) or not isinstance(base, dict):
            raise IntegrationError("GitHub pull request response is missing head/base metadata.")
        head_ref = str(head.get("ref") or "")
        base_ref = str(base.get("ref") or "")
        head_sha = str(head.get("sha") or "")
        if head_ref != request.source_ref or base_ref != request.target_ref:
            raise IntegrationError(
                "GitHub pull request refs differ from the durable review request."
            )
        if head_sha != request.candidate_commit:
            raise IntegrationError(
                "GitHub pull request head no longer equals the verified candidate."
            )

        merged_at = _parse_time(raw.get("merged_at"))
        raw_state = str(raw.get("state") or "").casefold()
        if merged_at is not None:
            state = "merged"
        elif raw_state == "open":
            state = "open"
        elif raw_state == "closed":
            state = "closed"
        else:
            raise IntegrationError(
                f"GitHub pull request returned unknown state {raw_state or 'missing'!r}."
            )

        number = raw.get("number")
        url = str(raw.get("html_url") or "").strip()
        if number is None or not url:
            raise IntegrationError("GitHub pull request is missing stable identity/URL.")
        merge_commit = str(raw.get("merge_commit_sha") or "").strip() or None
        return ReviewReceipt(
            run_id=request.run_id,
            task_id=request.task_id,
            review_provider="github",
            request_digest=digest(request),
            review_id=str(number),
            review_url=url,
            source_ref=request.source_ref,
            target_ref=request.target_ref,
            head_commit=head_sha,
            merge_commit=merge_commit,
            state=state,
            merged_at=merged_at,
            observed_at=utc_now(),
            reason=(
                None
                if state == "merged"
                else "GitHub pull request is awaiting review/merge."
                if state == "open"
                else "GitHub pull request was closed without merge."
            ),
        )

    def reconcile(self, request: ReviewRequest) -> ReviewReceipt:
        query = urlencode(
            {
                "state": "all",
                "head": f"{self.owner}:{request.source_ref}",
                "base": request.target_ref,
                "per_page": 100,
            }
        )
        raw = self._api(
            "GET",
            f"repos/{self.repository}/pulls?{query}",
        )
        if not isinstance(raw, list):
            raise IntegrationError("GitHub pull request list response is not an array.")
        if len(raw) > 1:
            raise IntegrationError(
                "Multiple GitHub pull requests match the deterministic ProjectCTL review branch."
            )
        return self._receipt(request, raw[0] if raw else None)

    def request_review(self, request: ReviewRequest) -> ReviewReceipt:
        self.transport.ensure_source(request)
        existing = self.reconcile(request)
        if existing.state != "missing":
            return existing

        try:
            raw = self._api(
                "POST",
                f"repos/{self.repository}/pulls",
                {
                    "title": request.title,
                    "body": request.body,
                    "head": request.source_ref,
                    "base": request.target_ref,
                    "maintainer_can_modify": False,
                },
            )
            return self._receipt(request, raw)
        except IntegrationError:
            observed = self.reconcile(request)
            if observed.state != "missing":
                return observed
            raise
