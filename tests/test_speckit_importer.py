import subprocess
from pathlib import Path

import pytest

from projectctl.core.enums import ImportAction
from projectctl.core.errors import TaskImportConflict
from projectctl.integrations.speckit.importer import SpecKitBeadsImporter
from projectctl.project.bootstrap import initialize_project
from projectctl.project.state import update_project_state
from projectctl.core.errors import DigestMismatchError


class FakeBeadsClient:
    def __init__(self):
        self.counter = 0
        self.issues = {}
        self.dependencies = set()
        self.closed = set()

    def create_issue(self, *, title, description, issue_type="task", priority=2, labels=None):
        self.counter += 1
        issue_id = f"bd-{self.counter}"
        self.issues[issue_id] = {"title": title, "description": description, "issue_type": issue_type, "priority": priority, "labels": list(labels or [])}
        return issue_id

    def close_issue(self, issue_id, reason):
        self.closed.add(issue_id)

    def show(self, issue_id):
        if issue_id not in self.issues:
            raise RuntimeError("not found")
        return {"id": issue_id, **self.issues[issue_id]}

    def list_dependencies(self, issue_id):
        return [
            {"id": dep, "dependency_type": "blocks"}
            for child, dep in sorted(self.dependencies)
            if child == issue_id
        ]

    def ensure_blocking_dependency(self, issue_id, depends_on_id):
        edge = (issue_id, depends_on_id)
        created = edge not in self.dependencies
        self.dependencies.add(edge)
        return created


def make_repo(tmp_path: Path, monkeypatch) -> Path:
    repo = tmp_path / "demo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    monkeypatch.setenv("PROJECTCTL_HOME", str(tmp_path / "home"))
    initialize_project(repo)
    return repo


def write_tasks(repo: Path):
    feature = repo / "specs" / "001-auth"
    feature.mkdir(parents=True, exist_ok=True)
    source = feature / "tasks.md"
    source.write_text(
        "# Tasks: Auth\n\n"
        "## Phase 1: Setup\n"
        "- [ ] T001 Create auth package in src/auth/__init__.py\n"
        "- [ ] T002 [P] Create token model in src/auth/token.py\n"
        "- [ ] T003 [P] Create config in src/auth/config.py\n"
        "- [ ] T004 Wire auth in src/app.py\n",
        encoding="utf-8",
    )
    return source


def test_importer_is_idempotent_and_creates_dependencies(tmp_path: Path, monkeypatch):
    repo = make_repo(tmp_path, monkeypatch)
    source = write_tasks(repo)
    client = FakeBeadsClient()
    importer = SpecKitBeadsImporter(repo, client=client)

    plan = importer.preview(str(source))
    assert all(item.action == ImportAction.CREATE for item in plan.items)
    result = importer.apply(plan)
    assert len(client.issues) == 4
    targets = {item.source_id: item.target_id for item in result.items}
    assert (targets["T002"], targets["T001"]) in client.dependencies
    assert (targets["T003"], targets["T001"]) in client.dependencies
    assert (targets["T004"], targets["T002"]) in client.dependencies
    assert (targets["T004"], targets["T003"]) in client.dependencies

    second = importer.preview(str(source))
    assert all(item.action == ImportAction.UNCHANGED for item in second.items)
    importer.apply(second)
    assert len(client.issues) == 4


def test_importer_fails_closed_when_imported_task_changes(tmp_path: Path, monkeypatch):
    repo = make_repo(tmp_path, monkeypatch)
    source = write_tasks(repo)
    client = FakeBeadsClient()
    importer = SpecKitBeadsImporter(repo, client=client)
    importer.apply(importer.preview(str(source)))

    text = source.read_text(encoding="utf-8").replace("Create token model", "Create secure token model")
    source.write_text(text, encoding="utf-8")
    plan = importer.preview(str(source))
    assert any(item.action == ImportAction.CONFLICT for item in plan.items)
    with pytest.raises(TaskImportConflict):
        importer.apply(plan)


def test_checked_source_task_is_closed_on_first_import(tmp_path: Path, monkeypatch):
    repo = make_repo(tmp_path, monkeypatch)
    feature = repo / "specs" / "001-done"
    feature.mkdir(parents=True)
    source = feature / "tasks.md"
    source.write_text("## Phase 1: Setup\n- [x] T001 Already completed in src/a.py\n", encoding="utf-8")
    client = FakeBeadsClient()
    importer = SpecKitBeadsImporter(repo, client=client)
    result = importer.apply(importer.preview(str(source)))
    assert result.items[0].target_id in client.closed



def test_importer_assigns_active_milestone_label_to_new_beads_tasks(tmp_path: Path, monkeypatch):
    repo = make_repo(tmp_path, monkeypatch)
    update_project_state(repo, milestone_id="M0.5", milestone_title="Project State")
    source = write_tasks(repo)
    client = FakeBeadsClient()
    importer = SpecKitBeadsImporter(repo, client=client)

    plan = importer.preview(str(source))
    assert plan.milestone == "M0.5"
    importer.apply(plan)
    assert all("milestone:M0.5" in issue["labels"] for issue in client.issues.values())


def test_import_plan_is_invalidated_when_project_state_changes(tmp_path: Path, monkeypatch):
    repo = make_repo(tmp_path, monkeypatch)
    update_project_state(repo, milestone_id="M0.5")
    source = write_tasks(repo)
    client = FakeBeadsClient()
    importer = SpecKitBeadsImporter(repo, client=client)

    plan = importer.preview(str(source))
    update_project_state(repo, milestone_id="M0.6")
    with pytest.raises(DigestMismatchError, match="Project state changed"):
        importer.apply(plan)
    assert client.issues == {}
