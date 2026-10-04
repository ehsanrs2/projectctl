from __future__ import annotations

import os
import subprocess
from datetime import datetime
from pathlib import Path

from projectctl.core.errors import ClaimConflictError, TaskStoreError


class RemoteRefLease:
    """CAS-style remote Git-ref ownership using explicit force-with-lease.

    Acquisition expects the target ref to be absent. Release expects the target
    ref to equal the exact ownership SHA. Both operations are therefore guarded
    by the remote ref's current value rather than by a local tracking branch.
    """

    def __init__(
        self,
        project_root: Path,
        *,
        remote_name: str = "origin",
        timeout_seconds: int = 60,
    ):
        self.project_root = project_root.resolve()
        self.remote_name = remote_name
        self.timeout_seconds = timeout_seconds

    def _git(
        self,
        *args: str,
        input_text: str | None = None,
        check: bool = True,
        env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        merged_env = os.environ.copy()
        merged_env["GIT_TERMINAL_PROMPT"] = "0"
        if env:
            merged_env.update(env)
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
                input=input_text,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                check=False,
                env=merged_env,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise TaskStoreError(f"Git ref lease command failed: {exc}") from exc
        if check and result.returncode != 0:
            message = (result.stderr or result.stdout or "git error").strip()
            raise TaskStoreError(
                f"git {' '.join(args)} failed ({result.returncode}): {message}"
            )
        return result

    def remote_url(self) -> str:
        return self._git(
            "remote",
            "get-url",
            self.remote_name,
        ).stdout.strip()

    def probe_readable(self) -> str:
        result = self._git(
            "ls-remote",
            self.remote_name,
            "HEAD",
        )
        line = result.stdout.strip().splitlines()
        if not line:
            raise TaskStoreError(
                f"Git remote {self.remote_name!r} did not expose HEAD."
            )
        return line[0].split("\t", 1)[0]

    def observe(self, ref: str) -> str | None:
        result = self._git(
            "ls-remote",
            "--refs",
            self.remote_name,
            ref,
        )
        lines = [line for line in result.stdout.splitlines() if line.strip()]
        if not lines:
            return None
        if len(lines) != 1:
            raise TaskStoreError(
                f"Remote ref observation for {ref!r} returned {len(lines)} rows."
            )
        sha, observed_ref = lines[0].split("\t", 1)
        if observed_ref != ref:
            raise TaskStoreError(
                f"Remote ref observation returned unexpected ref {observed_ref!r}."
            )
        return sha

    def remote_branch(self, branch_name: str) -> str | None:
        value = branch_name
        if value.startswith("refs/heads/"):
            value = value[len("refs/heads/") :]
        if not value or value.startswith("refs/") or ".." in value:
            raise TaskStoreError(
                f"Unsupported integration target branch for remote claim: {branch_name!r}"
            )
        return self.observe(f"refs/heads/{value}")

    def create_marker_commit(
        self,
        *,
        base_commit: str,
        message: str,
        timestamp: datetime,
    ) -> str:
        tree = self._git("rev-parse", f"{base_commit}^{{tree}}").stdout.strip()
        if not tree:
            raise TaskStoreError(
                f"Could not resolve tree for claim base {base_commit}."
            )
        stamp = timestamp.isoformat()
        env = {
            "GIT_AUTHOR_NAME": "ProjectCTL",
            "GIT_AUTHOR_EMAIL": "projectctl@localhost",
            "GIT_COMMITTER_NAME": "ProjectCTL",
            "GIT_COMMITTER_EMAIL": "projectctl@localhost",
            "GIT_AUTHOR_DATE": stamp,
            "GIT_COMMITTER_DATE": stamp,
        }
        return self._git(
            "commit-tree",
            tree,
            "-p",
            base_commit,
            input_text=message.rstrip() + "\n",
            env=env,
        ).stdout.strip()

    def acquire(self, *, ref: str, ownership_sha: str) -> bool:
        result = self._git(
            "push",
            "--porcelain",
            f"--force-with-lease={ref}:",
            self.remote_name,
            f"{ownership_sha}:{ref}",
            check=False,
        )
        current = self.observe(ref)
        if current == ownership_sha:
            return True
        if current is not None:
            return False
        message = (result.stderr or result.stdout or "remote ref create failed").strip()
        raise TaskStoreError(
            f"Remote claim acquisition for {ref} is ambiguous or failed: {message}"
        )

    def release(self, *, ref: str, ownership_sha: str) -> None:
        result = self._git(
            "push",
            "--porcelain",
            f"--force-with-lease={ref}:{ownership_sha}",
            self.remote_name,
            f":{ref}",
            check=False,
        )
        current = self.observe(ref)
        if current is None:
            return
        if current != ownership_sha:
            raise ClaimConflictError(
                f"Remote claim ownership changed for {ref}; "
                f"expected {ownership_sha}, found {current}. Refusing deletion."
            )
        message = (result.stderr or result.stdout or "remote ref delete failed").strip()
        raise TaskStoreError(
            f"Remote claim release for {ref} failed while ownership still matches: {message}"
        )
