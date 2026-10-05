from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from projectctl.core.digest import digest
from projectctl.core.errors import IntegrationError, ProviderUnavailableError
from projectctl.core.time import utc_now
from projectctl.git.review import ReviewGitTransport
from projectctl.schemas.delivery import ReviewReceipt, ReviewRequest


def _parse_time(value) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise IntegrationError(f"GitLab review timestamp is invalid: {value!r}") from exc


class GitLabReviewDeliveryAdapter:
    """GitLab MR delivery adapter. It creates/reconciles review; it never merges."""

    def __init__(
        self,
        project_root: Path,
        *,
        remote_name: str,
        remote_identity: str,
        token: str | None = None,
        access_token: str | None = None,
        timeout_seconds: int = 60,
    ):
        self.project_root = project_root.resolve()
        self.remote_name = remote_name
        self.remote_identity = remote_identity
        if not remote_identity.startswith("gitlab.com/"):
            raise IntegrationError(
                "Built-in GitLab review delivery currently requires a gitlab.com remote identity."
            )
        self.project_path = remote_identity[len("gitlab.com/") :]
        if "/" not in self.project_path or self.project_path.startswith("/"):
            raise IntegrationError(
                "GitLab review delivery requires gitlab.com/<group>/<repository>."
            )
        env_token = token if token is not None else os.environ.get("GITLAB_TOKEN")
        env_access = (
            access_token
            if access_token is not None
            else os.environ.get("GITLAB_ACCESS_TOKEN")
        )
        if env_token and env_access:
            raise ProviderUnavailableError(
                "Configure only one of GITLAB_TOKEN or GITLAB_ACCESS_TOKEN."
            )
        if not env_token and not env_access:
            raise ProviderUnavailableError(
                "GitLab review delivery requires GITLAB_TOKEN or GITLAB_ACCESS_TOKEN."
            )
        self.token = env_token
        self.access_token = env_access
        self.timeout_seconds = timeout_seconds
        self.transport = ReviewGitTransport(
            self.project_root,
            remote_name=remote_name,
            remote_identity=remote_identity,
            timeout_seconds=timeout_seconds,
        )
        self.project_api = quote(self.project_path, safe="")

    def _api(
        self,
        method: str,
        endpoint: str,
        payload: dict | None = None,
        query: dict | None = None,
    ):
        url = f"https://gitlab.com/api/v4/{endpoint}"
        if query:
            url += "?" + urlencode(query)
        body = None
        headers = {"Accept": "application/json"}
        if self.token:
            headers["PRIVATE-TOKEN"] = self.token
        else:
            headers["Authorization"] = f"Bearer {self.access_token}"
        if payload is not None:
            body = json.dumps(payload, sort_keys=True).encode("utf-8")
            headers["Content-Type"] = "application/json"

        request = Request(url, data=body, headers=headers, method=method)
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                raw = response.read()
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise IntegrationError(
                f"GitLab review API {method} {endpoint} failed ({exc.code}): {detail}"
            ) from exc
        except (URLError, OSError, TimeoutError) as exc:
            raise ProviderUnavailableError(
                f"GitLab review API request failed: {exc}"
            ) from exc
        try:
            return json.loads(raw.decode("utf-8")) if raw else None
        except json.JSONDecodeError as exc:
            raise IntegrationError("GitLab review API returned invalid JSON.") from exc

    def _receipt(self, request: ReviewRequest, raw: dict | None) -> ReviewReceipt:
        if raw is None:
            return ReviewReceipt(
                run_id=request.run_id,
                task_id=request.task_id,
                review_provider="gitlab",
                request_digest=digest(request),
                source_ref=request.source_ref,
                target_ref=request.target_ref,
                state="missing",
                observed_at=utc_now(),
                reason="No GitLab merge request exists for the deterministic review branch.",
            )
        if not isinstance(raw, dict):
            raise IntegrationError("GitLab merge request response is not an object.")

        source_ref = str(raw.get("source_branch") or "")
        target_ref = str(raw.get("target_branch") or "")
        head_sha = str(raw.get("sha") or "")
        if source_ref != request.source_ref or target_ref != request.target_ref:
            raise IntegrationError(
                "GitLab merge request refs differ from the durable review request."
            )
        if head_sha != request.candidate_commit:
            raise IntegrationError(
                "GitLab merge request head no longer equals the verified candidate."
            )

        raw_state = str(raw.get("state") or "").casefold()
        if raw_state == "merged":
            state = "merged"
        elif raw_state == "opened":
            state = "open"
        elif raw_state == "closed":
            state = "closed"
        else:
            raise IntegrationError(
                f"GitLab merge request returned unknown state {raw_state or 'missing'!r}."
            )
        iid = raw.get("iid")
        url = str(raw.get("web_url") or "").strip()
        if iid is None or not url:
            raise IntegrationError("GitLab merge request is missing stable identity/URL.")
        merged_at = _parse_time(raw.get("merged_at"))
        merge_commit = str(raw.get("merge_commit_sha") or "").strip() or None
        return ReviewReceipt(
            run_id=request.run_id,
            task_id=request.task_id,
            review_provider="gitlab",
            request_digest=digest(request),
            review_id=str(iid),
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
                else "GitLab merge request is awaiting review/merge."
                if state == "open"
                else "GitLab merge request was closed without merge."
            ),
        )

    def reconcile(self, request: ReviewRequest) -> ReviewReceipt:
        raw = self._api(
            "GET",
            f"projects/{self.project_api}/merge_requests",
            query={
                "scope": "all",
                "state": "all",
                "source_branch": request.source_ref,
                "target_branch": request.target_ref,
                "per_page": 100,
            },
        )
        if not isinstance(raw, list):
            raise IntegrationError("GitLab merge request list response is not an array.")
        if len(raw) > 1:
            raise IntegrationError(
                "Multiple GitLab merge requests match the deterministic ProjectCTL review branch."
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
                f"projects/{self.project_api}/merge_requests",
                payload={
                    "source_branch": request.source_ref,
                    "target_branch": request.target_ref,
                    "title": request.title,
                    "description": request.body,
                    "remove_source_branch": False,
                    "squash": False,
                },
            )
            return self._receipt(request, raw)
        except IntegrationError:
            observed = self.reconcile(request)
            if observed.state != "missing":
                return observed
            raise
