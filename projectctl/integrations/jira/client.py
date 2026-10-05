from __future__ import annotations

import base64
import json
import os
import re
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from projectctl.core.errors import ProviderUnavailableError, TaskStoreError


JIRA_REST_CONTRACT = "jira-cloud-rest-v3-2026-10"
_PROJECT_KEY = re.compile(r"^[A-Za-z][A-Za-z0-9_\-]*$")
_FIELDS = [
    "summary",
    "status",
    "priority",
    "issuetype",
    "assignee",
    "parent",
    "created",
    "updated",
    "duedate",
    "resolution",
    "labels",
    "project",
]


def normalize_jira_site(value: str) -> str:
    raw = str(value).strip().rstrip("/").casefold()
    if not raw:
        raise TaskStoreError("Jira task authority requires task_store.site.")
    if "://" in raw or "/" in raw or "@" in raw:
        raise TaskStoreError(
            "Jira site must be a credential-free host such as acme.atlassian.net."
        )
    if not raw.endswith(".atlassian.net"):
        raise TaskStoreError(
            "M3.3a built-in Jira authority supports Jira Cloud *.atlassian.net sites only."
        )
    return raw


def normalize_jira_project(value: str) -> str:
    raw = str(value).strip().upper()
    if not raw or not _PROJECT_KEY.fullmatch(raw):
        raise TaskStoreError(
            "Jira project must be a Jira project key such as ENG or PLATFORM."
        )
    return raw


def _jql_literal(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


class JiraCloudClient:
    """Narrow read-only Jira Cloud REST v3 authority client.

    Credentials are runtime-only. M3.3a supports Atlassian basic authentication
    for local scripts/bots using JIRA_EMAIL + JIRA_API_TOKEN. No credential is
    written to ProjectCTL configuration or artifacts.
    """

    def __init__(
        self,
        project_root: Path,
        *,
        site: str,
        project_key: str,
        email: str | None = None,
        api_token: str | None = None,
        timeout_seconds: int = 30,
    ):
        self.project_root = project_root.resolve()
        self.site = normalize_jira_site(site)
        self.project_key = normalize_jira_project(project_key)

        resolved_email = email if email is not None else os.environ.get("JIRA_EMAIL")
        resolved_token = (
            api_token if api_token is not None else os.environ.get("JIRA_API_TOKEN")
        )
        resolved_email = str(resolved_email or "").strip()
        resolved_token = str(resolved_token or "").strip()
        if bool(resolved_email) != bool(resolved_token):
            raise ProviderUnavailableError(
                "Jira basic authentication requires both JIRA_EMAIL and JIRA_API_TOKEN."
            )
        if not resolved_email or not resolved_token:
            raise ProviderUnavailableError(
                "Jira task authority requires JIRA_EMAIL and JIRA_API_TOKEN in the environment."
            )

        encoded = base64.b64encode(
            f"{resolved_email}:{resolved_token}".encode("utf-8")
        ).decode("ascii")
        self.authorization = f"Basic {encoded}"
        self.timeout_seconds = timeout_seconds
        self.base_url = f"https://{self.site}"

    def _api(
        self,
        method: str,
        endpoint: str,
        *,
        payload: dict[str, Any] | None = None,
        query: dict[str, Any] | None = None,
    ) -> Any:
        path = endpoint if endpoint.startswith("/") else f"/{endpoint}"
        url = f"{self.base_url}{path}"
        if query:
            filtered = {
                key: value
                for key, value in query.items()
                if value is not None
            }
            if filtered:
                url += "?" + urlencode(filtered, doseq=True)

        body = None
        headers = {
            "Accept": "application/json",
            "Authorization": self.authorization,
            "User-Agent": "projectctl-jira-read-authority",
        }
        if payload is not None:
            body = json.dumps(payload, sort_keys=True).encode("utf-8")
            headers["Content-Type"] = "application/json"

        request = Request(url, data=body, method=method, headers=headers)
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                status = int(response.status)
                raw = response.read()
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:1000]
            raise TaskStoreError(
                f"Jira REST {method} {path} failed with HTTP {exc.code}: {detail}"
            ) from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise ProviderUnavailableError(
                f"Jira REST request failed: {exc}"
            ) from exc

        if status < 200 or status >= 300:
            raise TaskStoreError(
                f"Jira REST {method} {path} returned unexpected HTTP {status}."
            )
        if not raw:
            return None
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise TaskStoreError("Jira REST returned invalid JSON.") from exc

    def project_info(self) -> dict[str, Any]:
        raw = self._api(
            "GET",
            f"/rest/api/3/project/{quote(self.project_key, safe='')}",
        )
        if not isinstance(raw, dict):
            raise TaskStoreError("Jira project response is not an object.")
        observed_key = str(raw.get("key") or "").strip().upper()
        if observed_key != self.project_key:
            raise TaskStoreError(
                "Jira project response key differs from configured task_store.project."
            )
        if not str(raw.get("id") or "").strip():
            raise TaskStoreError("Jira project response is missing a stable id.")
        return raw

    def _validate_issue(self, raw: Any) -> dict[str, Any]:
        if not isinstance(raw, dict):
            raise TaskStoreError("Jira search returned a non-object issue.")
        issue_id = str(raw.get("id") or "").strip()
        key = str(raw.get("key") or "").strip().upper()
        fields = raw.get("fields")
        if not issue_id or not key or not isinstance(fields, dict):
            raise TaskStoreError(
                "Jira issue is missing stable id, key, or fields metadata."
            )
        project = fields.get("project")
        observed_project = (
            str(project.get("key") or "").strip().upper()
            if isinstance(project, dict)
            else ""
        )
        if observed_project != self.project_key:
            raise TaskStoreError(
                f"Jira search leaked issue {key!r} from project "
                f"{observed_project or 'unknown'!r}; expected {self.project_key!r}."
            )
        return raw

    def list_all(self, *, page_size: int = 100) -> list[dict[str, Any]]:
        if page_size <= 0 or page_size > 100:
            raise ValueError("Jira page_size must be between 1 and 100.")

        token: str | None = None
        seen_tokens: set[str] = set()
        issues: list[dict[str, Any]] = []
        jql = f'project = "{_jql_literal(self.project_key)}" ORDER BY key ASC'

        while True:
            payload: dict[str, Any] = {
                "jql": jql,
                "maxResults": page_size,
                "fields": _FIELDS,
                "fieldsByKeys": True,
            }
            if token is not None:
                payload["nextPageToken"] = token

            raw = self._api(
                "POST",
                "/rest/api/3/search/jql",
                payload=payload,
            )
            if not isinstance(raw, dict):
                raise TaskStoreError("Jira enhanced search response is not an object.")
            page = raw.get("issues")
            is_last = raw.get("isLast")
            if not isinstance(page, list) or not isinstance(is_last, bool):
                raise TaskStoreError(
                    "Jira enhanced search response has invalid issues/isLast metadata."
                )
            issues.extend(self._validate_issue(issue) for issue in page)

            if is_last:
                return issues

            next_token = raw.get("nextPageToken")
            if not isinstance(next_token, str) or not next_token.strip():
                raise TaskStoreError(
                    "Jira enhanced search isLast=false without a usable nextPageToken."
                )
            if next_token in seen_tokens:
                raise TaskStoreError(
                    "Jira enhanced search repeated nextPageToken; refusing pagination loop."
                )
            seen_tokens.add(next_token)
            token = next_token

    def show(self, issue_key: str) -> dict[str, Any]:
        key = str(issue_key).strip().upper()
        if key.startswith("JIRA-"):
            key = key[len("JIRA-") :]
        if not key:
            raise ValueError("Jira issue key must be non-empty.")
        raw = self._api(
            "GET",
            f"/rest/api/3/issue/{quote(key, safe='')}",
            query={"fields": ",".join(_FIELDS)},
        )
        return self._validate_issue(raw)

    def version(self) -> str:
        return JIRA_REST_CONTRACT
