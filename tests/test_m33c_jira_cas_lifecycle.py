import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

from projectctl.core.digest import digest
from projectctl.core.enums import TaskStatus
from projectctl.core.errors import TaskStoreError
from projectctl.integrations.execution_ownership import require_project_execution_ready
from projectctl.integrations.jira.client import (
    JIRA_LIFECYCLE_PROPERTY,
    JiraCloudClient,
)
from projectctl.integrations.jira.completion import JiraTaskCompletionWriter
from projectctl.integrations.jira.task_store import JiraIssuesTaskStore
from projectctl.integrations.task_authority import resolve_task_authority
from projectctl.schema_export import PUBLIC_SCHEMAS
from projectctl.schemas.config import (
    JiraLinkRule,
    JiraReadyStatus,
    JiraWorkflowPolicy,
    ProjectConfig,
    ProjectIdentity,
    TaskStoreConfig,
)
from projectctl.schemas.evidence import EvidenceManifest
from projectctl.schemas.execution import EvidenceReference
from projectctl.schemas.jira_lifecycle import JiraLifecycleMarker


SITE = "acme.atlassian.net"
PROJECT = "ENG"
NOW = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)
BASE = "a" * 40
CANDIDATE = "b" * 40


def policy():
    return JiraWorkflowPolicy(
        ready_statuses=[JiraReadyStatus(id="10000", name="Ready")],
        link_rules=[
            JiraLinkRule(
                type_id="10001",
                name="Blocks",
                inward_label="is blocked by",
                outward_label="blocks",
                inward="dependency",
                outward="blocks",
            )
        ],
    )


def issue(
    key="ENG-1",
    issue_id="101",
    *,
    category="new",
    status_id="10000",
    status_name="Ready",
    resolution=None,
    links=None,
    lifecycle=None,
):
    raw = {
        "id": issue_id,
        "key": key,
        "fields": {
            "summary": f"Summary {key}",
            "status": {
                "id": status_id,
                "name": status_name,
                "statusCategory": {
                    "id": "2",
                    "key": category,
                    "name": category,
                },
            },
            "priority": {"id": "3", "name": "Medium"},
            "issuetype": {"id": "10001", "name": "Task"},
            "assignee": None,
            "parent": None,
            "created": "2026-10-05T10:00:00.000+0000",
            "updated": "2026-10-05T10:00:00.000+0000",
            "duedate": None,
            "resolution": (
                {"id": "1", "name": resolution} if resolution else None
            ),
            "labels": [],
            "project": {"id": "10000", "key": PROJECT},
            "issuelinks": list(links or []),
        },
        "properties": {},
    }
    if lifecycle is not None:
        raw["properties"][JIRA_LIFECYCLE_PROPERTY] = lifecycle
    return raw


def linked(raw):
    return {
        "id": raw["id"],
        "key": raw["key"],
        "fields": {"status": raw["fields"]["status"]},
    }


def inward_block(blocker):
    return {
        "id": "link-1",
        "type": {
            "id": "10001",
            "name": "Blocks",
            "inward": "is blocked by",
            "outward": "blocks",
        },
        "inwardIssue": linked(blocker),
    }


class FakeClient:
    site = SITE
    project_key = PROJECT

    def __init__(self, rows):
        self.rows = {
            str(row["key"]).upper(): json.loads(json.dumps(row))
            for row in rows
        }
        self.cas_calls = []
        self.before_cas = None

    def _row(self, key):
        normalized = str(key).upper()
        if normalized.startswith("JIRA-"):
            normalized = normalized[5:]
        return self.rows[normalized]

    def list_all(self):
        return [json.loads(json.dumps(row)) for row in self.rows.values()]

    def show(self, key):
        return json.loads(json.dumps(self._row(key)))

    def show_linked(self, key):
        return self.show(key)

    def get_issue_property(self, issue_id_or_key, property_key):
        target = None
        value = str(issue_id_or_key)
        for row in self.rows.values():
            if str(row["id"]) == value or row["key"] == value.upper():
                target = row
                break
        if target is None:
            raise AssertionError(issue_id_or_key)
        return json.loads(
            json.dumps(target.get("properties", {}).get(property_key))
        )

    def compare_and_set_issue_property(
        self,
        issue_id,
        property_key,
        *,
        expected,
        desired,
    ):
        if self.before_cas is not None:
            hook = self.before_cas
            self.before_cas = None
            hook(self)
        target = next(
            row for row in self.rows.values()
            if str(row["id"]) == str(issue_id)
        )
        current = target.setdefault("properties", {}).get(property_key)
        self.cas_calls.append(
            {
                "expected": json.loads(json.dumps(expected)),
                "desired": json.loads(json.dumps(desired)),
                "current": json.loads(json.dumps(current)),
            }
        )
        if current != expected:
            return False
        target["properties"][property_key] = json.loads(json.dumps(desired))
        return True

    def version(self):
        return "jira-m33c-test"


def evidence(root: Path) -> EvidenceReference:
    manifest = EvidenceManifest(
        run_id="run-1",
        task_id="jira-ENG-1",
        base_commit=BASE,
        candidate_commit=CANDIDATE,
        diff_digest="diff",
        workspace_state_digest="workspace",
        worker_result_digest="worker",
        verification_manifest_digest="verification",
        verification_profile_digest="profile",
        changed_paths=["app.py"],
        overall_pass=True,
        generated_at=NOW,
    )
    rel = ".projectctl/runs/run-1/evidence-manifest.json"
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(manifest.model_dump(mode="json"), sort_keys=True),
        encoding="utf-8",
    )
    return EvidenceReference(path=rel, digest=digest(manifest))


def marker(state, *, generation=1, evidence_ref=None):
    kwargs = {}
    if state in {"completion_pending", "completed"}:
        assert evidence_ref is not None
        kwargs = {
            "run_id": "run-1",
            "evidence_path": evidence_ref.path,
            "evidence_digest": evidence_ref.digest,
        }
    return JiraLifecycleMarker(
        task_id="jira-ENG-1",
        issue_id="101",
        state=state,
        generation=generation,
        updated_at=NOW,
        **kwargs,
    )


def store(tmp_path: Path, rows, *, client=None, lifecycle_enabled=True):
    fake = client or FakeClient(rows)
    return JiraIssuesTaskStore(
        tmp_path,
        site=SITE,
        project_key=PROJECT,
        policy=policy(),
        client=fake,
        lifecycle_enabled=lifecycle_enabled,
    )


def test_jira_lifecycle_marker_schema_is_public():
    assert (
        PUBLIC_SCHEMAS["jira-lifecycle-marker.v1.schema.json"]
        is JiraLifecycleMarker
    )


def test_completed_property_normalizes_to_done(tmp_path: Path):
    ev = evidence(tmp_path)
    row = issue(lifecycle=marker("completed", generation=2, evidence_ref=ev).model_dump(mode="json"))

    task = store(tmp_path, [row]).list_all()[0]

    assert task.status == TaskStatus.DONE
    assert task.human_decision_required is False


@pytest.mark.parametrize("state", ["completion_pending", "needs_decision"])
def test_nonfinal_lifecycle_property_fails_closed(tmp_path: Path, state: str):
    ev = evidence(tmp_path)
    lifecycle = marker(
        state,
        evidence_ref=ev if state == "completion_pending" else None,
    )
    row = issue(lifecycle=lifecycle.model_dump(mode="json"))

    task = store(tmp_path, [row]).list_all()[0]

    assert task.status == TaskStatus.NEEDS_DECISION
    assert task.human_decision_required is True


def test_malformed_or_wrong_identity_property_fails_closed(tmp_path: Path):
    malformed = issue(lifecycle={"unexpected": True})
    task = store(tmp_path, [malformed]).list_all()[0]
    assert task.status == TaskStatus.NEEDS_DECISION

    ev = evidence(tmp_path)
    wrong = marker("completed", generation=2, evidence_ref=ev).model_copy(
        update={"issue_id": "999"}
    )
    row = issue(lifecycle=wrong.model_dump(mode="json"))
    task = store(tmp_path, [row]).list_all()[0]
    assert task.status == TaskStatus.NEEDS_DECISION


def test_native_cancelled_state_overrides_completed_marker(tmp_path: Path):
    ev = evidence(tmp_path)
    row = issue(
        category="done",
        status_id="20000",
        status_name="Done",
        resolution="Cancelled",
        lifecycle=marker("completed", generation=2, evidence_ref=ev).model_dump(mode="json"),
    )

    task = store(tmp_path, [row]).list_all()[0]

    assert task.status == TaskStatus.CANCELLED


def test_completed_marker_with_current_open_blocker_fails_closed(tmp_path: Path):
    ev = evidence(tmp_path)
    blocker = issue("ENG-2", "102")
    target = issue(
        lifecycle=marker("completed", generation=2, evidence_ref=ev).model_dump(mode="json"),
    )
    target["fields"]["issuelinks"] = [inward_block(blocker)]
    client = FakeClient([target, blocker])

    task = {
        value.id: value
        for value in store(tmp_path, [target, blocker], client=client).list_all()
    }["jira-ENG-1"]

    assert task.status == TaskStatus.NEEDS_DECISION
    assert task.dependencies == ["jira-ENG-2"]


def test_completion_uses_pending_guard_then_completed_cas(tmp_path: Path):
    row = issue()
    client = FakeClient([row])
    writer = JiraTaskCompletionWriter(
        tmp_path,
        site=SITE,
        project_key=PROJECT,
        policy=policy(),
        client=client,
    )
    ev = evidence(tmp_path)

    writer.complete("jira-ENG-1", evidence=ev)

    assert [call["desired"]["state"] for call in client.cas_calls] == [
        "completion_pending",
        "completed",
    ]
    current = client.get_issue_property("101", JIRA_LIFECYCLE_PROPERTY)
    assert current["state"] == "completed"
    assert current["evidence_digest"] == ev.digest


def test_completion_recovers_from_existing_pending_marker(tmp_path: Path):
    ev = evidence(tmp_path)
    pending = marker(
        "completion_pending",
        generation=1,
        evidence_ref=ev,
    )
    row = issue(lifecycle=pending.model_dump(mode="json"))
    client = FakeClient([row])
    writer = JiraTaskCompletionWriter(
        tmp_path,
        site=SITE,
        project_key=PROJECT,
        policy=policy(),
        client=client,
    )

    writer.complete("jira-ENG-1", evidence=ev)

    assert len(client.cas_calls) == 1
    assert client.cas_calls[0]["expected"]["state"] == "completion_pending"
    assert client.cas_calls[0]["desired"]["state"] == "completed"


def test_completion_is_idempotent_for_same_completed_evidence(tmp_path: Path):
    ev = evidence(tmp_path)
    done = marker("completed", generation=2, evidence_ref=ev)
    row = issue(lifecycle=done.model_dump(mode="json"))
    client = FakeClient([row])
    writer = JiraTaskCompletionWriter(
        tmp_path,
        site=SITE,
        project_key=PROJECT,
        policy=policy(),
        client=client,
    )

    writer.complete("jira-ENG-1", evidence=ev)

    assert client.cas_calls == []


def test_completion_refuses_needs_decision_or_foreign_property(tmp_path: Path):
    ev = evidence(tmp_path)
    row = issue(
        lifecycle=marker("needs_decision").model_dump(mode="json")
    )
    client = FakeClient([row])
    writer = JiraTaskCompletionWriter(
        tmp_path,
        site=SITE,
        project_key=PROJECT,
        policy=policy(),
        client=client,
    )

    with pytest.raises(TaskStoreError, match="needs-decision"):
        writer.complete("jira-ENG-1", evidence=ev)

    client.rows["ENG-1"]["properties"][JIRA_LIFECYCLE_PROPERTY] = {
        "foreign": "value"
    }
    with pytest.raises(TaskStoreError, match="malformed or foreign"):
        writer.complete("jira-ENG-1", evidence=ev)


def test_completion_cas_conflict_never_overwrites_concurrent_property(tmp_path: Path):
    row = issue()
    client = FakeClient([row])
    ev = evidence(tmp_path)
    writer = JiraTaskCompletionWriter(
        tmp_path,
        site=SITE,
        project_key=PROJECT,
        policy=policy(),
        client=client,
    )

    def concurrent_change(fake):
        fake.rows["ENG-1"]["properties"][JIRA_LIFECYCLE_PROPERTY] = {
            "human_or_app": "changed"
        }

    client.before_cas = concurrent_change

    with pytest.raises(TaskStoreError, match="changed concurrently"):
        writer.complete("jira-ENG-1", evidence=ev)

    assert client.rows["ENG-1"]["properties"][JIRA_LIFECYCLE_PROPERTY] == {
        "human_or_app": "changed"
    }


def test_mark_needs_decision_is_cas_backed_and_idempotent(tmp_path: Path):
    row = issue()
    client = FakeClient([row])
    writer = JiraTaskCompletionWriter(
        tmp_path,
        site=SITE,
        project_key=PROJECT,
        policy=policy(),
        client=client,
    )

    writer.mark_needs_decision("jira-ENG-1", reason="policy")
    writer.mark_needs_decision("jira-ENG-1", reason="policy")

    assert len(client.cas_calls) == 1
    current = client.get_issue_property("101", JIRA_LIFECYCLE_PROPERTY)
    assert current["state"] == "needs_decision"


class TransportProbe(JiraCloudClient):
    def __init__(self, root: Path):
        super().__init__(
            root,
            site=SITE,
            project_key=PROJECT,
            email="bot@example.com",
            api_token="token",
        )
        self.payload = None
        self.current = None

    def _submit_async(self, method, endpoint, *, payload):
        self.payload = (method, endpoint, payload)
        expected = payload["filter"].get("currentValue")
        has_property = payload["filter"].get("hasProperty")
        if (has_property is False and self.current is None) or (
            has_property is True and self.current == expected
        ):
            self.current = payload["value"]
        return None

    def get_issue_property(self, issue_id_or_key, property_key):
        return json.loads(json.dumps(self.current))


def test_jira_property_transport_uses_filtered_compare_and_set(tmp_path: Path):
    client = TransportProbe(tmp_path)
    desired = {"state": "needs_decision"}

    assert client.compare_and_set_issue_property(
        "101",
        JIRA_LIFECYCLE_PROPERTY,
        expected=None,
        desired=desired,
    )
    _, endpoint, payload = client.payload
    assert endpoint.endswith(JIRA_LIFECYCLE_PROPERTY)
    assert payload["filter"] == {
        "entityIds": [101],
        "hasProperty": False,
    }

    next_value = {"state": "completed"}
    assert client.compare_and_set_issue_property(
        "101",
        JIRA_LIFECYCLE_PROPERTY,
        expected=desired,
        desired=next_value,
    )
    assert client.payload[2]["filter"]["currentValue"] == desired


def test_jira_is_project_execution_ready_with_independent_ownership(tmp_path: Path):
    ctl = tmp_path / ".projectctl"
    ctl.mkdir()
    config = ProjectConfig(
        project=ProjectIdentity(id="demo"),
        task_store=TaskStoreConfig(
            provider="jira",
            site=SITE,
            project=PROJECT,
            jira_policy=policy(),
        ),
    )
    (ctl / "config.yaml").write_text(
        yaml.safe_dump(config.model_dump(mode="json"), sort_keys=False),
        encoding="utf-8",
    )

    require_project_execution_ready(tmp_path)


def test_resolved_jira_authority_has_completion_writer(
    tmp_path: Path,
    monkeypatch,
):
    ctl = tmp_path / ".projectctl"
    ctl.mkdir()
    config = ProjectConfig(
        project=ProjectIdentity(id="demo"),
        task_store=TaskStoreConfig(
            provider="jira",
            site=SITE,
            project=PROJECT,
            jira_policy=policy(),
        ),
    )
    (ctl / "config.yaml").write_text(
        yaml.safe_dump(config.model_dump(mode="json"), sort_keys=False),
        encoding="utf-8",
    )
    monkeypatch.setenv("JIRA_EMAIL", "bot@example.com")
    monkeypatch.setenv("JIRA_API_TOKEN", "token")

    authority = resolve_task_authority(tmp_path)

    assert isinstance(authority.completion_writer, JiraTaskCompletionWriter)
    assert authority.capabilities.complete.value == "supported"
    assert authority.capabilities.block_for_decision.value == "supported"
