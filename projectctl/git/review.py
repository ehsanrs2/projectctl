from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

from projectctl.core.errors import IntegrationError
from projectctl.git.remote import (
    normalize_configured_remote_identity,
    normalize_git_remote_identity,
)
from projectctl.schemas.delivery import ReviewReceipt, ReviewRequest


_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


def review_source_branch(run_id: str, candidate_commit: str) -> str:
    stem = _SAFE.sub("-", str(run_id).strip()).strip(".-")
    if not stem:
        raise IntegrationError("Review source branch requires a usable run id.")
    return f"projectctl/review/{stem[:64]}-{candidate_commit[:12]}"


class ReviewGitTransport:
    """Exact candidate branch publication and merged-target reconciliation."""

    def __init__(
        self,
        project_root: Path,
        *,
        remote_name: str,
        remote_identity: str,
        timeout_seconds: int = 60,
    ):
        self.project_root = project_root.resolve()
        self.remote_name = remote_name
        try:
            normalized = normalize_configured_remote_identity(remote_identity)
        except Exception as exc:
            raise IntegrationError(f"Invalid review remote identity: {exc}") from exc
        if not normalized:
            raise IntegrationError("Review delivery remote identity is empty.")
        self.remote_identity = normalized
        self.timeout_seconds = timeout_seconds

    def _git(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
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
            raise IntegrationError(f"Review Git command failed: {exc}") from exc
        if check and result.returncode != 0:
            message = (result.stderr or result.stdout or "git error").strip()
            raise IntegrationError(
                f"git {' '.join(args)} failed ({result.returncode}): {message}"
            )
        return result

    @staticmethod
    def _branch_ref(branch: str) -> str:
        value = str(branch).strip()
        if value.startswith("refs/heads/"):
            value = value[len("refs/heads/") :]
        if (
            not value
            or value.startswith("refs/")
            or ".." in value
            or value.startswith("/")
            or value.endswith("/")
        ):
            raise IntegrationError(f"Unsupported review branch: {branch!r}")
        return f"refs/heads/{value}"

    def _assert_remote_identity(self) -> None:
        url = self._git("remote", "get-url", self.remote_name).stdout.strip()
        try:
            observed = normalize_git_remote_identity(url)
        except Exception as exc:
            raise IntegrationError(
                f"Review remote URL is not a supported network Git remote: {exc}"
            ) from exc
        if observed != self.remote_identity:
            raise IntegrationError(
                "Review remote identity differs from code delivery config: "
                f"remote={observed or 'unknown'}, configured={self.remote_identity}."
            )

    def observe(self, branch: str) -> str | None:
        self._assert_remote_identity()
        ref = self._branch_ref(branch)
        result = self._git("ls-remote", "--refs", self.remote_name, ref)
        rows = [line for line in result.stdout.splitlines() if line.strip()]
        if not rows:
            return None
        if len(rows) != 1:
            raise IntegrationError(
                f"Review branch observation for {ref!r} returned {len(rows)} rows."
            )
        sha, observed_ref = rows[0].split("\t", 1)
        if observed_ref != ref:
            raise IntegrationError(
                f"Review branch observation returned unexpected ref {observed_ref!r}."
            )
        return sha

    def ensure_source(self, request: ReviewRequest) -> str:
        if request.remote_name != self.remote_name:
            raise IntegrationError("Review request remote name differs from configured remote.")
        if request.remote_identity != self.remote_identity:
            raise IntegrationError(
                "Review request remote identity differs from configured remote."
            )
        self._assert_remote_identity()

        candidate_exists = self._git(
            "cat-file", "-e", f"{request.candidate_commit}^{{commit}}", check=False
        )
        if candidate_exists.returncode != 0:
            raise IntegrationError(
                "Review candidate commit is not available in the local repository."
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
                "Review candidate is not a descendant of the verified base."
            )

        current = self.observe(request.source_ref)
        if current == request.candidate_commit:
            return current
        if current is not None:
            raise IntegrationError(
                "Deterministic ProjectCTL review source branch already points to "
                f"{current}, not the verified candidate."
            )

        ref = self._branch_ref(request.source_ref)
        result = self._git(
            "push",
            "--porcelain",
            f"--force-with-lease={ref}:",
            self.remote_name,
            f"{request.candidate_commit}:{ref}",
            check=False,
        )
        observed = self.observe(request.source_ref)
        if observed != request.candidate_commit:
            message = (result.stderr or result.stdout or "review source push failed").strip()
            raise IntegrationError(
                "Could not publish the exact review source candidate: "
                f"{message}; observed={observed or 'missing'}."
            )
        return observed

    def sync_merged_target(
        self,
        request: ReviewRequest,
        receipt: ReviewReceipt,
    ) -> str:
        if receipt.state != "merged":
            raise IntegrationError("Review target sync requires a merged review.")
        if receipt.head_commit != request.candidate_commit:
            raise IntegrationError(
                "Merged review head no longer equals the verified candidate."
            )
        self._assert_remote_identity()
        target_ref = self._branch_ref(request.target_ref)
        before = self.observe(request.target_ref)
        if before is None:
            raise IntegrationError("Merged review target branch is missing.")

        self._git("fetch", "--no-tags", self.remote_name, target_ref)
        fetched = self._git("rev-parse", "FETCH_HEAD").stdout.strip()
        after = self.observe(request.target_ref)
        if fetched != before or after != before:
            raise IntegrationError(
                "Review target changed while ProjectCTL was reconciling the merged result."
            )

        merge_commit = receipt.merge_commit
        if not merge_commit:
            if fetched == request.candidate_commit:
                merge_commit = request.candidate_commit
            else:
                raise IntegrationError(
                    "Merged review did not expose a merge commit identity and "
                    "the remote target is not the exact candidate."
                )

        merge_exists = self._git(
            "cat-file", "-e", f"{merge_commit}^{{commit}}", check=False
        )
        if merge_exists.returncode != 0:
            # The merge commit should be reachable from the fetched target; if
            # the server did not send it, fetch it explicitly once.
            self._git("fetch", "--no-tags", self.remote_name, merge_commit)
            merge_exists = self._git(
                "cat-file", "-e", f"{merge_commit}^{{commit}}", check=False
            )
        if merge_exists.returncode != 0:
            raise IntegrationError(
                "Review merge commit cannot be resolved locally."
            )

        if merge_commit == request.candidate_commit:
            pass
        else:
            row = self._git(
                "rev-list", "--parents", "-n", "1", merge_commit
            ).stdout.strip().split()
            parents = row[1:]
            if len(parents) != 2 or set(parents) != {
                request.base_commit,
                request.candidate_commit,
            }:
                raise IntegrationError(
                    "Merged review transformed the verified candidate or merged it "
                    "onto a different base. Squash/rebase/stale-base review merges "
                    "require explicit human re-verification."
                )

        in_target = self._git(
            "merge-base",
            "--is-ancestor",
            merge_commit,
            fetched,
            check=False,
        )
        if in_target.returncode != 0:
            raise IntegrationError(
                "Review merge commit is not reachable from the current remote target."
            )

        current_local = self._git("rev-parse", request.target_ref).stdout.strip()
        if current_local != fetched:
            can_ff = self._git(
                "merge-base", "--is-ancestor", current_local, fetched, check=False
            )
            if can_ff.returncode != 0:
                raise IntegrationError(
                    "Local integration target cannot fast-forward to the merged review target."
                )
            self._git("merge", "--ff-only", fetched)

        final = self._git("rev-parse", request.target_ref).stdout.strip()
        if final != fetched:
            raise IntegrationError(
                "Local integration target does not equal the reconciled remote review target."
            )
        return final
