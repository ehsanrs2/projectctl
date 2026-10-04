from pathlib import Path

import pytest

from projectctl.core.errors import TaskStoreError
from projectctl.integrations.github.completion import (
    COMPLETED_LABEL,
    NEEDS_DECISION_LABEL,
    GitHubTaskCompletionWriter,
)
from projectctl.schemas.execution import EvidenceReference


class FakeClient:
    def __init__(self, *, state="open", state_reason=None, labels=None):
        self.issue = {
            "number": 7,
            "state": state,
            "state_reason": state_reason,
            "labels": [{"name": value} for value in (labels or [])],
        }
        self.ensured = []
        self.added = []

    def show(self, issue_number):
        return {
            **self.issue,
            "labels": [dict(item) for item in self.issue["labels"]],
        }

    def ensure_label(self, name, *, color, description):
        self.ensured.append((name, color, description))

    def add_issue_labels(self, issue_number, labels):
        self.added.append((issue_number, list(labels)))
        existing = {
            item["name"].casefold()
            for item in self.issue["labels"]
        }
        for label in labels:
            if label.casefold() not in existing:
                self.issue["labels"].append({"name": label})
        return self.show(issue_number)


EVIDENCE = EvidenceReference(
    path=".projectctl/runs/run-1/publication-manifest.json",
    digest="sha256:publication",
)


def test_github_completion_is_additive_and_does_not_close_issue(tmp_path: Path):
    client = FakeClient(labels=["bug"])
    writer = GitHubTaskCompletionWriter(
        tmp_path,
        repository="acme/widget",
        client=client,
    )

    writer.complete("gh-7", evidence=EVIDENCE)

    assert client.issue["state"] == "open"
    assert {item["name"] for item in client.issue["labels"]} == {
        "bug",
        COMPLETED_LABEL,
    }
    assert client.added == [("gh-7", [COMPLETED_LABEL])]


def test_github_completion_refuses_external_noncompleted_close(tmp_path: Path):
    client = FakeClient(state="closed", state_reason="not_planned")
    writer = GitHubTaskCompletionWriter(
        tmp_path,
        repository="acme/widget",
        client=client,
    )

    with pytest.raises(TaskStoreError, match="refusing to overwrite human intent"):
        writer.complete("gh-7", evidence=EVIDENCE)

    assert client.added == []


def test_github_completed_native_close_is_idempotent(tmp_path: Path):
    client = FakeClient(state="closed", state_reason="completed")
    writer = GitHubTaskCompletionWriter(
        tmp_path,
        repository="acme/widget",
        client=client,
    )

    writer.complete("gh-7", evidence=EVIDENCE)

    assert client.added == []


def test_github_needs_decision_is_additive(tmp_path: Path):
    client = FakeClient(labels=["priority:p1"])
    writer = GitHubTaskCompletionWriter(
        tmp_path,
        repository="acme/widget",
        client=client,
    )

    writer.mark_needs_decision("gh-7", reason="policy")

    assert client.issue["state"] == "open"
    assert {item["name"] for item in client.issue["labels"]} == {
        "priority:p1",
        NEEDS_DECISION_LABEL,
    }
