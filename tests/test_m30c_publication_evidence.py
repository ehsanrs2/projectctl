import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

from projectctl.application.publication import (
    load_publication_manifest,
    persist_publication_manifest,
    persist_publication_request,
)
from projectctl.core.digest import digest
from projectctl.core.enums import ModelProfile, ReasoningLevel, RunStatus
from projectctl.core.errors import RunStoreError
from projectctl.project.bootstrap import initialize_project
from projectctl.schemas.delivery import PublicationManifest, PublicationRequest
from projectctl.schemas.run import RunManifest, WorkerDescriptor
from projectctl.storage.runs import RunStore


NOW = datetime(2026, 10, 4, 8, 0, tzinfo=timezone.utc)
BASE = "a" * 40
CANDIDATE = "b" * 40


def setup_run(tmp_path: Path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    monkeypatch.setenv("PROJECTCTL_HOME", str(tmp_path / "home"))
    initialize_project(repo)
    manifest = RunManifest(
        run_id="run-1",
        task_id="gh-7",
        execution_plan_digest="plan",
        status=RunStatus.INTEGRATING,
        base_commit=BASE,
        candidate_commit=CANDIDATE,
        branch_name="projectctl/run/run-1",
        worktree_id="run-1",
        worker=WorkerDescriptor(
            provider="codex",
            model_profile=ModelProfile.BALANCED,
            reasoning=ReasoningLevel.MEDIUM,
        ),
    )
    store = RunStore(repo)
    store.create(
        manifest,
        worktree_path=tmp_path / "worktree",
        now=NOW,
    )
    return repo, store


def values():
    request = PublicationRequest(
        run_id="run-1",
        task_id="gh-7",
        provider="github",
        repository="acme/widget",
        remote_name="origin",
        target_ref="main",
        base_commit=BASE,
        candidate_commit=CANDIDATE,
        evidence_manifest=".projectctl/runs/run-1/evidence-manifest.json",
        evidence_digest="sha256:evidence",
        requested_at=NOW,
    )
    manifest = PublicationManifest(
        run_id=request.run_id,
        task_id=request.task_id,
        provider=request.provider,
        repository=request.repository,
        remote_name=request.remote_name,
        target_ref=request.target_ref,
        base_commit=request.base_commit,
        candidate_commit=request.candidate_commit,
        evidence_manifest=request.evidence_manifest,
        evidence_digest=request.evidence_digest,
        request_digest=digest(request),
        remote_before=BASE,
        remote_after=CANDIDATE,
        published=True,
        observed_at=NOW,
    )
    return request, manifest


def test_publication_evidence_is_bound_to_request_and_run_events(tmp_path: Path, monkeypatch):
    repo, store = setup_run(tmp_path, monkeypatch)
    request, manifest = values()

    persist_publication_request(repo, store=store, request=request)
    persist_publication_manifest(
        repo,
        store=store,
        request=request,
        manifest=manifest,
    )

    loaded_request, loaded_manifest = load_publication_manifest(
        repo,
        store=store,
        run_id="run-1",
    )
    assert loaded_request == request
    assert loaded_manifest == manifest


def test_publication_manifest_tamper_is_detected(tmp_path: Path, monkeypatch):
    repo, store = setup_run(tmp_path, monkeypatch)
    request, manifest = values()
    persist_publication_request(repo, store=store, request=request)
    persist_publication_manifest(
        repo,
        store=store,
        request=request,
        manifest=manifest,
    )

    path = repo / ".projectctl" / "runs" / "run-1" / "publication-manifest.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["remote_after"] = "c" * 40
    path.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(RunStoreError, match="anchored"):
        load_publication_manifest(repo, store=store, run_id="run-1")
