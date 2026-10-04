from __future__ import annotations

import json
import shutil
import subprocess
from urllib.parse import quote
from pathlib import Path
from typing import Any

from projectctl.core.errors import ProviderUnavailableError, TaskStoreError
from projectctl.integrations.github.repository import (
    infer_github_repository,
    normalize_github_repository,
)


GITHUB_API_VERSION = "2026-03-10"
GITHUB_ACCEPT = "application/vnd.github+json"


class GitHubIssuesClient:
    """Narrow wrapper around the authenticated `gh api` surface.

    ProjectCTL does not persist GitHub credentials. Authentication, host policy,
    and token storage remain owned by GitHub CLI.
    """

    def __init__(
        self,
        project_root: Path,
        *,
        repository: str | None = None,
        executable: str | None = None,
        timeout_seconds: int = 30,
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
    def _decode_json(result: subprocess.CompletedProcess[str], args: list[str]) -> Any:
        raw = result.stdout.strip()
        if not raw:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise TaskStoreError(
                f"GitHub CLI returned non-JSON output for {' '.join(args)}: "
                f"{raw[:240]!r}"
            ) from exc

    def _run(self, args: list[str], *, input_text: str | None = None) -> Any:
        result = self._execute(args, input_text=input_text)
        if result.returncode != 0:
            message = (result.stderr or result.stdout or "unknown GitHub CLI error").strip()
            raise TaskStoreError(
                f"GitHub CLI command failed ({result.returncode}): "
                f"{' '.join(args)}: {message}"
            )
        return self._decode_json(result, args)

    def _get_args(
        self,
        endpoint: str,
        *,
        paginate: bool = False,
        slurp: bool = False,
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
        if paginate:
            args.append("--paginate")
        if slurp:
            args.append("--slurp")
        args.append(endpoint)
        return args

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
        payload = self._run(self._get_args(f"repos/{self.repository}"))
        if not isinstance(payload, dict):
            raise TaskStoreError("GitHub repository endpoint returned an invalid payload.")
        return payload

    def list_all(self) -> list[dict[str, Any]]:
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
        payload = self._run(
            self._get_args(f"repos/{self.repository}/issues/{number}")
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
