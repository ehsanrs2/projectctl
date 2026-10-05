import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

from projectctl.core.enums import CapabilityState, TaskStatus, TaskType
from projectctl.core.errors import ConfigurationError, TaskStoreError
from projectctl.integrations.execution_ownership import require_project_execution_ready
from projectctl.integrations.jira.client import JiraCloudClient
from projectctl.integrations.jira.task_store import JiraIssuesTaskStore
from projectctl.integrations.task_authority import (
    resolve_task_authority,
    task_authority_capabilities_for_provider,
)
from projectctl.project.adoption import plan_adoption
from projectctl.project.loader import load_project_config
from projectctl.schemas.config import (
    ProjectConfig,
    ProjectConfigV6,
    ProjectIdentity,
    TaskStoreConfig,
    TaskStoreConfigV4,
)
from projectctl.schemas.onboarding import ProjectInspection


NOW = "2026-10-05T09:00:00.000+0000"


def issue(
    key: str,
    *,
    issue_id: str,
    status_category: str = "new",
    status_name: str = "To Do",
    resolution: str | None = None,
    issue_type: str = "Task",
    priority: str = "Medium",
    parent: str | None = None,
):
    fields = {
        "summary": f"Summary {key}",
        "status": {
            "id": "10000",
            "name": status_name,
            "statusCategory": {
                "id": 2,
                "key": status_category,
                "name": status_category,
            },
        },
        "priority": {"id": "3", "name": priority},
        "issuetype": {"id": "10001", "name": issue_type},
        "assignee": {"accountId": "a1", "displayName": "Ada"},
        "parent": {"key": parent} if parent else None,
        "created": NOW,
        "updated": NOW,
        "duedate": None,
        "resolution": {"id": "1", "name": resolution} if resolution else None,
        "labels": ["backend"],
        "project": {"id": "10000", "key": "ENG", "name": "Engineering"},
    }
    return {
        "id": issue_id,
        "key": key,
        "self": f"https://acme.atlassian.net/rest/api/3/issue/{key}",
        "fields": fields,
    }


class PagingClient(JiraCloudClient):
    def __init__(self, root: Path):
        super().__init__(
            root,
            site="acme.atlassian.net",
            project_key="eng",
            email="bot@example.com",
            api_token="secret",
        )
        self.calls = []

    def _api(self, method, endpoint, *, payload=None, query=None):
        self.calls.append((method, endpoint, payload, query))
        if endpoint.startswith("/rest/api/3/project/"):
            return {"id": "10000", "key": "ENG", "name": "Engineering"}
        token = (payload or {}).get("nextPageToken")
        if token is None:
            return {
                "isLast": False,
                "nextPageToken": "page-2",
                "issues": [issue("ENG-1", issue_id="101")],
            }
        assert token == "page-2"
        return {
            "isLast": True,
            "issues": [issue("ENG-2", issue_id="102")],
        }


def test_jira_client_uses_enhanced_search_token_pagination(tmp_path: Path):
    client = PagingClient(tmp_path)

    rows = client.list_all(page_size=50)

    assert [row["key"] for row in rows] == ["ENG-1", "ENG-2"]
    assert client.calls[0][0:2] == ("POST", "/rest/api/3/search/jql")
    assert client.calls[0][2]["jql"] == 'project = "ENG" ORDER BY key ASC'
    assert client.calls[0][2]["maxResults"] == 50
    assert client.calls[1][2]["nextPageToken"] == "page-2"


def test_jira_client_rejects_cross_project_search_leak(tmp_path: Path):
    client = PagingClient(tmp_path)
    leaked = issue("OPS-1", issue_id="201")
    leaked["fields"]["project"]["key"] = "OPS"

    class LeakClient(PagingClient):
        def _api(self, method, endpoint, *, payload=None, query=None):
            return {"isLast": True, "issues": [leaked]}

    with pytest.raises(TaskStoreError, match="leaked issue"):
        LeakClient(tmp_path).list_all()


class FakeJiraClient:
    site = "acme.atlassian.net"
    project_key = "ENG"

    def __init__(self, rows):
        self.rows = rows

    def list_all(self):
        return list(self.rows)

    def show(self, key):
        for row in self.rows:
            if row["key"] == key:
                return row
        raise AssertionError(key)

    def version(self):
        return "jira-cloud-rest-v3-test"


@pytest.mark.parametrize(
    ("category", "resolution", "expected"),
    [
        ("new", None, TaskStatus.PLANNED),
        ("indeterminate", None, TaskStatus.RUNNING),
        ("in-flight", None, TaskStatus.RUNNING),
        ("done", None, TaskStatus.DONE),
        ("completed", "Cancelled", TaskStatus.CANCELLED),
        ("mystery", None, TaskStatus.NEEDS_DECISION),
    ],
)
def test_jira_status_mapping_is_conservative(
    tmp_path: Path, category, resolution, expected
):
    row = issue(
        "ENG-1",
        issue_id="101",
        status_category=category,
        resolution=resolution,
    )
    store = JiraIssuesTaskStore(
        tmp_path,
        site="acme.atlassian.net",
        project_key="ENG",
        client=FakeJiraClient([row]),
    )

    task = store.list_all()[0]

    assert task.status == expected
    if category == "new":
        assert "does not infer scheduler readiness" in " ".join(task.normalization_notes)
        assert store.list_ready() == []


def test_jira_normalizes_type_priority_assignee_and_hierarchy(tmp_path: Path):
    parent = issue(
        "ENG-1",
        issue_id="101",
        issue_type="Story",
        priority="High",
    )
    child = issue(
        "ENG-2",
        issue_id="102",
        issue_type="Bug",
        priority="Highest",
        parent="ENG-1",
    )
    store = JiraIssuesTaskStore(
        tmp_path,
        site="acme.atlassian.net",
        project_key="ENG",
        client=FakeJiraClient([parent, child]),
    )

    tasks = {task.id: task for task in store.list_all()}

    assert tasks["jira-ENG-1"].type == TaskType.FEATURE
    assert tasks["jira-ENG-1"].priority == 8
    assert tasks["jira-ENG-1"].team.assignees == ["Ada"]
    assert tasks["jira-ENG-2"].type == TaskType.BUG
    assert tasks["jira-ENG-2"].priority == 10
    assert tasks["jira-ENG-2"].hierarchy.parent == "jira-ENG-1"
    assert tasks["jira-ENG-1"].hierarchy.sub_issues == ["jira-ENG-2"]


def test_jira_capabilities_are_read_only():
    caps = task_authority_capabilities_for_provider("jira")

    assert caps.read == CapabilityState.SUPPORTED
    assert caps.claim == CapabilityState.UNSUPPORTED
    assert caps.release == CapabilityState.UNSUPPORTED
    assert caps.block_for_decision == CapabilityState.UNSUPPORTED
    assert caps.complete == CapabilityState.UNSUPPORTED


def test_project_config_v6_upgrades_to_v8_without_rewrite(tmp_path: Path):
    ctl = tmp_path / ".projectctl"
    ctl.mkdir()
    path = ctl / "config.yaml"
    legacy = ProjectConfigV6(
        project=ProjectIdentity(id="demo"),
        task_store=TaskStoreConfigV4(provider="beads"),
    )
    path.write_text(
        yaml.safe_dump(legacy.model_dump(mode="json"), sort_keys=False),
        encoding="utf-8",
    )

    config = load_project_config(tmp_path)

    assert config.schema_version == 8
    assert config.task_store.site is None
    assert config.task_store.project is None
    assert yaml.safe_load(path.read_text(encoding="utf-8"))["schema_version"] == 6


def test_jira_config_requires_site_and_project():
    with pytest.raises(Exception, match="site and task_store.project"):
        ProjectConfig(
            project=ProjectIdentity(id="demo"),
            task_store=TaskStoreConfig(provider="jira"),
        )


def test_jira_adoption_records_provider_identity(tmp_path: Path):
    inspection = ProjectInspection(
        project_root=str(tmp_path),
        classification="existing_unmanaged",
        confidence="high",
        repository_fingerprint="fp",
    )

    plan = plan_adoption(
        inspection,
        task_store_provider="jira",
        task_store_site="ACME.atlassian.net",
        task_store_project="eng",
        code_transport_mode="local",
        code_delivery_mode="local",
    )

    assert plan.task_store_provider == "jira"
    assert plan.task_store_site == "acme.atlassian.net"
    assert plan.task_store_project == "ENG"
    assert plan.unresolved_decisions == []


def test_jira_execution_remains_fail_closed(tmp_path: Path):
    ctl = tmp_path / ".projectctl"
    ctl.mkdir()
    config = ProjectConfig(
        project=ProjectIdentity(id="demo"),
        task_store=TaskStoreConfig(
            provider="jira",
            site="acme.atlassian.net",
            project="ENG",
        ),
    )
    (ctl / "config.yaml").write_text(
        yaml.safe_dump(config.model_dump(mode="json"), sort_keys=False),
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationError, match="block_for_decision, complete"):
        require_project_execution_ready(tmp_path)


def test_resolve_jira_authority_uses_runtime_client_contract(tmp_path: Path, monkeypatch):
    ctl = tmp_path / ".projectctl"
    ctl.mkdir()
    config = ProjectConfig(
        project=ProjectIdentity(id="demo"),
        task_store=TaskStoreConfig(
            provider="jira",
            site="acme.atlassian.net",
            project="ENG",
        ),
    )
    (ctl / "config.yaml").write_text(
        yaml.safe_dump(config.model_dump(mode="json"), sort_keys=False),
        encoding="utf-8",
    )
    monkeypatch.setenv("JIRA_EMAIL", "bot@example.com")
    monkeypatch.setenv("JIRA_API_TOKEN", "token")

    authority = resolve_task_authority(tmp_path)

    assert authority.provider == "jira"
    assert isinstance(authority.reader, JiraIssuesTaskStore)
    assert authority.completion_writer is None
