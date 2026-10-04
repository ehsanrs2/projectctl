import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from projectctl.core.errors import TaskStoreError, UnsafePathError
from projectctl.integrations.github.cache import (
    GitHubCacheFreshness,
    GitHubDerivedCache,
    cache_request_fingerprint,
    github_cache_request,
)
from projectctl.schema_export import PUBLIC_SCHEMAS
from projectctl.schemas.github_cache import GitHubCacheEntry, GitHubCacheRequest


NOW = datetime(2026, 10, 4, 12, 0, tzinfo=timezone.utc)


def request(*, api_version="2026-03-10", accept="application/vnd.github+json"):
    return GitHubCacheRequest(
        repository="acme/widget",
        endpoint="repos/acme/widget/issues?state=all&per_page=100",
        api_version=api_version,
        accept=accept,
        paginated=True,
        slurp=True,
    )


def test_cache_request_factory_pins_current_representation():
    value = github_cache_request(
        repository="acme/widget",
        endpoint="repos/acme/widget/issues?state=all&per_page=100",
        paginated=True,
        slurp=True,
    )
    assert value.api_version == "2026-03-10"
    assert value.accept == "application/vnd.github+json"
    assert value.hostname == "github.com"
    assert value.method == "GET"


def test_cache_key_changes_with_representation():
    base = request()
    different_version = request(api_version="2022-11-28")
    different_accept = request(accept="application/json")

    assert cache_request_fingerprint(base) != cache_request_fingerprint(
        different_version
    )
    assert cache_request_fingerprint(base) != cache_request_fingerprint(
        different_accept
    )


def test_cache_request_rejects_cross_repository_endpoint():
    with pytest.raises(ValueError, match="configured repository"):
        GitHubCacheRequest(
            repository="acme/widget",
            endpoint="repos/other/repo/issues",
        )


def test_store_load_and_freshness(tmp_path: Path):
    cache = GitHubDerivedCache(tmp_path)
    req = request()
    payload = [{"number": 1, "title": "Task"}]

    written = cache.store(
        req,
        payload,
        observed_at=NOW,
        etag='"abc"',
        last_modified="Sun, 04 Oct 2026 12:00:00 GMT",
    )
    loaded = cache.load(req)
    assert loaded == written
    assert loaded.payload == payload

    fresh = cache.lookup(
        req,
        max_age_seconds=60,
        now=NOW + timedelta(seconds=30),
    )
    assert fresh is not None
    assert fresh.freshness == GitHubCacheFreshness.FRESH
    assert fresh.age_seconds == 30

    stale = cache.lookup(
        req,
        max_age_seconds=60,
        now=NOW + timedelta(seconds=61),
    )
    assert stale is not None
    assert stale.freshness == GitHubCacheFreshness.STALE


def test_revalidation_preserves_payload_and_advances_validation_time(tmp_path: Path):
    cache = GitHubDerivedCache(tmp_path)
    req = request()
    payload = [{"number": 1}]
    original = cache.store(
        req,
        payload,
        observed_at=NOW,
        etag='"v1"',
    )

    updated = cache.revalidate(
        req,
        validated_at=NOW + timedelta(minutes=5),
        etag='"v2"',
    )

    assert updated.payload == original.payload
    assert updated.payload_digest == original.payload_digest
    assert updated.observed_at == original.observed_at
    assert updated.validated_at == NOW + timedelta(minutes=5)
    assert updated.etag == '"v2"'


def test_tampered_payload_fails_closed(tmp_path: Path):
    cache = GitHubDerivedCache(tmp_path)
    req = request()
    cache.store(req, [{"number": 1}], observed_at=NOW)

    path = cache.entry_path(req)
    raw = json.loads(path.read_text())
    raw["payload"][0]["number"] = 999
    path.write_text(json.dumps(raw))

    with pytest.raises(TaskStoreError, match="payload digest"):
        cache.load(req)


def test_tampered_request_identity_fails_closed(tmp_path: Path):
    cache = GitHubDerivedCache(tmp_path)
    req = request()
    cache.store(req, [{"number": 1}], observed_at=NOW)

    path = cache.entry_path(req)
    raw = json.loads(path.read_text())
    raw["request"]["api_version"] = "2022-11-28"
    path.write_text(json.dumps(raw))

    with pytest.raises(TaskStoreError, match="request fingerprint"):
        cache.load(req)


def test_future_validation_timestamp_cannot_make_cache_immortal(tmp_path: Path):
    cache = GitHubDerivedCache(tmp_path)
    req = request()
    future = NOW + timedelta(hours=1)
    cache.store(
        req,
        [{"number": 1}],
        observed_at=NOW,
        validated_at=future,
    )

    with pytest.raises(TaskStoreError, match="future"):
        cache.lookup(req, max_age_seconds=3600, now=NOW)


def test_invalidate_is_idempotent(tmp_path: Path):
    cache = GitHubDerivedCache(tmp_path)
    req = request()
    cache.store(req, [{"number": 1}], observed_at=NOW)

    assert cache.invalidate(req) is True
    assert cache.invalidate(req) is False
    assert cache.load(req) is None


def test_repository_invalidation_only_removes_target_repository(tmp_path: Path):
    cache = GitHubDerivedCache(tmp_path)
    first = request()
    second = GitHubCacheRequest(
        repository="acme/other",
        endpoint="repos/acme/other/issues",
    )
    cache.store(first, [{"number": 1}], observed_at=NOW)
    cache.store(second, [{"number": 2}], observed_at=NOW)

    assert cache.invalidate_repository("acme/widget") == 1
    assert cache.load(first) is None
    assert cache.load(second) is not None


def test_cache_parent_symlink_escape_is_rejected(tmp_path: Path):
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir()
    ctl_cache = tmp_path / ".projectctl" / "cache"
    ctl_cache.mkdir(parents=True)
    (ctl_cache / "github").symlink_to(outside, target_is_directory=True)

    cache = GitHubDerivedCache(tmp_path)
    with pytest.raises(UnsafePathError, match="escapes project root"):
        cache.entry_path(request())


def test_cache_contracts_are_public():
    assert PUBLIC_SCHEMAS["github-cache-request.v1.schema.json"] is GitHubCacheRequest
    assert PUBLIC_SCHEMAS["github-cache-entry.v1.schema.json"] is GitHubCacheEntry


def test_tampered_validation_time_fails_integrity_check(tmp_path: Path):
    cache = GitHubDerivedCache(tmp_path)
    req = request()
    cache.store(
        req,
        [{"number": 1}],
        observed_at=NOW,
        validated_at=NOW,
        etag='"v1"',
    )

    path = cache.entry_path(req)
    raw = json.loads(path.read_text())
    raw["validated_at"] = (NOW + timedelta(days=30)).isoformat()
    path.write_text(json.dumps(raw))

    with pytest.raises(TaskStoreError, match="integrity digest"):
        cache.load(req)
