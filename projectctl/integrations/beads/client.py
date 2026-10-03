from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from projectctl.core.errors import ProviderUnavailableError, TaskStoreError


class BeadsClient:
    """Small, non-shelling wrapper around the supported `bd --json` CLI surface."""

    def __init__(self, project_root: Path, executable: str | None = None, timeout_seconds: int = 30):
        self.project_root = project_root.resolve()
        self.executable = executable or shutil.which("bd")
        self.timeout_seconds = timeout_seconds
        if not self.executable:
            raise ProviderUnavailableError("Beads executable `bd` was not found in PATH.")

    def _run(self, args: list[str], *, expect_json: bool = True) -> Any:
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
            raise TaskStoreError(f"Failed to execute Beads command: {cmd!r}: {exc}") from exc

        if result.returncode != 0:
            message = (result.stderr or result.stdout or "unknown Beads error").strip()
            raise TaskStoreError(f"Beads command failed ({result.returncode}): {' '.join(args)}: {message}")

        if not expect_json:
            return result.stdout

        raw = result.stdout.strip()
        if not raw:
            # Some mutating Beads commands historically returned no JSON despite --json.
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise TaskStoreError(
                f"Beads returned non-JSON output for {' '.join(args)}: {raw[:240]!r}"
            ) from exc

    @staticmethod
    def issue_list(payload: Any) -> list[dict[str, Any]]:
        if payload is None:
            return []
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        if isinstance(payload, dict):
            if "id" in payload:
                return [payload]
            for key in ("issues", "ready", "blocked", "results", "items"):
                value = payload.get(key)
                if isinstance(value, list):
                    return [item for item in value if isinstance(item, dict)]
        raise TaskStoreError("Unsupported Beads JSON response shape.")

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
        return (result.stdout or result.stderr).strip() or None

    def list_all(self) -> list[dict[str, Any]]:
        return self.issue_list(self._run(["list", "--json"]))

    def list_ready(self) -> list[dict[str, Any]]:
        return self.issue_list(self._run(["ready", "--json"]))

    def list_blocked(self) -> list[dict[str, Any]]:
        return self.issue_list(self._run(["blocked", "--json"]))

    def show(self, issue_id: str) -> dict[str, Any]:
        issues = self.issue_list(self._run(["show", issue_id, "--json"]))
        if not issues:
            raise TaskStoreError(f"Beads issue not found: {issue_id}")
        return issues[0]

    def create_issue(
        self,
        *,
        title: str,
        description: str,
        issue_type: str = "task",
        priority: int = 2,
        labels: list[str] | None = None,
    ) -> str:
        args = [
            "create",
            title,
            "--description",
            description,
            "--type",
            issue_type,
            "--priority",
            str(priority),
        ]
        clean_labels = sorted({label.strip() for label in (labels or []) if label.strip()})
        if clean_labels:
            args.extend(["-l", ",".join(clean_labels)])
        args.append("--json")
        payload = self._run(args)
        issues = self.issue_list(payload)
        if not issues or not issues[0].get("id"):
            raise TaskStoreError("Beads create did not return an issue id.")
        return str(issues[0]["id"])

    def close_issue(self, issue_id: str, reason: str) -> None:
        self._run(["close", issue_id, "--reason", reason], expect_json=False)

    def list_dependencies(self, issue_id: str) -> list[dict[str, Any]]:
        payload = self._run(["dep", "list", issue_id, "--json"])
        if payload is None:
            return []
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        if isinstance(payload, dict):
            for key in ("dependencies", "deps", "items", "results"):
                value = payload.get(key)
                if isinstance(value, list):
                    return [item for item in value if isinstance(item, dict)]
            if "id" in payload or "depends_on_id" in payload:
                return [payload]
        raise TaskStoreError(f"Unsupported dependency JSON response for {issue_id}.")

    def ensure_blocking_dependency(self, issue_id: str, depends_on_id: str) -> bool:
        """Ensure `issue_id` depends on `depends_on_id`. Returns True if created."""
        for dep in self.list_dependencies(issue_id):
            dep_id = dep.get("depends_on_id") or dep.get("id") or dep.get("target_id")
            dep_type = dep.get("dependency_type") or dep.get("type")
            if str(dep_id) == depends_on_id and dep_type in {"blocks", "block", "blocking"}:
                return False
        # Do not require JSON here; some supported Beads releases return an empty body.
        self._run(["dep", "add", issue_id, depends_on_id], expect_json=False)
        return True
