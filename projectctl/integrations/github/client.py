from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from projectctl.core.errors import ProviderUnavailableError, TaskStoreError
from projectctl.integrations.github.repository import infer_github_repository


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
        self.repository = (repository or infer_github_repository(self.project_root) or "").strip()
        if not self.repository or self.repository.count("/") != 1:
            raise TaskStoreError(
                "GitHub task store requires an owner/repository identity. "
                "Set task_store.repository or configure a github.com origin remote."
            )
        self.timeout_seconds = timeout_seconds

    def _run(self, args: list[str]) -> Any:
        cmd = [self.executable, *args]
        try:
            result = subprocess.run(
                cmd,
                cwd=self.project_root,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise TaskStoreError(
                f"Failed to execute GitHub CLI command: {cmd!r}: {exc}"
            ) from exc
        if result.returncode != 0:
            message = (result.stderr or result.stdout or "unknown GitHub CLI error").strip()
            raise TaskStoreError(
                f"GitHub CLI command failed ({result.returncode}): "
                f"{' '.join(args)}: {message}"
            )
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
        payload = self._run(["api", "--method", "GET", f"repos/{self.repository}"])
        if not isinstance(payload, dict):
            raise TaskStoreError("GitHub repository endpoint returned an invalid payload.")
        return payload

    def list_all(self) -> list[dict[str, Any]]:
        payload = self._run(
            [
                "api",
                "--method",
                "GET",
                "--paginate",
                "--slurp",
                f"repos/{self.repository}/issues?state=all&per_page=100",
            ]
        )
        return [
            issue
            for issue in self.issue_list(payload)
            if "pull_request" not in issue
        ]

    def show(self, issue_number: str | int) -> dict[str, Any]:
        value = str(issue_number).strip()
        if value.startswith("gh-"):
            value = value[3:]
        if value.startswith("#"):
            value = value[1:]
        if not value.isdigit() or int(value) <= 0:
            raise TaskStoreError(f"Invalid GitHub issue id: {issue_number!r}")
        payload = self._run(
            ["api", "--method", "GET", f"repos/{self.repository}/issues/{int(value)}"]
        )
        if not isinstance(payload, dict) or not payload.get("number"):
            raise TaskStoreError(f"GitHub issue not found: {issue_number}")
        if "pull_request" in payload:
            raise TaskStoreError(
                f"GitHub item #{value} is a pull request, not an issue task."
            )
        return payload
