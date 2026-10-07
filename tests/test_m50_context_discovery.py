from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from typer.testing import CliRunner

from projectctl.cli.entry import app
from projectctl.context import discovery
from projectctl.core.enums import ResourceClass, TaskStatus
from projectctl.schema_export import PUBLIC_SCHEMAS
from projectctl.schemas.context_discovery import (
    ContextDiscoveryReport,
    ContextScopeSuggestion,
)
from projectctl.schemas.task import (
    NormalizedTask,
    TaskReferences,
    TaskSnapshot,
    TaskSource,
)


NOW = datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc)
runner = CliRunner()


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


def _repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(
        ["git", "init", "-b", "main", str(root)],
        check=True,
        capture_output=True,
    )
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "user.name", "ProjectCTL Test")
    (root / "pkg").mkdir()
    (root / "tests").mkdir()
    (root / "docs").mkdir()
    (root / "pkg" / "service.py").write_text(
        "import pkg.helper\n\n"
        "class PaymentService:\n"
        "    def charge(self):\n"
        "        return pkg.helper.normalize(1)\n",
        encoding="utf-8",
    )
    (root / "pkg" / "helper.py").write_text(
        "def normalize(value):\n"
        "    return value\n",
        encoding="utf-8",
    )
    (root / "pkg" / "graph_only.py").write_text(
        "def graph_only():\n"
        "    return True\n",
        encoding="utf-8",
    )
    (root / "tests" / "test_service.py").write_text(
        "from pkg.service import PaymentService\n\n"
        "def test_charge():\n"
        "    assert PaymentService().charge() == 1\n",
        encoding="utf-8",
    )
    (root / "docs" / "spec.md").write_text(
        "Update pkg/service.py to keep PaymentService behavior explicit.\n",
        encoding="utf-8",
    )
    _git(root, "add", ".")
    _git(root, "commit", "-m", "fixture")
    return root


def _task(
    *,
    title: str = "Update PaymentService",
    references: TaskReferences | None = None,
) -> NormalizedTask:
    return NormalizedTask(
        id="TASK-1",
        title=title,
        source=TaskSource(provider="test", external_id="TASK-1"),
        status=TaskStatus.READY,
        resource_class=ResourceClass.SMALL,
        references=references or TaskReferences(),
    )


def _snapshot(task: NormalizedTask) -> TaskSnapshot:
    return TaskSnapshot(
        provider="test",
        captured_at=NOW,
        source_revision="rev-1",
        tasks=[task],
    )


def _patch_project(
    monkeypatch,
    task: NormalizedTask,
    *,
    graphify: bool = False,
) -> None:
    monkeypatch.setattr(
        discovery,
        "capture_task_snapshot",
        lambda *args, **kwargs: _snapshot(task),
    )
    monkeypatch.setattr(
        discovery,
        "load_project_config",
        lambda root: SimpleNamespace(
            project=SimpleNamespace(id="demo"),
            features=SimpleNamespace(graphify=graphify),
        ),
    )


def test_builtin_discovery_finds_symbol_import_and_test_companion(
    tmp_path: Path,
    monkeypatch,
):
    root = _repo(tmp_path)
    _patch_project(monkeypatch, _task())

    report = discovery.discover_context(
        root,
        "TASK-1",
        integration_target_ref="HEAD",
        now=NOW,
        persist=False,
    )

    by_path = {item.path: item for item in report.candidates}
    assert "pkg/service.py" in by_path
    assert "write_candidate" in by_path["pkg/service.py"].roles
    assert "pkg/helper.py" in by_path
    assert "input" in by_path["pkg/helper.py"].roles
    assert "tests/test_service.py" in by_path
    assert "test" in by_path["tests/test_service.py"].roles
    assert "write_candidate" in by_path["tests/test_service.py"].roles
    assert report.indexed_python_files == 4
    assert report.authoritative is False


def test_reference_path_mention_is_explicit_write_candidate(
    tmp_path: Path,
    monkeypatch,
):
    root = _repo(tmp_path)
    task = _task(
        title="Implement the referenced behavior",
        references=TaskReferences(specs=["docs/spec.md"]),
    )
    _patch_project(monkeypatch, task)

    report = discovery.discover_context(
        root,
        "TASK-1",
        integration_target_ref="HEAD",
        now=NOW,
        persist=False,
    )

    by_path = {item.path: item for item in report.candidates}
    assert "docs/spec.md" in by_path
    assert "reference" in by_path["docs/spec.md"].roles
    assert "pkg/service.py" in by_path
    assert "write_candidate" in by_path["pkg/service.py"].roles
    assert any(
        item.kind == "path_mention" and item.source_path == "docs/spec.md"
        for item in report.evidence
    )


def test_discovery_reads_recorded_git_base_not_dirty_worktree(
    tmp_path: Path,
    monkeypatch,
):
    root = _repo(tmp_path)
    (root / "pkg" / "service.py").write_text(
        "class WorkingTreeOnlySymbol:\n"
        "    pass\n",
        encoding="utf-8",
    )
    _patch_project(
        monkeypatch,
        _task(title="Update WorkingTreeOnlySymbol"),
    )

    report = discovery.discover_context(
        root,
        "TASK-1",
        integration_target_ref="HEAD",
        now=NOW,
        persist=False,
    )

    assert not any(
        item.kind == "python_symbol"
        and "WorkingTreeOnlySymbol" in item.detail
        for item in report.evidence
    )


def test_graphify_inferred_neighbor_is_input_only(
    tmp_path: Path,
    monkeypatch,
):
    root = _repo(tmp_path)
    graph_dir = root / "graphify-out"
    graph_dir.mkdir()
    graph = {
        "directed": True,
        "multigraph": False,
        "nodes": [
            {
                "id": "service",
                "label": "PaymentService",
                "file_type": "code",
                "source_file": "pkg/service.py",
            },
            {
                "id": "graph-only",
                "label": "GraphOnly",
                "file_type": "code",
                "source_file": "pkg/graph_only.py",
            },
        ],
        "links": [
            {
                "source": "service",
                "target": "graph-only",
                "relation": "conceptually_related_to",
                "confidence": "INFERRED",
                "confidence_score": 0.75,
                "source_file": "pkg/service.py",
            }
        ],
    }
    (graph_dir / "graph.json").write_text(
        json.dumps(graph),
        encoding="utf-8",
    )
    _patch_project(monkeypatch, _task(), graphify=True)

    report = discovery.discover_context(
        root,
        "TASK-1",
        integration_target_ref="HEAD",
        now=NOW,
        persist=False,
    )

    by_path = {item.path: item for item in report.candidates}
    assert report.graphify_digest is not None
    assert "pkg/graph_only.py" in by_path
    assert "input" in by_path["pkg/graph_only.py"].roles
    assert "write_candidate" not in by_path["pkg/graph_only.py"].roles
    assert any(
        item.provider == "graphify"
        and item.strength == "inferred"
        and item.source_path == "pkg/graph_only.py"
        for item in report.evidence
    )


def test_scope_suggestion_compares_but_never_mutates_catalog(
    tmp_path: Path,
    monkeypatch,
):
    root = _repo(tmp_path)
    catalog = root / "projectctl.parallel.yaml"
    catalog.write_text(
        "schema_kind: projectctl.parallel_scope_catalog\n"
        "schema_version: 1\n"
        "tasks:\n"
        "  TASK-1:\n"
        "    task_id: TASK-1\n"
        "    inputs:\n"
        "      - path: pkg/service.py\n"
        "        kind: exact\n"
        "    writes:\n"
        "      - path: pkg/service.py\n"
        "        kind: exact\n"
        "    resources: []\n",
        encoding="utf-8",
    )
    before = catalog.read_bytes()
    _patch_project(monkeypatch, _task())

    suggestion = discovery.suggest_scope(
        root,
        "TASK-1",
        integration_target_ref="HEAD",
        now=NOW,
        persist=False,
    )

    assert isinstance(suggestion, ContextScopeSuggestion)
    assert suggestion.authoritative is False
    assert suggestion.requires_human_review is True
    assert suggestion.declared_scope_present is True
    assert catalog.read_bytes() == before
    assert "tests/test_service.py" in suggestion.coverage.suggested_writes_not_declared


def test_m50_public_schema_and_cli_surface():
    assert (
        PUBLIC_SCHEMAS["context-discovery-report.v1.schema.json"]
        is ContextDiscoveryReport
    )
    assert (
        PUBLIC_SCHEMAS["context-scope-suggestion.v1.schema.json"]
        is ContextScopeSuggestion
    )

    result = runner.invoke(app, ["context", "--help"])
    assert result.exit_code == 0, result.output
    assert "discover" in result.output
    assert "suggest-scope" in result.output
