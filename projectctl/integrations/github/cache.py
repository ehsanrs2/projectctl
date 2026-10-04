from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any

from projectctl.core.digest import digest
from projectctl.core.errors import TaskStoreError, UnsafePathError
from projectctl.integrations.github.client import GITHUB_ACCEPT, GITHUB_API_VERSION
from projectctl.schemas.github_cache import GitHubCacheEntry, GitHubCacheRequest


class GitHubCacheFreshness(StrEnum):
    FRESH = "fresh"
    STALE = "stale"


@dataclass(frozen=True)
class GitHubCacheLookup:
    entry: GitHubCacheEntry
    freshness: GitHubCacheFreshness
    age_seconds: float


def github_cache_request(
    *,
    repository: str,
    endpoint: str,
    paginated: bool = False,
    slurp: bool = False,
) -> GitHubCacheRequest:
    return GitHubCacheRequest(
        repository=repository,
        endpoint=endpoint,
        api_version=GITHUB_API_VERSION,
        accept=GITHUB_ACCEPT,
        paginated=paginated,
        slurp=slurp,
    )


def cache_request_fingerprint(request: GitHubCacheRequest) -> str:
    return digest(request)


def _fingerprint_hex(fingerprint: str) -> str:
    if ":" not in fingerprint:
        raise TaskStoreError("Invalid GitHub cache fingerprint.")
    algorithm, value = fingerprint.split(":", 1)
    if algorithm != "canonical-json-sha256-v1" or len(value) != 64:
        raise TaskStoreError("Unsupported GitHub cache fingerprint.")
    if any(char not in "0123456789abcdef" for char in value):
        raise TaskStoreError("Invalid GitHub cache fingerprint payload.")
    return value


class GitHubDerivedCache:
    """Local derived cache for GitHub REST representations.

    GitHub remains authoritative. Entries are disposable, integrity-checked
    artifacts under .projectctl/cache/github/v1 and never become task state.
    """

    def __init__(self, project_root: Path):
        self.project_root = project_root.resolve()
        self.cache_root = self.project_root / ".projectctl" / "cache" / "github" / "v1"

    def _safe_parent(self, request: GitHubCacheRequest) -> Path:
        owner, repository = request.repository.split("/", 1)
        parent = self.cache_root / owner / repository
        resolved_parent = parent.resolve(strict=False)
        if not resolved_parent.is_relative_to(self.project_root):
            raise UnsafePathError(
                f"GitHub cache path escapes project root: {resolved_parent}"
            )
        return parent

    def entry_path(self, request: GitHubCacheRequest) -> Path:
        fingerprint = cache_request_fingerprint(request)
        return self._safe_parent(request) / f"{_fingerprint_hex(fingerprint)}.json"

    def load(self, request: GitHubCacheRequest) -> GitHubCacheEntry | None:
        path = self.entry_path(request)
        if not path.exists():
            return None
        if path.is_symlink():
            raise UnsafePathError(f"GitHub cache entry must not be a symlink: {path}")
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            entry = GitHubCacheEntry.model_validate(raw)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            raise TaskStoreError(f"Invalid GitHub cache entry {path}: {exc}") from exc

        expected = cache_request_fingerprint(request)
        if entry.request_fingerprint != expected or entry.request != request:
            raise TaskStoreError(
                "GitHub cache entry request identity does not match requested representation."
            )
        return entry

    def lookup(
        self,
        request: GitHubCacheRequest,
        *,
        max_age_seconds: float,
        now: datetime | None = None,
    ) -> GitHubCacheLookup | None:
        if max_age_seconds < 0:
            raise ValueError("max_age_seconds must be non-negative.")
        entry = self.load(request)
        if entry is None:
            return None

        current = now or datetime.now(timezone.utc)
        if entry.validated_at > current:
            raise TaskStoreError(
                "GitHub cache validation timestamp is in the future; refusing freshness."
            )
        age = (current - entry.validated_at).total_seconds()
        freshness = (
            GitHubCacheFreshness.FRESH
            if age <= max_age_seconds
            else GitHubCacheFreshness.STALE
        )
        return GitHubCacheLookup(
            entry=entry,
            freshness=freshness,
            age_seconds=age,
        )

    def store(
        self,
        request: GitHubCacheRequest,
        payload: dict[str, Any] | list[Any],
        *,
        observed_at: datetime,
        validated_at: datetime | None = None,
        etag: str | None = None,
        last_modified: str | None = None,
    ) -> GitHubCacheEntry:
        entry = GitHubCacheEntry(
            request=request,
            request_fingerprint=cache_request_fingerprint(request),
            payload=payload,
            payload_digest=digest(payload),
            observed_at=observed_at,
            validated_at=validated_at or observed_at,
            etag=etag,
            last_modified=last_modified,
        )
        self._write(entry)
        return entry

    def revalidate(
        self,
        request: GitHubCacheRequest,
        *,
        validated_at: datetime,
        etag: str | None = None,
        last_modified: str | None = None,
    ) -> GitHubCacheEntry:
        existing = self.load(request)
        if existing is None:
            raise TaskStoreError(
                "Cannot revalidate a missing GitHub cache entry."
            )
        if validated_at < existing.validated_at:
            raise TaskStoreError(
                "GitHub cache revalidation cannot move validated_at backwards."
            )
        updated = existing.model_copy(
            update={
                "validated_at": validated_at,
                "etag": etag if etag is not None else existing.etag,
                "last_modified": (
                    last_modified
                    if last_modified is not None
                    else existing.last_modified
                ),
            }
        )
        # model_copy does not re-run validators; reconstruct before persistence.
        checked = GitHubCacheEntry.model_validate(updated.model_dump(mode="json"))
        self._write(checked)
        return checked

    def invalidate(self, request: GitHubCacheRequest) -> bool:
        path = self.entry_path(request)
        if not path.exists():
            return False
        if path.is_symlink():
            raise UnsafePathError(f"GitHub cache entry must not be a symlink: {path}")
        path.unlink()
        return True

    def invalidate_repository(self, repository: str) -> int:
        request = GitHubCacheRequest(
            repository=repository,
            endpoint=f"repos/{repository}",
        )
        parent = self._safe_parent(request)
        if not parent.exists():
            return 0
        resolved = parent.resolve()
        if not resolved.is_relative_to(self.project_root):
            raise UnsafePathError(
                f"GitHub cache repository path escapes project root: {resolved}"
            )
        count = 0
        for path in sorted(parent.glob("*.json")):
            if path.is_symlink():
                raise UnsafePathError(
                    f"GitHub cache entry must not be a symlink: {path}"
                )
            path.unlink()
            count += 1
        return count

    def _write(self, entry: GitHubCacheEntry) -> None:
        path = self.entry_path(entry.request)
        parent = path.parent
        parent.mkdir(parents=True, exist_ok=True)
        resolved_parent = parent.resolve()
        if not resolved_parent.is_relative_to(self.project_root):
            raise UnsafePathError(
                f"GitHub cache parent escapes project root: {resolved_parent}"
            )

        data = json.dumps(
            entry.model_dump(mode="json"),
            sort_keys=True,
            indent=2,
            ensure_ascii=False,
        ) + "\n"

        tmp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=parent,
                prefix=".tmp-",
                suffix=".json",
                delete=False,
            ) as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
                tmp_path = Path(handle.name)
            os.replace(tmp_path, path)
            tmp_path = None
        finally:
            if tmp_path is not None:
                tmp_path.unlink(missing_ok=True)
