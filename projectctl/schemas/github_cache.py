from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import AwareDatetime, field_validator, model_validator

from projectctl.core.digest import digest
from projectctl.schemas.base import ProjectCtlModel


_REPOSITORY = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9][A-Za-z0-9_.-]*$"
)


class GitHubCacheRequest(ProjectCtlModel):
    schema_kind: Literal["projectctl.github_cache_request"] = (
        "projectctl.github_cache_request"
    )
    schema_version: Literal[1] = 1

    repository: str
    hostname: Literal["github.com"] = "github.com"
    method: Literal["GET"] = "GET"
    endpoint: str
    api_version: str = "2026-03-10"
    accept: str = "application/vnd.github+json"
    paginated: bool = False
    slurp: bool = False

    @field_validator("repository")
    @classmethod
    def validate_repository(cls, value: str) -> str:
        if not _REPOSITORY.fullmatch(value):
            raise ValueError("GitHub cache repository must use owner/repository form.")
        return value

    @model_validator(mode="after")
    def validate_endpoint(self):
        value = self.endpoint.strip()
        if "://" in value or value.startswith("/"):
            raise ValueError("GitHub cache endpoint must be an API-relative path.")
        prefix = f"repos/{self.repository}"
        if value != prefix and not value.startswith(prefix + "/") and not value.startswith(
            prefix + "?"
        ):
            raise ValueError(
                "GitHub cache endpoint must remain inside the configured repository."
            )
        return self


def github_cache_integrity_digest(
    *,
    request_fingerprint: str,
    payload_digest: str,
    observed_at: AwareDatetime,
    validated_at: AwareDatetime,
    etag: str | None,
    last_modified: str | None,
) -> str:
    return digest(
        {
            "request_fingerprint": request_fingerprint,
            "payload_digest": payload_digest,
            "observed_at": observed_at.isoformat(),
            "validated_at": validated_at.isoformat(),
            "etag": etag,
            "last_modified": last_modified,
        }
    )


class GitHubCacheEntry(ProjectCtlModel):
    schema_kind: Literal["projectctl.github_cache_entry"] = (
        "projectctl.github_cache_entry"
    )
    schema_version: Literal[1] = 1

    request: GitHubCacheRequest
    request_fingerprint: str
    payload: dict[str, Any] | list[Any]
    payload_digest: str
    integrity_digest: str
    observed_at: AwareDatetime
    validated_at: AwareDatetime
    etag: str | None = None
    last_modified: str | None = None

    @field_validator("etag", "last_modified")
    @classmethod
    def non_empty_optional_header(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("Cached validator headers cannot be empty strings.")
        return value

    @model_validator(mode="after")
    def validate_integrity(self):
        if self.request_fingerprint != digest(self.request):
            raise ValueError("GitHub cache request fingerprint does not match request.")
        if self.payload_digest != digest(self.payload):
            raise ValueError("GitHub cache payload digest does not match payload.")
        if self.validated_at < self.observed_at:
            raise ValueError("GitHub cache validated_at cannot precede observed_at.")
        expected_integrity = github_cache_integrity_digest(
            request_fingerprint=self.request_fingerprint,
            payload_digest=self.payload_digest,
            observed_at=self.observed_at,
            validated_at=self.validated_at,
            etag=self.etag,
            last_modified=self.last_modified,
        )
        if self.integrity_digest != expected_integrity:
            raise ValueError("GitHub cache integrity digest does not match provenance.")
        return self
