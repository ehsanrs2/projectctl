from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from projectctl.core.enums import TaskStatus
from projectctl.integrations.jira.task_store import JiraIssuesTaskStore
from projectctl.project.loader import load_project_config
from projectctl.schemas.config import (
    JiraLinkRule,
    JiraReadyStatus,
    JiraWorkflowPolicy,
    ProjectConfig,
    ProjectConfigV7,
    ProjectIdentity,
    TaskStoreConfig,
    TaskStoreConfigV5,
)


SITE = "acme.atlassian.net"
PROJECT = "ENG"
NOW = "2026-10-05T10:00:00.000+0000"


def status(status_id="10000", name="Ready", category="new"):
    return {
        "id": status_id,
        "name": name,
        "statusCategory": {
            "id": "2",
            "key": category,
            "name": category,
        },
    }


def issue(
    key,
    issue_id,
    *,
    status_id="10000",
    status_name="Ready",
    category="new",
    parent=None,
    links=None,
):
    fields = {
        "summary": f"Summary {key}",
        "status": status(status_id, status_name, category),
        "priority": {"id": "3", "name": "Medium"},
        "issuetype": {"id": "10001", "name": "Task"},
        "assignee": None,
        "parent": (
            {"id": parent[0], "key": parent[1]} if parent is not None else None
        ),
        "created": NOW,
        "updated": NOW,
        "duedate": None,
        "resolution": None,
        "labels": [],
        "project": {"id": "10000", "key": PROJECT},
        "issuelinks": list(links or []),
    }
    return {"id": issue_id, "key": key, "fields": fields}


def linked(raw):
    return {
        "id": raw["id"],
        "key": raw["key"],
        "fields": {
            "status": raw["fields"]["status"],
        },
    }


def link(*, side, target, type_id="10000", name="Blocks",
         inward="is blocked by", outward="blocks"):
    value = {
        "id": f"link-{target['id']}-{side}",
        "type": {
            "id": type_id,
            "name": name,
            "inward": inward,
            "outward": outward,
        },
    }
    value["inwardIssue" if side == "inward" else "outwardIssue"] = linked(target)
    return value


def blocks_policy():
    return JiraWorkflowPolicy(
        ready_statuses=[JiraReadyStatus(id="10000", name="Ready")],
        link_rules=[
            JiraLinkRule(
                type_id="10000",
                name="Blocks",
                inward_label="is blocked by",
                outward_label="blocks",
                inward="dependency",
                outward="blocks",
            )
        ],
    )


class FakeClient:
    site = SITE
    project_key = PROJECT

    def __init__(self, rows, linked=None):
        self.rows = list(rows)
        self.linked = {
            str(item["key"]).upper(): item
            for item in (linked or [])
        }

    def list_all(self):
        return list(self.rows)

    def show_linked(self, key):
        normalized = str(key).upper()
        if normalized in self.linked:
            return self.linked[normalized]
        for row in self.rows:
            if str(row["key"]).upper() == normalized:
                return row
        raise AssertionError(normalized)

    def version(self):
        return "jira-m33b-test"


def store(tmp_path: Path, rows, policy=None, linked=None):
    return JiraIssuesTaskStore(
        tmp_path,
        site=SITE,
        project_key=PROJECT,
        policy=policy or JiraWorkflowPolicy(),
        client=FakeClient(rows, linked=linked),
    )


def test_ready_requires_explicit_status_id_and_name(tmp_path: Path):
    row = issue("ENG-1", "101")

    planned = store(tmp_path, [row]).list_all()[0]
    ready = store(tmp_path, [row], blocks_policy()).list_all()[0]

    assert planned.status == TaskStatus.PLANNED
    assert ready.status == TaskStatus.READY


def test_ready_status_name_drift_fails_closed(tmp_path: Path):
    row = issue("ENG-1", "101", status_name="Ready for Dev")
    task = store(tmp_path, [row], blocks_policy()).list_all()[0]

    assert task.status == TaskStatus.NEEDS_DECISION
    assert task.human_decision_required is True
    assert "changed name" in " ".join(task.normalization_notes)


def test_ready_status_category_drift_fails_closed(tmp_path: Path):
    row = issue(
        "ENG-1",
        "101",
        status_name="Ready",
        category="indeterminate",
    )
    task = store(tmp_path, [row], blocks_policy()).list_all()[0]

    assert task.status == TaskStatus.NEEDS_DECISION
    assert "policy/provider metadata drifted" in " ".join(task.normalization_notes)


def test_inward_blocks_link_becomes_dependency_and_blocks_ready_task(tmp_path: Path):
    blocker = issue("ENG-2", "102")
    target = issue(
        "ENG-1",
        "101",
        links=[link(side="inward", target=blocker)],
    )

    tasks = {
        task.id: task
        for task in store(tmp_path, [target, blocker], blocks_policy()).list_all()
    }

    assert tasks["jira-ENG-1"].status == TaskStatus.BLOCKED
    assert tasks["jira-ENG-1"].dependencies == ["jira-ENG-2"]
    assert tasks["jira-ENG-2"].blocks == ["jira-ENG-1"]


def test_terminal_blocker_is_satisfied(tmp_path: Path):
    blocker = issue(
        "ENG-2",
        "102",
        status_id="20000",
        status_name="Done",
        category="done",
    )
    target = issue(
        "ENG-1",
        "101",
        links=[link(side="inward", target=blocker)],
    )

    task = {
        item.id: item
        for item in store(tmp_path, [target, blocker], blocks_policy()).list_all()
    }["jira-ENG-1"]

    assert task.status == TaskStatus.READY
    assert task.dependencies == []


def test_external_open_blocker_uses_stable_external_identity(tmp_path: Path):
    external = issue("OPS-9", "901")
    external["fields"]["project"]["key"] = "OPS"
    target = issue(
        "ENG-1",
        "101",
        links=[link(side="inward", target=external)],
    )

    task = store(
        tmp_path,
        [target],
        blocks_policy(),
        linked=[external],
    ).list_all()[0]

    assert task.status == TaskStatus.BLOCKED
    assert task.dependencies == [f"jira:{SITE}:901"]
    assert "Open external Jira blocker" in " ".join(task.normalization_notes)


def test_unknown_link_type_fails_closed(tmp_path: Path):
    other = issue("ENG-2", "102")
    target = issue(
        "ENG-1",
        "101",
        links=[
            link(
                side="outward",
                target=other,
                type_id="90000",
                name="Relates",
                inward="relates to",
                outward="relates to",
            )
        ],
    )

    task = {
        item.id: item
        for item in store(tmp_path, [target, other], blocks_policy()).list_all()
    }["jira-ENG-1"]

    assert task.status == TaskStatus.NEEDS_DECISION
    assert "no explicit ProjectCTL semantics" in " ".join(task.normalization_notes)


def test_explicit_ignore_rule_allows_non_dependency_link(tmp_path: Path):
    other = issue("ENG-2", "102")
    target = issue(
        "ENG-1",
        "101",
        links=[
            link(
                side="outward",
                target=other,
                type_id="90000",
                name="Relates",
                inward="relates to",
                outward="relates to",
            )
        ],
    )
    policy = JiraWorkflowPolicy(
        ready_statuses=[JiraReadyStatus(id="10000", name="Ready")],
        link_rules=[
            JiraLinkRule(
                type_id="90000",
                name="Relates",
                inward_label="relates to",
                outward_label="relates to",
                inward="ignore",
                outward="ignore",
            )
        ],
    )

    task = {
        item.id: item
        for item in store(tmp_path, [target, other], policy).list_all()
    }["jira-ENG-1"]

    assert task.status == TaskStatus.READY
    assert task.dependencies == []


def test_link_type_metadata_drift_fails_closed(tmp_path: Path):
    blocker = issue("ENG-2", "102")
    target = issue(
        "ENG-1",
        "101",
        links=[
            link(
                side="inward",
                target=blocker,
                inward="depends on",
            )
        ],
    )

    task = {
        item.id: item
        for item in store(tmp_path, [target, blocker], blocks_policy()).list_all()
    }["jira-ENG-1"]

    assert task.status == TaskStatus.NEEDS_DECISION
    assert "metadata changed" in " ".join(task.normalization_notes)


def test_dependency_cycle_fails_closed(tmp_path: Path):
    a = issue("ENG-1", "101")
    b = issue("ENG-2", "102")
    a["fields"]["issuelinks"] = [link(side="inward", target=b)]
    b["fields"]["issuelinks"] = [link(side="inward", target=a)]

    tasks = store(tmp_path, [a, b], blocks_policy()).list_all()

    assert {task.status for task in tasks} == {TaskStatus.NEEDS_DECISION}
    assert all(
        "dependency graph contains a cycle" in " ".join(task.normalization_notes)
        for task in tasks
    )


def test_hierarchy_cycle_fails_closed_without_becoming_dependency(tmp_path: Path):
    a = issue("ENG-1", "101", parent=("102", "ENG-2"))
    b = issue("ENG-2", "102", parent=("101", "ENG-1"))

    tasks = store(tmp_path, [a, b], blocks_policy()).list_all()

    assert {task.status for task in tasks} == {TaskStatus.NEEDS_DECISION}
    assert all(task.dependencies == [] for task in tasks)
    assert all(
        "hierarchy contains a cycle" in " ".join(task.normalization_notes)
        for task in tasks
    )


def test_duplicate_jira_policy_ids_are_rejected():
    with pytest.raises(ValidationError, match="ready status ids must be unique"):
        JiraWorkflowPolicy(
            ready_statuses=[
                JiraReadyStatus(id="10000", name="Ready"),
                JiraReadyStatus(id="10000", name="Ready Again"),
            ]
        )

    with pytest.raises(ValidationError, match="link rule type_ids must be unique"):
        JiraWorkflowPolicy(
            link_rules=[
                JiraLinkRule(
                    type_id="10000",
                    name="Blocks",
                    inward_label="is blocked by",
                    outward_label="blocks",
                    inward="dependency",
                    outward="blocks",
                ),
                JiraLinkRule(
                    type_id="10000",
                    name="Other",
                    inward_label="in",
                    outward_label="out",
                    inward="ignore",
                    outward="ignore",
                ),
            ]
        )


def test_project_config_v7_upgrades_to_v8_without_rewrite(tmp_path: Path):
    ctl = tmp_path / ".projectctl"
    ctl.mkdir()
    path = ctl / "config.yaml"
    legacy = ProjectConfigV7(
        project=ProjectIdentity(id="demo"),
        task_store=TaskStoreConfigV5(
            provider="jira",
            site=SITE,
            project=PROJECT,
        ),
    )
    path.write_text(
        yaml.safe_dump(legacy.model_dump(mode="json"), sort_keys=False),
        encoding="utf-8",
    )

    config = load_project_config(tmp_path)

    assert config.schema_version == 8
    assert config.task_store.jira_policy.ready_statuses == []
    assert config.task_store.jira_policy.link_rules == []
    assert yaml.safe_load(path.read_text(encoding="utf-8"))["schema_version"] == 7


def test_jira_policy_is_rejected_for_non_jira_provider():
    with pytest.raises(ValidationError, match="only valid with provider='jira'"):
        ProjectConfig(
            project=ProjectIdentity(id="demo"),
            task_store=TaskStoreConfig(
                provider="beads",
                jira_policy=blocks_policy(),
            ),
        )


def test_outward_only_local_link_still_blocks_target(tmp_path: Path):
    blocker = issue("ENG-2", "102")
    target = issue("ENG-1", "101")
    blocker["fields"]["issuelinks"] = [
        link(side="outward", target=target)
    ]

    tasks = {
        task.id: task
        for task in store(
            tmp_path,
            [target, blocker],
            blocks_policy(),
        ).list_all()
    }

    assert tasks["jira-ENG-1"].status == TaskStatus.BLOCKED
    assert tasks["jira-ENG-1"].dependencies == ["jira-ENG-2"]
    assert tasks["jira-ENG-2"].blocks == ["jira-ENG-1"]


def test_external_blocker_revalidation_overrides_stale_embedded_terminal_state(
    tmp_path: Path,
):
    external_embedded = issue(
        "OPS-9",
        "901",
        status_id="20000",
        status_name="Done",
        category="done",
    )
    external_embedded["fields"]["project"]["key"] = "OPS"

    external_current = issue(
        "OPS-9",
        "901",
        status_id="10000",
        status_name="Ready",
        category="new",
    )
    external_current["fields"]["project"]["key"] = "OPS"

    target = issue(
        "ENG-1",
        "101",
        links=[link(side="inward", target=external_embedded)],
    )

    task = store(
        tmp_path,
        [target],
        blocks_policy(),
        linked=[external_current],
    ).list_all()[0]

    assert task.status == TaskStatus.BLOCKED
    assert task.dependencies == [f"jira:{SITE}:901"]
    assert "embedded status was stale" in " ".join(task.normalization_notes)


def test_external_blocker_identity_mismatch_fails_closed(tmp_path: Path):
    external = issue("OPS-9", "901")
    external["fields"]["project"]["key"] = "OPS"

    current = issue("OPS-9", "999")
    current["fields"]["project"]["key"] = "OPS"

    target = issue(
        "ENG-1",
        "101",
        links=[link(side="inward", target=external)],
    )

    task = store(
        tmp_path,
        [target],
        blocks_policy(),
        linked=[current],
    ).list_all()[0]

    assert task.status == TaskStatus.NEEDS_DECISION
    assert "changed stable id/key" in " ".join(task.normalization_notes)
