import json
from pathlib import Path

import pytest

from projectctl.core.enums import TaskStatus
from projectctl.core.errors import TaskStoreError
from projectctl.integrations.linear.client import LinearIssuesClient
from projectctl.integrations.linear.task_store import LinearIssuesTaskStore


TEAM_ID = "9cfb482a-81e3-4154-b5b9-2c805e70a02d"
OTHER_TEAM_ID = "11111111-2222-3333-4444-555555555555"


def issue(
    identifier: str,
    uuid: str,
    *,
    state_type: str = "unstarted",
    parent: dict | None = None,
):
    return {
        "id": uuid,
        "identifier": identifier,
        "title": f"Work on {identifier}",
        "priority": 0,
        "createdAt": "2026-10-05T01:00:00.000Z",
        "updatedAt": "2026-10-05T02:00:00.000Z",
        "archivedAt": None,
        "state": {
            "id": f"state-{state_type}",
            "name": state_type.title(),
            "type": state_type,
        },
        "assignee": None,
        "parent": parent,
    }


def relation(
    *,
    blocker_id: str,
    blocker_identifier: str,
    target_id: str,
    target_identifier: str,
    blocker_state: str = "unstarted",
    blocker_team: str = TEAM_ID,
    relation_type: str = "blocks",
):
    return {
        "id": f"rel-{blocker_id}-{target_id}",
        "type": relation_type,
        "issue": {
            "id": blocker_id,
            "identifier": blocker_identifier,
            "state": {"type": blocker_state},
            "team": {"id": blocker_team},
        },
        "relatedIssue": {
            "id": target_id,
            "identifier": target_identifier,
            "state": {"type": "unstarted"},
            "team": {"id": TEAM_ID},
        },
    }


class RelationshipClient:
    team_id = TEAM_ID

    def __init__(self, issues, inverse):
        self._issues = list(issues)
        self._inverse = {key: list(value) for key, value in inverse.items()}

    def list_all(self):
        return list(self._issues)

    def list_inverse_relations(self, issue_id):
        return list(self._inverse.get(issue_id, []))

    def version(self):
        return "linear-graphql-v2-test"


class FakeLinearClient(LinearIssuesClient):
    def __init__(self, root: Path, responses: list[dict]):
        self.responses = list(responses)
        self.requests: list[dict] = []
        super().__init__(root, team_id=TEAM_ID, api_key="lin_api_test")

    def _http_post(self, body: bytes):
        self.requests.append(json.loads(body.decode("utf-8")))
        if not self.responses:
            raise AssertionError("Unexpected Linear request")
        return 200, json.dumps(self.responses.pop(0)).encode("utf-8")


def inverse_page(issue_id, nodes, *, has_next=False, cursor=None):
    return {
        "data": {
            "issue": {
                "id": issue_id,
                "inverseRelations": {
                    "nodes": nodes,
                    "pageInfo": {
                        "hasNextPage": has_next,
                        "endCursor": cursor,
                    },
                },
            }
        }
    }


def test_inverse_relation_client_uses_independent_cursor_pagination(tmp_path: Path):
    target = "22222222-2222-2222-2222-222222222222"
    first = relation(
        blocker_id="11111111-1111-1111-1111-111111111111",
        blocker_identifier="ENG-1",
        target_id=target,
        target_identifier="ENG-2",
    )
    second = relation(
        blocker_id="33333333-3333-3333-3333-333333333333",
        blocker_identifier="ENG-3",
        target_id=target,
        target_identifier="ENG-2",
    )
    client = FakeLinearClient(
        tmp_path,
        [
            inverse_page(target, [first], has_next=True, cursor="r1"),
            inverse_page(target, [second]),
        ],
    )

    values = client.list_inverse_relations(target, page_size=10)

    assert len(values) == 2
    assert client.requests[0]["variables"] == {
        "issueId": target,
        "first": 10,
        "after": None,
    }
    assert client.requests[1]["variables"]["after"] == "r1"
    assert "inverseRelations" in client.requests[0]["query"]


def test_inverse_relation_client_rejects_identity_mismatch(tmp_path: Path):
    requested = "22222222-2222-2222-2222-222222222222"
    client = FakeLinearClient(
        tmp_path,
        [
            inverse_page(
                "99999999-9999-9999-9999-999999999999",
                [],
            )
        ],
    )

    with pytest.raises(TaskStoreError, match="identity"):
        client.list_inverse_relations(requested)


def test_unstarted_issue_without_blocker_becomes_ready(tmp_path: Path):
    a = issue("ENG-1", "11111111-1111-1111-1111-111111111111")
    store = LinearIssuesTaskStore(
        tmp_path,
        team_id=TEAM_ID,
        client=RelationshipClient([a], {}),
    )

    task = store.list_all()[0]

    assert task.status == TaskStatus.READY
    assert task.dependencies == []
    assert [item.id for item in store.list_ready()] == ["lin-ENG-1"]


def test_backlog_issue_remains_planned_even_without_blocker(tmp_path: Path):
    a = issue(
        "ENG-1",
        "11111111-1111-1111-1111-111111111111",
        state_type="backlog",
    )
    store = LinearIssuesTaskStore(
        tmp_path,
        team_id=TEAM_ID,
        client=RelationshipClient([a], {}),
    )

    task = store.list_all()[0]

    assert task.status == TaskStatus.PLANNED
    assert store.list_ready() == []


def test_local_open_blocker_creates_dependency_and_reverse_block_edge(tmp_path: Path):
    blocker = issue(
        "ENG-1",
        "11111111-1111-1111-1111-111111111111",
        state_type="started",
    )
    target = issue("ENG-2", "22222222-2222-2222-2222-222222222222")
    rel = relation(
        blocker_id=blocker["id"],
        blocker_identifier="ENG-1",
        target_id=target["id"],
        target_identifier="ENG-2",
        blocker_state="started",
    )
    client = RelationshipClient(
        [blocker, target],
        {target["id"]: [rel]},
    )
    store = LinearIssuesTaskStore(tmp_path, team_id=TEAM_ID, client=client)

    tasks = {task.id: task for task in store.list_all()}

    assert tasks["lin-ENG-2"].status == TaskStatus.BLOCKED
    assert tasks["lin-ENG-2"].dependencies == ["lin-ENG-1"]
    assert tasks["lin-ENG-1"].blocks == ["lin-ENG-2"]
    assert [task.id for task in store.list_blocked()] == ["lin-ENG-2"]


@pytest.mark.parametrize("terminal_state", ["completed", "canceled"])
def test_terminal_blocker_is_satisfied(tmp_path: Path, terminal_state: str):
    blocker = issue(
        "ENG-1",
        "11111111-1111-1111-1111-111111111111",
        state_type=terminal_state,
    )
    target = issue("ENG-2", "22222222-2222-2222-2222-222222222222")
    rel = relation(
        blocker_id=blocker["id"],
        blocker_identifier="ENG-1",
        target_id=target["id"],
        target_identifier="ENG-2",
        blocker_state=terminal_state,
    )
    store = LinearIssuesTaskStore(
        tmp_path,
        team_id=TEAM_ID,
        client=RelationshipClient([blocker, target], {target["id"]: [rel]}),
    )

    tasks = {task.id: task for task in store.list_all()}

    assert tasks["lin-ENG-2"].status == TaskStatus.READY
    assert tasks["lin-ENG-2"].dependencies == []


def test_cross_team_open_blocker_uses_stable_external_identity(tmp_path: Path):
    target = issue("ENG-2", "22222222-2222-2222-2222-222222222222")
    external_uuid = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    rel = relation(
        blocker_id=external_uuid,
        blocker_identifier="OPS-9",
        target_id=target["id"],
        target_identifier="ENG-2",
        blocker_team=OTHER_TEAM_ID,
    )
    store = LinearIssuesTaskStore(
        tmp_path,
        team_id=TEAM_ID,
        client=RelationshipClient([target], {target["id"]: [rel]}),
    )

    task = store.list_all()[0]

    assert task.status == TaskStatus.BLOCKED
    assert task.dependencies == [f"linear:{external_uuid}"]
    assert not task.human_decision_required
    assert any("external Linear blocker" in note for note in task.normalization_notes)


def test_missing_same_team_blocker_fails_closed_to_needs_decision(tmp_path: Path):
    target = issue("ENG-2", "22222222-2222-2222-2222-222222222222")
    blocker_uuid = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    rel = relation(
        blocker_id=blocker_uuid,
        blocker_identifier="ENG-1",
        target_id=target["id"],
        target_identifier="ENG-2",
        blocker_team=TEAM_ID,
    )
    store = LinearIssuesTaskStore(
        tmp_path,
        team_id=TEAM_ID,
        client=RelationshipClient([target], {target["id"]: [rel]}),
    )

    task = store.list_all()[0]

    assert task.status == TaskStatus.NEEDS_DECISION
    assert task.human_decision_required
    assert task.dependencies == [f"linear:{blocker_uuid}"]
    assert any("absent from the authority snapshot" in note for note in task.normalization_notes)


def test_inverse_blocks_target_mismatch_fails_closed(tmp_path: Path):
    target = issue("ENG-2", "22222222-2222-2222-2222-222222222222")
    rel = relation(
        blocker_id="11111111-1111-1111-1111-111111111111",
        blocker_identifier="ENG-1",
        target_id="99999999-9999-9999-9999-999999999999",
        target_identifier="OTHER-1",
    )
    store = LinearIssuesTaskStore(
        tmp_path,
        team_id=TEAM_ID,
        client=RelationshipClient([target], {target["id"]: [rel]}),
    )

    task = store.list_all()[0]

    assert task.status == TaskStatus.NEEDS_DECISION
    assert task.dependencies == []
    assert any("direction is ambiguous" in note for note in task.normalization_notes)


def test_non_blocking_relations_do_not_create_dependencies(tmp_path: Path):
    target = issue("ENG-2", "22222222-2222-2222-2222-222222222222")
    rel = relation(
        blocker_id="11111111-1111-1111-1111-111111111111",
        blocker_identifier="ENG-1",
        target_id=target["id"],
        target_identifier="ENG-2",
        relation_type="related",
    )
    store = LinearIssuesTaskStore(
        tmp_path,
        team_id=TEAM_ID,
        client=RelationshipClient([target], {target["id"]: [rel]}),
    )

    task = store.list_all()[0]

    assert task.status == TaskStatus.READY
    assert task.dependencies == []


def test_parent_child_hierarchy_is_separate_from_dependency_readiness(tmp_path: Path):
    parent_uuid = "11111111-1111-1111-1111-111111111111"
    child_uuid = "22222222-2222-2222-2222-222222222222"
    parent = issue("ENG-1", parent_uuid)
    child = issue(
        "ENG-2",
        child_uuid,
        parent={
            "id": parent_uuid,
            "identifier": "ENG-1",
            "team": {"id": TEAM_ID},
        },
    )
    store = LinearIssuesTaskStore(
        tmp_path,
        team_id=TEAM_ID,
        client=RelationshipClient([parent, child], {}),
    )

    tasks = {task.id: task for task in store.list_all()}

    assert tasks["lin-ENG-2"].hierarchy.parent == "lin-ENG-1"
    assert tasks["lin-ENG-1"].hierarchy.sub_issues == ["lin-ENG-2"]
    assert tasks["lin-ENG-2"].dependencies == []
    assert tasks["lin-ENG-2"].status == TaskStatus.READY


def test_external_parent_is_observational_not_blocking(tmp_path: Path):
    parent_uuid = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    child = issue(
        "ENG-2",
        "22222222-2222-2222-2222-222222222222",
        parent={
            "id": parent_uuid,
            "identifier": "OPS-1",
            "team": {"id": OTHER_TEAM_ID},
        },
    )
    store = LinearIssuesTaskStore(
        tmp_path,
        team_id=TEAM_ID,
        client=RelationshipClient([child], {}),
    )

    task = store.list_all()[0]

    assert task.hierarchy.parent == f"linear:{parent_uuid}"
    assert task.status == TaskStatus.READY
    assert task.dependencies == []


def test_local_dependency_cycle_requires_human_decision(tmp_path: Path):
    a = issue("ENG-1", "11111111-1111-1111-1111-111111111111")
    b = issue("ENG-2", "22222222-2222-2222-2222-222222222222")
    a_blocked_by_b = relation(
        blocker_id=b["id"],
        blocker_identifier="ENG-2",
        target_id=a["id"],
        target_identifier="ENG-1",
    )
    b_blocked_by_a = relation(
        blocker_id=a["id"],
        blocker_identifier="ENG-1",
        target_id=b["id"],
        target_identifier="ENG-2",
    )
    store = LinearIssuesTaskStore(
        tmp_path,
        team_id=TEAM_ID,
        client=RelationshipClient(
            [a, b],
            {
                a["id"]: [a_blocked_by_b],
                b["id"]: [b_blocked_by_a],
            },
        ),
    )

    tasks = store.list_all()

    assert all(task.status == TaskStatus.NEEDS_DECISION for task in tasks)
    assert all(task.human_decision_required for task in tasks)
    assert all(
        any("dependency graph contains a cycle" in note for note in task.normalization_notes)
        for task in tasks
    )


def test_local_hierarchy_cycle_requires_human_decision(tmp_path: Path):
    a_uuid = "11111111-1111-1111-1111-111111111111"
    b_uuid = "22222222-2222-2222-2222-222222222222"
    a = issue(
        "ENG-1",
        a_uuid,
        parent={"id": b_uuid, "identifier": "ENG-2", "team": {"id": TEAM_ID}},
    )
    b = issue(
        "ENG-2",
        b_uuid,
        parent={"id": a_uuid, "identifier": "ENG-1", "team": {"id": TEAM_ID}},
    )
    store = LinearIssuesTaskStore(
        tmp_path,
        team_id=TEAM_ID,
        client=RelationshipClient([a, b], {}),
    )

    tasks = store.list_all()

    assert all(task.status == TaskStatus.NEEDS_DECISION for task in tasks)
    assert all(
        any("hierarchy contains a cycle" in note for note in task.normalization_notes)
        for task in tasks
    )
