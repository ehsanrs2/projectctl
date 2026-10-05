from __future__ import annotations

import base64
import json
import os
import re
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen

from projectctl.core.errors import ProviderUnavailableError, TaskStoreError


JIRA_REST_CONTRACT = "jira-cloud-rest-v3-m33c-2026-10"
JIRA_LIFECYCLE_PROPERTY = "projectctl.lifecycle.v1"
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
    "issuelinks",
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


class _NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


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

    @staticmethod
    def _decode_json(raw: bytes) -> Any:
        if not raw:
            return None
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise TaskStoreError("Jira REST returned invalid JSON.") from exc

    def _request(
        self,
        method: str,
        endpoint: str,
        *,
        payload: dict[str, Any] | None = None,
        query: dict[str, Any] | None = None,
        allow_not_found: bool = False,
    ) -> tuple[int, dict[str, str], Any]:
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
            "User-Agent": "projectctl-jira-authority",
        }
        if payload is not None:
            body = json.dumps(payload, sort_keys=True).encode("utf-8")
            headers["Content-Type"] = "application/json"

        request = Request(url, data=body, method=method, headers=headers)
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                status = int(response.status)
                response_headers = {
                    str(key).casefold(): str(value)
                    for key, value in response.headers.items()
                }
                raw = response.read()
        except HTTPError as exc:
            if allow_not_found and exc.code == 404:
                return 404, {}, None
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
        return status, response_headers, self._decode_json(raw)

    def _api(
        self,
        method: str,
        endpoint: str,
        *,
        payload: dict[str, Any] | None = None,
        query: dict[str, Any] | None = None,
    ) -> Any:
        _, _, value = self._request(
            method,
            endpoint,
            payload=payload,
            query=query,
        )
        return value

    def _submit_async(
        self,
        method: str,
        endpoint: str,
        *,
        payload: dict[str, Any],
    ) -> Any:
        path = endpoint if endpoint.startswith("/") else f"/{endpoint}"
        url = f"{self.base_url}{path}"
        body = json.dumps(payload, sort_keys=True).encode("utf-8")
        request = Request(
            url,
            data=body,
            method=method,
            headers={
                "Accept": "application/json",
                "Authorization": self.authorization,
                "Content-Type": "application/json",
                "User-Agent": "projectctl-jira-authority",
            },
        )
        opener = build_opener(_NoRedirectHandler())
        location: str | None = None
        try:
            with opener.open(request, timeout=self.timeout_seconds) as response:
                status = int(response.status)
                if status == 303:
                    location = response.headers.get("Location")
                else:
                    raise TaskStoreError(
                        f"Jira async REST {method} {path} returned HTTP {status}; "
                        "expected 303."
                    )
        except HTTPError as exc:
            if exc.code == 303:
                location = exc.headers.get("Location")
            else:
                detail = exc.read().decode("utf-8", errors="replace")[:1000]
                raise TaskStoreError(
                    f"Jira async REST {method} {path} failed with HTTP "
                    f"{exc.code}: {detail}"
                ) from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise ProviderUnavailableError(
                f"Jira async REST request failed: {exc}"
            ) from exc

        if not location:
            raise TaskStoreError(
                "Jira async operation did not return a task Location."
            )
        parsed = urlparse(location)
        if parsed.netloc and parsed.netloc.casefold() != self.site:
            raise TaskStoreError(
                "Jira async task Location points outside the configured site."
            )
        task_endpoint = parsed.path
        if parsed.query:
            task_endpoint += "?" + parsed.query

        deadline = time.monotonic() + self.timeout_seconds
        while True:
            task = self._api("GET", task_endpoint)
            if not isinstance(task, dict):
                raise TaskStoreError("Jira async task response is malformed.")
            status = str(task.get("status") or "").strip().upper()
            if status == "COMPLETE":
                return task.get("result")
            if status in {"FAILED", "CANCELLED"}:
                raise TaskStoreError(
                    f"Jira async task ended with status {status}."
                )
            if status not in {"ENQUEUED", "RUNNING", "IN_PROGRESS"}:
                raise TaskStoreError(
                    f"Jira async task returned unknown status {status or 'missing'}."
                )
            if time.monotonic() >= deadline:
                raise ProviderUnavailableError(
                    "Jira async property mutation did not complete before timeout."
                )
            time.sleep(0.1)

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

    def _validate_issue(
        self,
        raw: Any,
        *,
        require_project_scope: bool = True,
    ) -> dict[str, Any]:
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
        if not observed_project:
            raise TaskStoreError(
                f"Jira issue {key!r} is missing project identity metadata."
            )
        if require_project_scope and observed_project != self.project_key:
            raise TaskStoreError(
                f"Jira search leaked issue {key!r} from project "
                f"{observed_project!r}; expected {self.project_key!r}."
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
                "properties": [JIRA_LIFECYCLE_PROPERTY],
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
            query={
                "fields": ",".join(_FIELDS),
                "properties": [JIRA_LIFECYCLE_PROPERTY],
            },
        )
        return self._validate_issue(raw)

    def show_linked(self, issue_key: str) -> dict[str, Any]:
        """Read a linked issue on the same Jira site without project scoping.

        Cross-project dependencies are allowed only after this independent read
        proves stable issue id/key/project/status metadata. Credentials still
        control whether the linked issue is visible.
        """
        key = str(issue_key).strip().upper()
        if not key:
            raise ValueError("Jira linked issue key must be non-empty.")
        raw = self._api(
            "GET",
            f"/rest/api/3/issue/{quote(key, safe='')}",
            query={"fields": ",".join(_FIELDS)},
        )
        return self._validate_issue(raw, require_project_scope=False)

    def get_issue_property(
        self,
        issue_id_or_key: str,
        property_key: str,
    ) -> Any | None:
        status, _, raw = self._request(
            "GET",
            f"/rest/api/3/issue/{quote(str(issue_id_or_key), safe='')}/properties/"
            f"{quote(property_key, safe='')}",
            allow_not_found=True,
        )
        if status == 404:
            return None
        if not isinstance(raw, dict) or raw.get("key") != property_key:
            raise TaskStoreError("Jira issue-property response is malformed.")
        if "value" not in raw:
            raise TaskStoreError("Jira issue-property response is missing value.")
        return raw["value"]

    def compare_and_set_issue_property(
        self,
        issue_id: str,
        property_key: str,
        *,
        expected: Any | None,
        desired: Any,
    ) -> bool:
        try:
            numeric_id = int(str(issue_id))
        except ValueError as exc:
            raise TaskStoreError(
                "Jira issue property CAS requires a stable numeric issue id."
            ) from exc

        filter_value: dict[str, Any] = {"entityIds": [numeric_id]}
        if expected is None:
            filter_value["hasProperty"] = False
        else:
            filter_value["hasProperty"] = True
            filter_value["currentValue"] = expected

        self._submit_async(
            "PUT",
            f"/rest/api/3/issue/properties/{quote(property_key, safe='')}",
            payload={
                "filter": filter_value,
                "value": desired,
            },
        )

        observed = self.get_issue_property(issue_id, property_key)
        if observed == desired:
            return True
        if observed == expected:
            return False
        if observed is None and expected is None:
            return False
        raise TaskStoreError(
            "Jira lifecycle property changed to an unexpected value during CAS."
        )

    def issue_link_types(self) -> list[dict[str, Any]]:
        raw = self._api("GET", "/rest/api/3/issueLinkType")
        if not isinstance(raw, dict) or not isinstance(raw.get("issueLinkTypes"), list):
            raise TaskStoreError("Jira issue-link-type response is malformed.")
        values: list[dict[str, Any]] = []
        for item in raw["issueLinkTypes"]:
            if not isinstance(item, dict):
                raise TaskStoreError("Jira issue-link-type response contains a non-object.")
            if not all(str(item.get(key) or "").strip() for key in ("id", "name", "inward", "outward")):
                raise TaskStoreError("Jira issue-link-type response is missing identity/labels.")
            values.append(item)
        return values

    def statuses(self) -> list[dict[str, Any]]:
        raw = self._api("GET", "/rest/api/3/status")
        if not isinstance(raw, list):
            raise TaskStoreError("Jira status catalog response is malformed.")
        values: list[dict[str, Any]] = []
        for item in raw:
            if not isinstance(item, dict):
                raise TaskStoreError("Jira status catalog contains a non-object.")
            if not str(item.get("id") or "").strip() or not str(item.get("name") or "").strip():
                raise TaskStoreError("Jira status catalog entry is missing id/name.")
            values.append(item)
        return values

    def version(self) -> str:
        return JIRA_REST_CONTRACT
