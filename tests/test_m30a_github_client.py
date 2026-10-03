import json
import os
import stat
from pathlib import Path

import pytest

from projectctl.core.errors import TaskStoreError
from projectctl.integrations.github.client import GitHubIssuesClient


FAKE_GH = r'''#!/usr/bin/env python3
import json, sys
args = sys.argv[1:]
if args == ["--version"]:
    print("gh version 2.99.0")
    raise SystemExit(0)
if args[:3] == ["api", "--method", "GET"]:
    endpoint = args[-1]
    if endpoint == "repos/acme/widget":
        print(json.dumps({"full_name": "acme/widget"}))
        raise SystemExit(0)
    if endpoint == "repos/acme/widget/issues/7":
        print(json.dumps({"number": 7, "title": "Issue", "state": "open", "labels": []}))
        raise SystemExit(0)
    if endpoint.startswith("repos/acme/widget/issues?"):
        print(json.dumps([
            [
                {"number": 7, "title": "Issue", "state": "open", "labels": []},
                {"number": 8, "title": "PR", "state": "open", "labels": [], "pull_request": {}}
            ],
            [
                {"number": 9, "title": "Second page", "state": "closed", "labels": []}
            ]
        ]))
        raise SystemExit(0)
print("unsupported: " + " ".join(args), file=sys.stderr)
raise SystemExit(2)
'''


def fake_gh(tmp_path: Path) -> Path:
    path = tmp_path / "gh"
    path.write_text(FAKE_GH)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return path


def test_github_client_flattens_pages_and_filters_pull_requests(tmp_path: Path):
    client = GitHubIssuesClient(
        tmp_path,
        repository="acme/widget",
        executable=str(fake_gh(tmp_path)),
    )
    assert client.repository_info()["full_name"] == "acme/widget"
    assert [item["number"] for item in client.list_all()] == [7, 9]
    assert client.show("gh-7")["number"] == 7
    assert client.version() == "gh version 2.99.0"


def test_github_client_rejects_invalid_issue_id_before_cli_call(tmp_path: Path):
    client = GitHubIssuesClient(
        tmp_path,
        repository="acme/widget",
        executable=str(fake_gh(tmp_path)),
    )
    with pytest.raises(TaskStoreError, match="Invalid GitHub issue id"):
        client.show("../secrets")
