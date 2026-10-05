from datetime import datetime, timezone
from pathlib import Path
import json
import subprocess

import pytest
import yaml
from pydantic import ValidationError

from projectctl.core.digest import digest
from projectctl.core.enums import TaskStatus
from projectctl.core.errors import ConfigurationError, ProviderUnavailableError, TaskStoreError
from projectctl.git.publication import GitRemotePublisher
from projectctl.integrations.delivery import code_delivery_policy
from projectctl.integrations.execution_ownership import require_project_execution_ready
from projectctl.integrations.linear.client import LinearIssuesClient
from projectctl.integrations.linear.completion import LinearTaskCompletionWriter
from projectctl.integrations.linear.lifecycle import COMPLETED_LABEL, NEEDS_DECISION_LABEL
from projectctl.integrations.linear.task_store import LinearIssuesTaskStore
from projectctl.project.adoption import plan_adoption
from projectctl.project.loader import load_project_config
from projectctl.schema_export import PUBLIC_SCHEMAS
from projectctl.schemas.config import (
    CodeDeliveryConfig,
    CodeTransportConfig,
    ProjectConfig,
    ProjectConfigV5,
    ProjectIdentity,
    TaskStoreConfig,
)
from projectctl.schemas.delivery import CodeDeliveryPolicy, CodeDeliveryPolicyV1, PublicationRequest
from projectctl.schemas.evidence import EvidenceManifest
from projectctl.schemas.execution import EvidenceReference
from projectctl.schemas.onboarding import ProjectInspection


TEAM_ID = "9cfb482a-81e3-4154-b5b9-2c805e70a02d"
ISSUE_ID = "11111111-1111-1111-1111-111111111111"
BLOCKER_ID = "22222222-2222-2222-2222-222222222222"
NOW = datetime(2026, 10, 5, 7, 0, tzinfo=timezone.utc)
BASE = "a" * 40
CANDIDATE = "b" * 40


def write_config(
    root: Path,
    *,
    provider: str = "linear",
    transport: CodeTransportConfig | None = None,
    delivery: CodeDeliveryConfig | None = None,
):
    ctl = root / ".projectctl"
    ctl.mkdir(parents=True, exist_ok=True)
    config = ProjectConfig(
        project=ProjectIdentity(id="demo"),
        task_store=TaskStoreConfig(
            provider=provider,
            repository="acme/widget" if provider == "github" else None,
            team=TEAM_ID if provider == "linear" else None,
        ),
        code_transport=transport or CodeTransportConfig(mode="local"),
        code_delivery=delivery or CodeDeliveryConfig(mode="local"),
    )
    (ctl / "config.yaml").write_text(
        yaml.safe_dump(config.model_dump(mode="json"), sort_keys=False),
        encoding="utf-8",
    )
    return config


def raw_issue(*, state_type="unstarted", label_ids=None):
    return {
        "id": ISSUE_ID,
        "identifier": "ENG-1",
        "title": "Implement delivery",
        "priority": 0,
        "createdAt": "2026-10-05T01:00:00.000Z",
        "updatedAt": "2026-10-05T02:00:00.000Z",
        "archivedAt": None,
        "labelIds": list(label_ids or []),
        "state": {
            "id": f"state-{state_type}",
            "name": state_type.title(),
            "type": state_type,
        },
        "assignee": None,
        "parent": None,
        "team": {"id": TEAM_ID},
    }


def blocker_relation(*, state_type="unstarted"):
    return {
        "id": "rel-1",
        "type": "blocks",
        "issue": {
            "id": BLOCKER_ID,
            "identifier": "ENG-0",
            "state": {"type": state_type},
            "team": {"id": TEAM_ID},
        },
        "relatedIssue": {
            "id": ISSUE_ID,
            "identifier": "ENG-1",
            "state": {"type": "unstarted"},
            "team": {"id": TEAM_ID},
        },
    }


class MarkerStoreClient:
    team_id = TEAM_ID

    def __init__(self, issue, marker_ids):
        self.issue = dict(issue)
        self.marker_ids = dict(marker_ids)

    def team_label_ids(self, _names):
        return dict(self.marker_ids)

    def list_all(self):
        return [dict(self.issue)]

    def list_inverse_relations(self, _issue_id):
        return []

    def version(self):
        return "linear-m32c2-test"


class LifecycleClient:
    team_id = TEAM_ID

    def __init__(self, *, state_type="unstarted", relation_batches=None):
        self.issue = raw_issue(state_type=state_type)
        self.labels = {
            COMPLETED_LABEL: "label-completed",
            NEEDS_DECISION_LABEL: "label-decision",
        }
        self.relation_batches = list(relation_batches or [[]])
        self.relation_calls = 0
        self.operations = []

    def show(self, _issue_id):
        self.issue["labelIds"] = list(self.issue.get("labelIds") or [])
        return json.loads(json.dumps(self.issue))

    def list_inverse_relations(self, _issue_id):
        index = min(self.relation_calls, len(self.relation_batches) - 1)
        self.relation_calls += 1
        return json.loads(json.dumps(self.relation_batches[index]))

    def ensure_team_label(self, name, *, color, description):
        self.operations.append(("ensure", name, color, description))
        return {"id": self.labels[name], "name": name, "team": {"id": TEAM_ID}}

    def team_label_ids(self, names):
        return {name: self.labels[name] for name in names if name in self.labels}

    def add_issue_label(self, _issue_id, label_id):
        values = set(self.issue.get("labelIds") or [])
        values.add(label_id)
        self.issue["labelIds"] = sorted(values)
        self.operations.append(("add", label_id))
        return self.show(_issue_id)

    def remove_issue_label(self, _issue_id, label_id):
        values = set(self.issue.get("labelIds") or [])
        values.discard(label_id)
        self.issue["labelIds"] = sorted(values)
        self.operations.append(("remove", label_id))
        return self.show(_issue_id)


def write_evidence(root: Path) -> EvidenceReference:
    manifest = EvidenceManifest(
        run_id="run-1",
        task_id="lin-ENG-1",
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


def test_delivery_config_requires_network_transport_for_remote_modes():
    with pytest.raises(ValidationError, match="requires"):
        ProjectConfig(
            project={"id": "demo"},
            code_transport={"mode": "local"},
            code_delivery={"mode": "direct_git"},
        )
    with pytest.raises(ValidationError, match="requires"):
        ProjectConfig(
            project={"id": "demo"},
            code_transport={"mode": "local"},
            code_delivery={"mode": "review_required"},
        )


@pytest.mark.parametrize(
    ("mode", "supported", "publication_required", "evidence"),
    [
        ("local", True, False, "evidence_manifest"),
        ("direct_git", True, True, "publication_manifest"),
        ("review_required", True, True, "review_receipt"),
    ],
)
def test_code_delivery_policy_is_explicit(
    tmp_path: Path,
    mode: str,
    supported: bool,
    publication_required: bool,
    evidence: str,
):
    transport = (
        CodeTransportConfig(mode="local")
        if mode == "local"
        else CodeTransportConfig(
            mode="git_remote",
            remote_name="origin",
            remote_identity="gitlab.com/acme/widget",
        )
    )
    write_config(
        tmp_path,
        transport=transport,
        delivery=CodeDeliveryConfig(mode=mode),
    )

    policy = code_delivery_policy(tmp_path)

    assert policy.mode == mode
    assert policy.supported is supported
    assert policy.publication_required is publication_required
    assert policy.completion_evidence == evidence


def test_review_required_requires_runtime_provider_auth(tmp_path: Path, monkeypatch):
    write_config(
        tmp_path,
        transport=CodeTransportConfig(
            mode="git_remote",
            remote_name="origin",
            remote_identity="gitlab.com/acme/widget",
        ),
        delivery=CodeDeliveryConfig(mode="review_required"),
    )

    monkeypatch.delenv("GITLAB_TOKEN", raising=False)
    monkeypatch.delenv("GITLAB_ACCESS_TOKEN", raising=False)
    with pytest.raises(ProviderUnavailableError, match="GITLAB_TOKEN"):
        require_project_execution_ready(tmp_path)


def test_linear_local_delivery_is_statically_execution_ready(tmp_path: Path):
    write_config(tmp_path)
    require_project_execution_ready(tmp_path)


def test_project_config_v5_github_preserves_historical_direct_delivery(tmp_path: Path):
    ctl = tmp_path / ".projectctl"
    ctl.mkdir()
    path = ctl / "config.yaml"
    payload = ProjectConfigV5(
        project=ProjectIdentity(id="demo"),
        task_store=TaskStoreConfig(provider="github", repository="acme/widget"),
        code_transport=CodeTransportConfig(
            mode="git_remote",
            remote_name="origin",
            remote_identity="github.com/acme/widget",
        ),
    ).model_dump(mode="json")
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    config = load_project_config(tmp_path)

    assert config.schema_version == 8
    assert config.code_delivery.mode == "direct_git"
    assert yaml.safe_load(path.read_text(encoding="utf-8"))["schema_version"] == 5


def test_project_config_v5_linear_gitlab_does_not_infer_publish_permission(tmp_path: Path):
    ctl = tmp_path / ".projectctl"
    ctl.mkdir()
    path = ctl / "config.yaml"
    payload = ProjectConfigV5(
        project=ProjectIdentity(id="demo"),
        task_store=TaskStoreConfig(provider="linear", team=TEAM_ID),
        code_transport=CodeTransportConfig(
            mode="git_remote",
            remote_name="origin",
            remote_identity="gitlab.com/acme/widget",
        ),
    ).model_dump(mode="json")
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    config = load_project_config(tmp_path)

    assert config.code_transport.remote_identity == "gitlab.com/acme/widget"
    assert config.code_delivery.mode == "local"


def test_gitlab_adoption_requires_explicit_direct_delivery_opt_in(tmp_path: Path):
    inspection = ProjectInspection(
        project_root=str(tmp_path),
        classification="existing_unmanaged",
        confidence="high",
        repository_fingerprint="fp",
        git_remote_name="origin",
        git_remote_identity="gitlab.com/acme/widget",
    )

    local_plan = plan_adoption(
        inspection,
        task_store_provider="linear",
        task_store_team=TEAM_ID,
        code_transport_mode="git_remote",
    )
    direct_plan = plan_adoption(
        inspection,
        task_store_provider="linear",
        task_store_team=TEAM_ID,
        code_transport_mode="git_remote",
        code_delivery_mode="direct_git",
    )

    assert local_plan.code_delivery_mode == "local"
    assert direct_plan.code_delivery_mode == "direct_git"


def test_code_delivery_policy_schema_is_public():
    assert PUBLIC_SCHEMAS["code-delivery-policy.v1.schema.json"] is CodeDeliveryPolicyV1
    assert PUBLIC_SCHEMAS["code-delivery-policy.v2.schema.json"] is CodeDeliveryPolicy


@pytest.mark.parametrize(
    ("labels", "state_type", "expected", "decision"),
    [
        (["label-completed"], "unstarted", TaskStatus.DONE, False),
        (["label-decision"], "unstarted", TaskStatus.NEEDS_DECISION, True),
        (
            ["label-completed", "label-decision"],
            "unstarted",
            TaskStatus.NEEDS_DECISION,
            True,
        ),
        (["label-completed"], "canceled", TaskStatus.CANCELLED, False),
    ],
)
def test_linear_lifecycle_markers_normalize_fail_closed(
    tmp_path: Path,
    labels,
    state_type,
    expected,
    decision,
):
    marker_ids = {
        COMPLETED_LABEL: "label-completed",
        NEEDS_DECISION_LABEL: "label-decision",
    }
    client = MarkerStoreClient(
        raw_issue(state_type=state_type, label_ids=labels),
        marker_ids,
    )
    store = LinearIssuesTaskStore(tmp_path, team_id=TEAM_ID, client=client)

    task = store.list_all()[0]

    assert task.status == expected
    assert task.human_decision_required is decision


def test_linear_completion_uses_fail_closed_two_phase_markers(tmp_path: Path):
    client = LifecycleClient(relation_batches=[[], []])
    writer = LinearTaskCompletionWriter(tmp_path, team_id=TEAM_ID, client=client)

    writer.complete("lin-ENG-1", evidence=write_evidence(tmp_path))

    assert client.issue["labelIds"] == ["label-completed"]
    ops = [(item[0], item[1]) for item in client.operations]
    assert ("add", "label-decision") in ops
    assert ("add", "label-completed") in ops
    assert ("remove", "label-decision") in ops


def test_linear_completion_refuses_existing_unresolved_blocker(tmp_path: Path):
    client = LifecycleClient(
        relation_batches=[[blocker_relation(state_type="started")]]
    )
    writer = LinearTaskCompletionWriter(tmp_path, team_id=TEAM_ID, client=client)

    with pytest.raises(TaskStoreError, match="unresolved blocker"):
        writer.complete("lin-ENG-1", evidence=write_evidence(tmp_path))

    assert client.issue["labelIds"] == []


def test_linear_completion_keeps_decision_guard_if_blocker_appears_midflight(
    tmp_path: Path,
):
    client = LifecycleClient(
        relation_batches=[
            [],
            [blocker_relation(state_type="started")],
        ]
    )
    writer = LinearTaskCompletionWriter(tmp_path, team_id=TEAM_ID, client=client)

    with pytest.raises(TaskStoreError, match="unresolved blocker"):
        writer.complete("lin-ENG-1", evidence=write_evidence(tmp_path))

    assert set(client.issue["labelIds"]) == {
        "label-completed",
        "label-decision",
    }


def test_linear_needs_decision_is_additive(tmp_path: Path):
    client = LifecycleClient()
    writer = LinearTaskCompletionWriter(tmp_path, team_id=TEAM_ID, client=client)

    writer.mark_needs_decision("lin-ENG-1", reason="policy")

    assert client.issue["labelIds"] == ["label-decision"]


class FakeGitPublisher(GitRemotePublisher):
    def __init__(self, root: Path):
        self.project_root = root
        self.remote_identity = "gitlab.com/acme/widget"
        self.repository = None
        self.remote_name = "origin"
        self.timeout_seconds = 1

    def _git(self, *args, check=True):
        if args[:3] == ("remote", "get-url", "origin"):
            return subprocess.CompletedProcess(args, 0, "git@gitlab.com:acme/widget.git\n", "")
        if args[:2] == ("cat-file", "-e"):
            return subprocess.CompletedProcess(args, 0, "", "")
        if args[:2] == ("merge-base", "--is-ancestor"):
            return subprocess.CompletedProcess(args, 0, "", "")
        raise AssertionError(args)


def test_generic_git_publisher_accepts_linear_provider_and_gitlab_identity(tmp_path: Path):
    publisher = FakeGitPublisher(tmp_path)
    request = PublicationRequest(
        run_id="run-1",
        task_id="lin-ENG-1",
        provider="linear",
        repository="gitlab.com/acme/widget",
        remote_name="origin",
        target_ref="main",
        base_commit=BASE,
        candidate_commit=CANDIDATE,
        evidence_manifest=".projectctl/runs/run-1/evidence-manifest.json",
        evidence_digest="evidence",
        requested_at=NOW,
    )

    assert publisher._validate_request(request) == "refs/heads/main"


class MutationProbeClient(LinearIssuesClient):
    def __init__(self, root: Path):
        self.calls = []
        super().__init__(root, team_id=TEAM_ID, api_key="test")

    def _graphql(self, query, variables):
        self.calls.append((query, variables))
        return {
            "issueAddLabel": {
                "success": True,
                "issue": {
                    "id": ISSUE_ID,
                    "identifier": "ENG-1",
                    "updatedAt": "2026-10-05T02:00:00.000Z",
                    "labelIds": ["label-completed"],
                    "state": {"id": "todo", "name": "Todo", "type": "unstarted"},
                    "team": {"id": TEAM_ID},
                },
            }
        }


def test_linear_add_label_uses_additive_mutation(tmp_path: Path):
    client = MutationProbeClient(tmp_path)

    updated = client.add_issue_label(ISSUE_ID, "label-completed")

    assert updated["labelIds"] == ["label-completed"]
    _, variables = client.calls[0]
    assert variables == {"id": ISSUE_ID, "labelId": "label-completed"}
