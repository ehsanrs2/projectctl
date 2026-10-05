import json
from pathlib import Path

import pytest
import yaml
from projectctl.core.enums import TaskStatus
from projectctl.core.errors import ProviderUnavailableError, RepositoryContractError, TaskStoreError
from projectctl.integrations.linear.client import LinearIssuesClient
from projectctl.integrations.linear.task_store import LinearIssuesTaskStore
from projectctl.project.adoption import plan_adoption
from projectctl.project.loader import load_project_config
from projectctl.schemas.onboarding import ProjectInspection


TEAM_ID = "9cfb482a-81e3-4154-b5b9-2c805e70a02d"


class FakeLinearClient(LinearIssuesClient):
    def __init__(self, root: Path, responses: list[dict]):
        self.responses = list(responses)
        self.requests: list[dict] = []
        super().__init__(
            root,
            team_id=TEAM_ID,
            api_key="lin_api_test",
        )

    def _http_post(self, body: bytes):
        self.requests.append(json.loads(body.decode("utf-8")))
        if not self.responses:
            raise AssertionError("Unexpected Linear request")
        payload = self.responses.pop(0)
        return 200, json.dumps(payload).encode("utf-8")


def page(nodes, *, has_next=False, cursor=None):
    return {
        "data": {
            "team": {
                "id": TEAM_ID,
                "name": "Platform",
                "issues": {
                    "nodes": nodes,
                    "pageInfo": {
                        "hasNextPage": has_next,
                        "endCursor": cursor,
                    },
                },
            }
        }
    }


def issue(
    identifier: str,
    *,
    uuid: str,
    state_type: str,
    state_name: str,
    priority: int = 0,
    assignee: str | None = None,
):
    return {
        "id": uuid,
        "identifier": identifier,
        "title": f"Work on {identifier}",
        "priority": priority,
        "createdAt": "2026-10-04T10:00:00.000Z",
        "updatedAt": "2026-10-04T11:00:00.000Z",
        "archivedAt": None,
        "state": {
            "id": f"state-{state_type}",
            "name": state_name,
            "type": state_type,
        },
        "assignee": (
            {"id": "user-1", "name": assignee}
            if assignee is not None
            else None
        ),
    }


def test_linear_client_uses_cursor_pagination_and_exact_team_identity(tmp_path: Path):
    first = [
        issue(
            "ENG-1",
            uuid="11111111-1111-1111-1111-111111111111",
            state_type="unstarted",
            state_name="Todo",
        )
    ]
    second = [
        issue(
            "ENG-2",
            uuid="22222222-2222-2222-2222-222222222222",
            state_type="completed",
            state_name="Done",
        )
    ]
    client = FakeLinearClient(
        tmp_path,
        [
            page(first, has_next=True, cursor="cursor-1"),
            page(second, has_next=False, cursor=None),
        ],
    )

    values = client.list_all(page_size=50)

    assert [item["identifier"] for item in values] == ["ENG-1", "ENG-2"]
    assert client.requests[0]["variables"]["after"] is None
    assert client.requests[1]["variables"]["after"] == "cursor-1"
    assert client.requests[0]["variables"]["teamId"] == TEAM_ID


def test_linear_graphql_errors_fail_closed_even_with_partial_data(tmp_path: Path):
    client = FakeLinearClient(
        tmp_path,
        [
            {
                "data": {"team": {"id": TEAM_ID, "name": "Platform"}},
                "errors": [{"message": "field access denied"}],
            }
        ],
    )

    with pytest.raises(TaskStoreError, match="field access denied"):
        client.team_info()


def test_linear_client_does_not_accept_two_credential_sources(tmp_path: Path):
    with pytest.raises(ProviderUnavailableError, match="only one"):
        LinearIssuesClient(
            tmp_path,
            team_id=TEAM_ID,
            api_key="api-key",
            access_token="oauth-token",
        )


def test_linear_pagination_requires_progress_cursor(tmp_path: Path):
    client = FakeLinearClient(
        tmp_path,
        [page([], has_next=True, cursor=None)],
    )

    with pytest.raises(TaskStoreError, match="endCursor"):
        client.list_all()


class StoreClient:
    team_id = TEAM_ID

    def __init__(self):
        self.assignee = "Alice"

    def list_all(self):
        return [
            issue(
                "ENG-1",
                uuid="11111111-1111-1111-1111-111111111111",
                state_type="unstarted",
                state_name="Todo",
                priority=1,
                assignee=self.assignee,
            ),
            issue(
                "ENG-2",
                uuid="22222222-2222-2222-2222-222222222222",
                state_type="started",
                state_name="In Progress",
                priority=2,
            ),
            issue(
                "ENG-3",
                uuid="33333333-3333-3333-3333-333333333333",
                state_type="completed",
                state_name="Done",
                priority=3,
            ),
            issue(
                "ENG-4",
                uuid="44444444-4444-4444-4444-444444444444",
                state_type="canceled",
                state_name="Canceled",
                priority=4,
            ),
        ]

    def list_inverse_relations(self, _issue_id):
        return []

    def team_label_ids(self, _names):
        return {}

    def version(self):
        return "linear-graphql-test"


def test_linear_task_store_preserves_m32a_normalization_under_m32b(tmp_path: Path):
    client = StoreClient()
    store = LinearIssuesTaskStore(tmp_path, team_id=TEAM_ID, client=client)

    tasks = {task.id: task for task in store.list_all()}

    assert tasks["lin-ENG-1"].status == TaskStatus.READY
    assert tasks["lin-ENG-1"].priority == 10
    assert tasks["lin-ENG-1"].source.external_id == "11111111-1111-1111-1111-111111111111"
    assert tasks["lin-ENG-1"].team.assignees == ["Alice"]
    assert tasks["lin-ENG-2"].status == TaskStatus.RUNNING
    assert tasks["lin-ENG-3"].status == TaskStatus.DONE
    assert tasks["lin-ENG-4"].status == TaskStatus.CANCELLED

    assert [task.id for task in store.list_ready()] == ["lin-ENG-1"]


def test_linear_assignee_change_does_not_change_semantic_source_revision(tmp_path: Path):
    client = StoreClient()
    store = LinearIssuesTaskStore(tmp_path, team_id=TEAM_ID, client=client)

    first = store.snapshot()
    client.assignee = "Bob"
    second = store.snapshot()

    assert first.source_revision == second.source_revision
    assert first.tasks[0].team.assignees == ["Alice"]
    assert second.tasks[0].team.assignees == ["Bob"]


def inspection(tmp_path: Path) -> ProjectInspection:
    return ProjectInspection(
        project_root=str(tmp_path),
        classification="existing_unmanaged",
        confidence="high",
        repository_fingerprint="fingerprint",
        detected_task_systems=[],
    )


def test_linear_adoption_requires_and_normalizes_team_uuid(tmp_path: Path):
    plan = plan_adoption(
        inspection(tmp_path),
        task_store_provider="linear",
        task_store_team=TEAM_ID.upper(),
    )

    assert plan.task_store_provider == "linear"
    assert plan.task_store_repository is None
    assert plan.task_store_team == TEAM_ID
    assert "task_store_team" not in plan.unresolved_decisions


def test_linear_adoption_without_team_fails_closed_as_unresolved(tmp_path: Path):
    plan = plan_adoption(
        inspection(tmp_path),
        task_store_provider="linear",
    )
    assert "task_store_team" in plan.unresolved_decisions


def test_linear_adoption_rejects_non_uuid_team_identity(tmp_path: Path):
    with pytest.raises(RepositoryContractError, match="UUID"):
        plan_adoption(
            inspection(tmp_path),
            task_store_provider="linear",
            task_store_team="ENG",
        )


def test_linear_team_is_not_accepted_for_other_provider(tmp_path: Path):
    with pytest.raises(RepositoryContractError, match="only supported"):
        plan_adoption(
            inspection(tmp_path),
            task_store_provider="beads",
            task_store_team=TEAM_ID,
        )


def test_project_config_v3_upgrades_to_v7_without_rewrite(tmp_path: Path):
    ctl = tmp_path / ".projectctl"
    ctl.mkdir()
    path = ctl / "config.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "schema_kind": "projectctl.project_config",
                "schema_version": 3,
                "project": {"id": "demo"},
                "task_store": {
                    "provider": "github",
                    "repository": "acme/widget",
                    "cache_max_age_seconds": 17,
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    config = load_project_config(tmp_path)

    assert config.schema_version == 7
    assert config.task_store.repository == "acme/widget"
    assert config.task_store.team is None
    assert config.task_store.cache_max_age_seconds == 17
    assert config.code_transport.mode == "git_remote"
    assert config.code_transport.remote_identity == "github.com/acme/widget"
    assert config.code_delivery.mode == "direct_git"
    assert yaml.safe_load(path.read_text(encoding="utf-8"))["schema_version"] == 3
