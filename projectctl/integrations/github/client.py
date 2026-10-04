from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

from projectctl.core.errors import ProviderUnavailableError, TaskStoreError
from projectctl.core.time import utc_now
from projectctl.integrations.github.repository import (
    infer_github_repository,
    normalize_github_repository,
)
from projectctl.telemetry.events import record_event

if TYPE_CHECKING:
    from projectctl.integrations.github.cache import GitHubDerivedCache


GITHUB_API_VERSION = "2026-03-10"
GITHUB_ACCEPT = "application/vnd.github+json"


@dataclass(frozen=True)
class GitHubGetResponse:
    status_code: int
    headers: dict[str, str]
    payload: Any


class GitHubIssuesClient:
    """Narrow wrapper around the authenticated `gh api` surface.

    ProjectCTL does not persist GitHub credentials. Authentication, host policy,
    and token storage remain owned by GitHub CLI.

    M3.1c2 conditionally revalidates single-response GET representations. It
    deliberately does not attach one validator to a multi-page
    `--paginate --slurp` aggregate because an HTTP validator belongs to one
    concrete response representation/page.
    """

    def __init__(
        self,
        project_root: Path,
        *,
        repository: str | None = None,
        executable: str | None = None,
        timeout_seconds: int = 30,
        cache: GitHubDerivedCache | None = None,
    ):
        self.project_root = project_root.resolve()
        self.executable = executable or shutil.which("gh")
        if not self.executable:
            raise ProviderUnavailableError(
                "GitHub CLI `gh` was not found in PATH."
            )
        inferred = repository or infer_github_repository(self.project_root)
        self.repository = normalize_github_repository(inferred)
        if self.repository is None:
            raise TaskStoreError(
                "GitHub task store requires an owner/repository identity. "
                "Set task_store.repository or configure a github.com origin remote."
            )
        self.timeout_seconds = timeout_seconds

        if cache is None:
            # Delayed import avoids a module cycle: cache.py imports the stable
            # representation constants declared above.
            from projectctl.integrations.github.cache import GitHubDerivedCache

            cache = GitHubDerivedCache(self.project_root)
        self.cache = cache

    def _execute(
        self,
        args: list[str],
        *,
        input_text: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        cmd = [self.executable, *args]
        try:
            return subprocess.run(
                cmd,
                cwd=self.project_root,
                input=input_text,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise TaskStoreError(
                f"Failed to execute GitHub CLI command: {cmd!r}: {exc}"
            ) from exc

    @staticmethod
    def _decode_json_text(raw: str, args: list[str]) -> Any:
        value = raw.strip()
        if not value:
            return None
        try:
            return json.loads(value)
        except json.JSONDecodeError as exc:
            raise TaskStoreError(
                f"GitHub CLI returned non-JSON output for {' '.join(args)}: "
                f"{value[:240]!r}"
            ) from exc

    @classmethod
    def _decode_json(
        cls,
        result: subprocess.CompletedProcess[str],
        args: list[str],
    ) -> Any:
        return cls._decode_json_text(result.stdout, args)

    @classmethod
    def _decode_included_response(
        cls,
        result: subprocess.CompletedProcess[str],
        args: list[str],
    ) -> GitHubGetResponse:
        raw = result.stdout.replace("\r\n", "\n")
        header_block, separator, body = raw.partition("\n\n")
        if not separator:
            raise TaskStoreError(
                "GitHub CLI conditional GET did not include an HTTP status/header block."
            )

        lines = header_block.splitlines()
        if not lines or not lines[0].startswith("HTTP/"):
            raise TaskStoreError(
                "GitHub CLI conditional GET returned an invalid HTTP status line."
            )
        status_parts = lines[0].split()
        if len(status_parts) < 2 or not status_parts[1].isdigit():
            raise TaskStoreError(
                f"GitHub CLI returned an invalid HTTP status line: {lines[0]!r}"
            )

        headers: dict[str, str] = {}
        for line in lines[1:]:
            if not line.strip() or ":" not in line:
                continue
            name, value = line.split(":", 1)
            headers[name.strip().casefold()] = value.strip()

        return GitHubGetResponse(
            status_code=int(status_parts[1]),
            headers=headers,
            payload=cls._decode_json_text(body, args),
        )

    def _run(self, args: list[str], *, input_text: str | None = None) -> Any:
        result = self._execute(args, input_text=input_text)
        if result.returncode != 0:
            message = (result.stderr or result.stdout or "unknown GitHub CLI error").strip()
            raise TaskStoreError(
                f"GitHub CLI command failed ({result.returncode}): "
                f"{' '.join(args)}: {message}"
            )
        return self._decode_json(result, args)

    @staticmethod
    def _safe_validator(value: str | None, *, name: str) -> str | None:
        if value is None:
            return None
        if "\r" in value or "\n" in value:
            raise TaskStoreError(
                f"Cached GitHub {name} validator contains a prohibited line break."
            )
        return value

    def _get_args(
        self,
        endpoint: str,
        *,
        paginate: bool = False,
        slurp: bool = False,
        include: bool = False,
        etag: str | None = None,
        last_modified: str | None = None,
    ) -> list[str]:
        args = [
            "api",
            "--hostname",
            "github.com",
            "--method",
            "GET",
            "-H",
            f"Accept: {GITHUB_ACCEPT}",
            "-H",
            f"X-GitHub-Api-Version: {GITHUB_API_VERSION}",
        ]
        if include:
            args.append("--include")

        safe_etag = self._safe_validator(etag, name="ETag")
        safe_last_modified = self._safe_validator(
            last_modified,
            name="Last-Modified",
        )
        if safe_etag is not None:
            args.extend(["-H", f"If-None-Match: {safe_etag}"])
        elif safe_last_modified is not None:
            args.extend(["-H", f"If-Modified-Since: {safe_last_modified}"])

        if paginate:
            args.append("--paginate")
        if slurp:
            args.append("--slurp")
        args.append(endpoint)
        return args

    def _record_cache_read(
        self,
        *,
        request,
        outcome: str,
        status_code: int | None,
        conditional_header: str | None,
    ) -> None:
        from projectctl.integrations.github.cache import cache_request_fingerprint

        record_event(
            self.project_root,
            "github.cache.read",
            {
                "repository": self.repository,
                "endpoint": request.endpoint,
                "request_fingerprint": cache_request_fingerprint(request),
                "outcome": outcome,
                "status_code": status_code,
                "conditional_header": conditional_header,
            },
        )

    def _conditional_get(self, endpoint: str) -> Any:
        from projectctl.integrations.github.cache import github_cache_request

        request = github_cache_request(
            repository=self.repository,
            endpoint=endpoint,
        )
        existing = self.cache.load(request)
        etag = existing.etag if existing is not None else None
        last_modified = existing.last_modified if existing is not None else None
        conditional_header = (
            "if-none-match"
            if etag is not None
            else "if-modified-since"
            if last_modified is not None
            else None
        )
        args = self._get_args(
            endpoint,
            include=True,
            etag=etag,
            last_modified=last_modified,
        )
        result = self._execute(args)

        # Provider/transport failures that do not contain a parseable HTTP
        # response are errors even when a cache entry exists. Cached data is
        # never used as an outage fallback.
        if result.returncode != 0 and not result.stdout.lstrip().startswith("HTTP/"):
            self._record_cache_read(
                request=request,
                outcome="provider_error",
                status_code=None,
                conditional_header=conditional_header,
            )
            message = (result.stderr or result.stdout or "unknown GitHub CLI error").strip()
            raise TaskStoreError(
                f"GitHub CLI command failed ({result.returncode}): "
                f"{' '.join(args)}: {message}"
            )

        response = self._decode_included_response(result, args)

        if response.status_code == 304:
            if existing is None or conditional_header is None:
                self._record_cache_read(
                    request=request,
                    outcome="provider_error",
                    status_code=304,
                    conditional_header=conditional_header,
                )
                raise TaskStoreError(
                    "GitHub returned 304 Not Modified without a matching cached validator."
                )
            updated = self.cache.revalidate(
                request,
                validated_at=utc_now(),
                etag=response.headers.get("etag"),
                last_modified=response.headers.get("last-modified"),
            )
            self._record_cache_read(
                request=request,
                outcome="revalidated_304",
                status_code=304,
                conditional_header=conditional_header,
            )
            return updated.payload

        if result.returncode != 0 or response.status_code != 200:
            self._record_cache_read(
                request=request,
                outcome="provider_error",
                status_code=response.status_code,
                conditional_header=conditional_header,
            )
            message = (result.stderr or "GitHub API request failed").strip()
            raise TaskStoreError(
                f"GitHub CLI GET failed with HTTP {response.status_code}: "
                f"{endpoint}: {message}"
            )

        if not isinstance(response.payload, (dict, list)):
            self._record_cache_read(
                request=request,
                outcome="provider_error",
                status_code=200,
                conditional_header=conditional_header,
            )
            raise TaskStoreError(
                "GitHub GET returned a JSON value that cannot be stored in the derived cache."
            )

        observed_at = utc_now()
        self.cache.store(
            request,
            response.payload,
            observed_at=observed_at,
            etag=response.headers.get("etag"),
            last_modified=response.headers.get("last-modified"),
        )
        self._record_cache_read(
            request=request,
            outcome="miss_200" if existing is None else "refreshed_200",
            status_code=200,
            conditional_header=conditional_header,
        )
        return response.payload

    @staticmethod
    def issue_list(payload: Any) -> list[dict[str, Any]]:
        if payload is None:
            return []
        if isinstance(payload, dict):
            return [payload] if "number" in payload else []
        if not isinstance(payload, list):
            raise TaskStoreError("Unsupported GitHub Issues JSON response shape.")

        result: list[dict[str, Any]] = []
        for item in payload:
            if isinstance(item, dict):
                result.append(item)
            elif isinstance(item, list):
                result.extend(value for value in item if isinstance(value, dict))
            else:
                raise TaskStoreError("Unsupported GitHub Issues pagination shape.")
        return result

    def version(self) -> str | None:
        result = subprocess.run(
            [self.executable, "--version"],
            cwd=self.project_root,
            capture_output=True,
            text=True,
            timeout=self.timeout_seconds,
            check=False,
        )
        if result.returncode != 0:
            return None
        first = (result.stdout or result.stderr).strip().splitlines()
        return first[0].strip() if first else None

    def repository_info(self) -> dict[str, Any]:
        payload = self._conditional_get(f"repos/{self.repository}")
        if not isinstance(payload, dict):
            raise TaskStoreError("GitHub repository endpoint returned an invalid payload.")
        return payload

    def list_all(self) -> list[dict[str, Any]]:
        # M3.1c2 intentionally leaves multi-page aggregate reads unconditional.
        # One validator must not be treated as proof for an entire
        # --paginate/--slurp aggregate. M3.1c3 owns page-aware snapshot reuse.
        payload = self._run(
            self._get_args(
                f"repos/{self.repository}/issues?state=all&per_page=100",
                paginate=True,
                slurp=True,
            )
        )
        return [
            issue
            for issue in self.issue_list(payload)
            if "pull_request" not in issue
        ]

    @staticmethod
    def _issue_number(issue_number: str | int) -> int:
        value = str(issue_number).strip()
        if value.startswith("gh-"):
            value = value[3:]
        if value.startswith("#"):
            value = value[1:]
        if not value.isdigit() or int(value) <= 0:
            raise TaskStoreError(f"Invalid GitHub issue id: {issue_number!r}")
        return int(value)

    def _list_issue_relation(
        self,
        issue_number: str | int,
        suffix: str,
    ) -> list[dict[str, Any]]:
        number = self._issue_number(issue_number)
        payload = self._run(
            self._get_args(
                f"repos/{self.repository}/issues/{number}/{suffix}?per_page=100",
                paginate=True,
                slurp=True,
            )
        )
        return self.issue_list(payload)

    def list_blocked_by(self, issue_number: str | int) -> list[dict[str, Any]]:
        return self._list_issue_relation(
            issue_number,
            "dependencies/blocked_by",
        )

    def list_sub_issues(self, issue_number: str | int) -> list[dict[str, Any]]:
        return self._list_issue_relation(
            issue_number,
            "sub_issues",
        )

    def show(self, issue_number: str | int) -> dict[str, Any]:
        number = self._issue_number(issue_number)
        payload = self._conditional_get(
            f"repos/{self.repository}/issues/{number}"
        )
        if not isinstance(payload, dict) or not payload.get("number"):
            raise TaskStoreError(f"GitHub issue not found: {issue_number}")
        if "pull_request" in payload:
            raise TaskStoreError(
                f"GitHub item #{number} is a pull request, not an issue task."
            )
        return payload

    def ensure_label(
        self,
        name: str,
        *,
        color: str,
        description: str,
    ) -> None:
        endpoint = f"repos/{self.repository}/labels"
        args = [
            "api",
            "--hostname",
            "github.com",
            "--method",
            "POST",
            endpoint,
            "--input",
            "-",
        ]
        payload = json.dumps(
            {"name": name, "color": color, "description": description},
            sort_keys=True,
        )
        result = self._execute(args, input_text=payload)
        if result.returncode == 0:
            return

        # Label creation is idempotent by observation. GitHub reports a
        # validation failure when the label already exists; do not infer that
        # from stderr text. Confirm the exact label through a GET instead.
        encoded = quote(name, safe="")
        existing = self._run(
            self._get_args(f"repos/{self.repository}/labels/{encoded}")
        )
        if not isinstance(existing, dict) or str(existing.get("name")) != name:
            message = (result.stderr or result.stdout or "label creation failed").strip()
            raise TaskStoreError(
                f"Could not ensure GitHub label {name!r}: {message}"
            )

    def add_issue_labels(
        self,
        issue_number: str | int,
        labels: list[str],
    ) -> dict[str, Any]:
        issue = self.show(issue_number)
        number = int(issue["number"])
        payload = self._run(
            [
                "api",
                "--hostname",
                "github.com",
                "--method",
                "POST",
                f"repos/{self.repository}/issues/{number}/labels",
                "--input",
                "-",
            ],
            input_text=json.dumps({"labels": labels}, sort_keys=True),
        )
        if not isinstance(payload, list):
            raise TaskStoreError("GitHub add-label response has an invalid shape.")
        return self.show(number)
