import json
import subprocess
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import yaml

from projectctl.application.tasks import capture_task_snapshot
from projectctl.integrations.github.client import GitHubIssuesClient
from projectctl.integrations.github.task_store import GitHubIssuesTaskStore
from projectctl.project.loader import load_project_config
from projectctl.schema_export import PUBLIC_SCHEMAS
from projectctl.schemas.config import ProjectConfig, ProjectConfigV1, ProjectConfigV2


def issue(number: int):
    return {
        "number": number,
        "title": f"Issue {number}",
        "state": "open",
        "state_reason": None,
        "created_at": "2026-10-04T08:00:00Z",
        "updated_at": "2026-10-04T09:00:00Z",
        "repository_url": "https://api.github.com/repos/acme/widget",
        "html_url": f"https://github.com/acme/widget/issues/{number}",
        "labels": [],
        "milestone": None,
    }


class CountingClient(GitHubIssuesClient):
    def __init__(
        self,
        project_root: Path,
        *,
        issues: list[dict],
        cache_max_age_seconds: float = 60,
    ):
        self.remote_calls: list[str] = []
        self.mutations: list[tuple[str, list[str]]] = []
        self.issues = {int(item["number"]): dict(item) for item in issues}
        super().__init__(
            project_root,
            repository="acme/widget",
            executable="gh-test",
            cache_max_age_seconds=cache_max_age_seconds,
        )

    def version(self):
        return "gh version cache-scale-test"

    @staticmethod
    def _response(args, payload, *, etag):
        return subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout=(
                "HTTP/2.0 200 OK\n"
                f"etag: {etag}\n"
                "\n"
                + json.dumps(payload)
                + "\n"
            ),
            stderr="",
        )

    def _execute(self, args, *, input_text=None):
        endpoint = next(
            arg for arg in args if isinstance(arg, str) and arg.startswith("repos/")
        )
        method = args[args.index("--method") + 1] if "--method" in args else "GET"

        if method == "POST" and endpoint.endswith("/labels"):
            number = int(endpoint.split("/issues/", 1)[1].split("/", 1)[0])
            labels = json.loads(input_text or "{}").get("labels") or []
            current = self.issues[number]
            existing = {
                str(item.get("name"))
                for item in current.get("labels") or []
                if isinstance(item, dict)
            }
            for label in labels:
                if label not in existing:
                    current.setdefault("labels", []).append({"name": label})
            self.mutations.append((endpoint, list(labels)))
            return subprocess.CompletedProcess(
                args=args,
                returncode=0,
                stdout=json.dumps(current["labels"]),
                stderr="",
            )

        self.remote_calls.append(endpoint)

        if endpoint.startswith("repos/acme/widget/issues?"):
            query = parse_qs(urlsplit("https://example.invalid/?" + endpoint.split("?", 1)[1]).query)
            page = int(query.get("page", ["1"])[0])
            ordered = [self.issues[number] for number in sorted(self.issues)]
            start = (page - 1) * 100
            payload = ordered[start : start + 100]
            return self._response(args, payload, etag=f'"issues-page-{page}"')

        if "/dependencies/blocked_by?" in endpoint or "/sub_issues?" in endpoint:
            return self._response(args, [], etag=f'"relation-{abs(hash(endpoint))}"')

        if "/issues/" in endpoint:
            number = int(endpoint.rsplit("/", 1)[1])
            return self._response(
                args,
                self.issues[number],
                etag=f'"issue-{number}"',
            )

        if endpoint == "repos/acme/widget":
            return self._response(
                args,
                {"full_name": "acme/widget"},
                etag='"repo"',
            )

        raise AssertionError(f"Unexpected endpoint: {endpoint}")


def test_fresh_single_response_cache_hit_skips_remote_and_emits_telemetry(
    tmp_path: Path,
    monkeypatch,
):
    events = []
    monkeypatch.setattr(
        "projectctl.integrations.github.client.record_event",
        lambda _root, event_type, payload: events.append((event_type, payload)),
    )
    client = CountingClient(
        tmp_path,
        issues=[issue(1)],
        cache_max_age_seconds=60,
    )

    assert client.show(1)["number"] == 1
    assert len(client.remote_calls) == 1

    assert client.show(1)["number"] == 1
    assert len(client.remote_calls) == 1
    assert [payload["outcome"] for _, payload in events] == [
        "miss_200",
        "fresh_hit",
    ]


def test_issue_collection_is_cached_page_by_page(tmp_path: Path):
    client = CountingClient(
        tmp_path,
        issues=[issue(number) for number in range(1, 102)],
        cache_max_age_seconds=60,
    )

    first = client.list_all()
    assert len(first) == 101
    assert client.remote_calls == [
        "repos/acme/widget/issues?state=all&per_page=100",
        "repos/acme/widget/issues?state=all&per_page=100&page=2",
    ]

    second = client.list_all()
    assert [item["number"] for item in second] == [item["number"] for item in first]
    assert len(client.remote_calls) == 2


def test_repeated_snapshot_eliminates_relation_remote_fanout_within_freshness_window(
    tmp_path: Path,
):
    count = 25
    client = CountingClient(
        tmp_path,
        issues=[issue(number) for number in range(1, count + 1)],
        cache_max_age_seconds=60,
    )
    store = GitHubIssuesTaskStore(tmp_path, client=client)

    first = store.snapshot()
    first_remote_count = len(client.remote_calls)
    assert len(first.tasks) == count
    assert first_remote_count == 1 + 2 * count

    second = store.snapshot()
    assert second.source_revision == first.source_revision
    assert len(client.remote_calls) == first_remote_count


def test_zero_freshness_forces_remote_revalidation_path(tmp_path: Path):
    client = CountingClient(
        tmp_path,
        issues=[issue(1)],
        cache_max_age_seconds=0,
    )
    client.show(1)
    first_count = len(client.remote_calls)
    client.show(1)

    assert first_count == 1
    assert len(client.remote_calls) == 2
    assert 'If-None-Match: "issue-1"' in client._get_args(
        "repos/acme/widget/issues/1",
        include=True,
        etag='"issue-1"',
    )


def test_successful_issue_mutation_invalidates_repository_cache(tmp_path: Path):
    client = CountingClient(
        tmp_path,
        issues=[issue(1)],
        cache_max_age_seconds=60,
    )

    assert client.show(1)["labels"] == []
    calls_before = len(client.remote_calls)

    updated = client.add_issue_labels(1, ["projectctl:completed"])

    assert {"name": "projectctl:completed"} in updated["labels"]
    assert len(client.remote_calls) == calls_before + 1
    # The pre-mutation show may use the fresh cache, but after repository
    # invalidation the final show must hit GitHub instead of reusing stale data.
    assert client.mutations == [
        ("repos/acme/widget/issues/1/labels", ["projectctl:completed"])
    ]


def test_project_config_v2_upgrades_to_v3_with_explicit_cache_policy(tmp_path: Path):
    ctl = tmp_path / ".projectctl"
    ctl.mkdir()
    (ctl / "config.yaml").write_text(
        yaml.safe_dump(
            {
                "schema_kind": "projectctl.project_config",
                "schema_version": 2,
                "project": {"id": "demo"},
                "task_store": {
                    "provider": "github",
                    "repository": "acme/widget",
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    config = load_project_config(tmp_path)

    assert config.schema_version == 3
    assert config.task_store.provider == "github"
    assert config.task_store.repository == "acme/widget"
    assert config.task_store.cache_max_age_seconds == 30


def test_project_config_cache_policy_can_disable_local_fresh_hits():
    config = ProjectConfig(
        project={"id": "demo"},
        task_store={
            "provider": "github",
            "repository": "acme/widget",
            "cache_max_age_seconds": 0,
        },
    )
    assert config.task_store.cache_max_age_seconds == 0


def test_project_config_contract_is_additively_versioned():
    assert PUBLIC_SCHEMAS["project-config.v1.schema.json"] is ProjectConfigV1
    assert PUBLIC_SCHEMAS["project-config.v2.schema.json"] is ProjectConfigV2
    assert PUBLIC_SCHEMAS["project-config.v3.schema.json"] is ProjectConfig
    assert ProjectConfigV1.model_fields["schema_version"].default == 1
    assert ProjectConfigV2.model_fields["schema_version"].default == 2
    assert ProjectConfig.model_fields["schema_version"].default == 3


def test_capture_task_snapshot_forwards_explicit_freshness_override(
    tmp_path: Path,
    monkeypatch,
):
    seen = []

    class Reader:
        def list_all(self):
            return []

        def list_ready(self):
            return []

        def list_blocked(self):
            return []

        def snapshot(self, *, tasks=None):
            from projectctl.schemas.task import TaskSnapshot

            return TaskSnapshot(
                provider="github",
                source_revision="test",
                tasks=tasks or [],
            )

    class Authority:
        reader = Reader()

    def fake_resolver(_root, *, read_cache_max_age_seconds=None):
        seen.append(read_cache_max_age_seconds)
        return Authority()

    monkeypatch.setattr(
        "projectctl.application.tasks.resolve_task_authority",
        fake_resolver,
    )

    capture_task_snapshot(
        tmp_path,
        read_cache_max_age_seconds=0,
    )
    assert seen == [0]
