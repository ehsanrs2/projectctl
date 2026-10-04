import json
import os
import stat
from pathlib import Path

import pytest

from projectctl.core.errors import TaskStoreError
from projectctl.integrations.github.cache import GitHubDerivedCache, github_cache_request
from projectctl.integrations.github.client import GitHubIssuesClient


FAKE_GH = r'''#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
log_path = os.environ.get("FAKE_GH_LOG")
if log_path:
    with open(log_path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(args) + "\n")

def included(status, payload=None, *, etag=None, last_modified=None):
    reason = {200: "OK", 304: "Not Modified", 500: "Internal Server Error"}[status]
    print(f"HTTP/2.0 {status} {reason}")
    if etag is not None:
        print("etag: " + etag)
    if last_modified is not None:
        print("last-modified: " + last_modified)
    print()
    if payload is not None:
        print(json.dumps(payload))

if args == ["--version"]:
    print("gh version 2.99.0")
    raise SystemExit(0)

if args[:5] == ["api", "--hostname", "github.com", "--method", "GET"]:
    endpoint = args[-1]

    if endpoint == "repos/acme/widget":
        if 'If-None-Match: "repo-v1"' in args:
            included(304, etag='"repo-v1"')
            print("gh: HTTP 304", file=sys.stderr)
            raise SystemExit(1)
        included(
            200,
            {"full_name": "acme/widget"},
            etag='"repo-v1"',
            last_modified="Sun, 04 Oct 2026 12:00:00 GMT",
        )
        raise SystemExit(0)

    if endpoint == "repos/acme/widget/issues/7":
        if 'If-None-Match: "issue-7-v1"' in args:
            included(304, etag='"issue-7-v1"')
            print("gh: HTTP 304", file=sys.stderr)
            raise SystemExit(1)
        included(
            200,
            {"number": 7, "title": "Cached", "state": "open", "labels": []},
            etag='"issue-7-v1"',
            last_modified="Sun, 04 Oct 2026 12:01:00 GMT",
        )
        raise SystemExit(0)

    if endpoint == "repos/acme/widget/issues/8":
        if "If-Modified-Since: Sun, 04 Oct 2026 12:02:00 GMT" in args:
            included(304, last_modified="Sun, 04 Oct 2026 12:02:00 GMT")
            raise SystemExit(0)
        included(
            200,
            {"number": 8, "title": "Last modified", "state": "open", "labels": []},
            last_modified="Sun, 04 Oct 2026 12:02:00 GMT",
        )
        raise SystemExit(0)

    if endpoint == "repos/acme/widget/issues/9":
        if 'If-None-Match: "issue-9-v1"' in args:
            included(500, {"message": "boom"})
            print("gh: Internal Server Error (HTTP 500)", file=sys.stderr)
            raise SystemExit(1)
        included(
            200,
            {"number": 9, "title": "Do not fallback", "state": "open", "labels": []},
            etag='"issue-9-v1"',
        )
        raise SystemExit(0)

    if endpoint == "repos/acme/widget/issues/10":
        included(304, etag='"orphan"')
        raise SystemExit(0)

    if endpoint.startswith("repos/acme/widget/issues?"):
        print(json.dumps([[
            {"number": 11, "title": "Page", "state": "open", "labels": []}
        ]]))
        raise SystemExit(0)

print("unsupported: " + " ".join(args), file=sys.stderr)
raise SystemExit(2)
'''


def fake_gh(tmp_path: Path) -> Path:
    path = tmp_path / "gh"
    path.write_text(FAKE_GH)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return path


def client(tmp_path: Path) -> GitHubIssuesClient:
    return GitHubIssuesClient(
        tmp_path,
        repository="acme/widget",
        executable=str(fake_gh(tmp_path)),
    )


def read_log(path: Path) -> list[list[str]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_200_then_304_reuses_payload_and_advances_validation(
    tmp_path: Path,
    monkeypatch,
):
    log = tmp_path / "gh.log"
    monkeypatch.setenv("FAKE_GH_LOG", str(log))
    events = []
    monkeypatch.setattr(
        "projectctl.integrations.github.client.record_event",
        lambda _root, event_type, payload: events.append((event_type, payload)),
    )

    value = client(tmp_path)
    first_payload = value.show(7)

    cache = GitHubDerivedCache(tmp_path)
    request = github_cache_request(
        repository="acme/widget",
        endpoint="repos/acme/widget/issues/7",
    )
    first = cache.load(request)
    assert first is not None
    assert first.etag == '"issue-7-v1"'

    second_payload = value.show(7)
    second = cache.load(request)
    assert second is not None

    assert second_payload == first_payload
    assert second.payload == first.payload
    assert second.payload_digest == first.payload_digest
    assert second.observed_at == first.observed_at
    assert second.validated_at >= first.validated_at

    calls = read_log(log)
    second_call = calls[-1]
    assert 'If-None-Match: "issue-7-v1"' in second_call
    assert not any(arg.startswith("If-Modified-Since:") for arg in second_call)

    assert [payload["outcome"] for _, payload in events] == [
        "miss_200",
        "revalidated_304",
    ]


def test_last_modified_is_used_when_etag_is_absent(tmp_path: Path, monkeypatch):
    log = tmp_path / "gh.log"
    monkeypatch.setenv("FAKE_GH_LOG", str(log))

    value = client(tmp_path)
    assert value.show(8)["number"] == 8
    assert value.show(8)["number"] == 8

    second_call = read_log(log)[-1]
    assert (
        "If-Modified-Since: Sun, 04 Oct 2026 12:02:00 GMT"
        in second_call
    )
    assert not any(arg.startswith("If-None-Match:") for arg in second_call)


def test_provider_error_never_becomes_cache_fallback(
    tmp_path: Path,
    monkeypatch,
):
    events = []
    monkeypatch.setattr(
        "projectctl.integrations.github.client.record_event",
        lambda _root, event_type, payload: events.append((event_type, payload)),
    )

    value = client(tmp_path)
    assert value.show(9)["number"] == 9

    cache = GitHubDerivedCache(tmp_path)
    request = github_cache_request(
        repository="acme/widget",
        endpoint="repos/acme/widget/issues/9",
    )
    before = cache.load(request)
    assert before is not None

    with pytest.raises(TaskStoreError, match="HTTP 500"):
        value.show(9)

    after = cache.load(request)
    assert after == before
    assert events[-1][1]["outcome"] == "provider_error"
    assert events[-1][1]["status_code"] == 500


def test_304_without_matching_cache_validator_fails_closed(tmp_path: Path):
    value = client(tmp_path)
    with pytest.raises(TaskStoreError, match="without a matching cached validator"):
        value.show(10)


def test_repository_info_is_conditionally_revalidated(tmp_path: Path, monkeypatch):
    log = tmp_path / "gh.log"
    monkeypatch.setenv("FAKE_GH_LOG", str(log))
    value = client(tmp_path)

    assert value.repository_info()["full_name"] == "acme/widget"
    assert value.repository_info()["full_name"] == "acme/widget"

    assert 'If-None-Match: "repo-v1"' in read_log(log)[-1]


def test_paginated_aggregate_reads_remain_unconditional_in_m31c2(
    tmp_path: Path,
    monkeypatch,
):
    log = tmp_path / "gh.log"
    monkeypatch.setenv("FAKE_GH_LOG", str(log))
    value = client(tmp_path)

    assert [item["number"] for item in value.list_all()] == [11]

    call = read_log(log)[-1]
    assert "--paginate" in call
    assert "--slurp" in call
    assert "--include" not in call
    assert not any(arg.startswith("If-None-Match:") for arg in call)
    assert not any(arg.startswith("If-Modified-Since:") for arg in call)


def test_cached_validator_cannot_inject_additional_header_lines(tmp_path: Path):
    value = client(tmp_path)
    with pytest.raises(TaskStoreError, match="prohibited line break"):
        value._get_args(
            "repos/acme/widget/issues/7",
            include=True,
            etag='"good"\r\nX-Evil: true',
        )
