import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

from projectctl.application.claims import (
    load_durable_claim,
    persist_claim,
    persist_claim_request,
)
from projectctl.core.digest import digest
from projectctl.core.enums import (
    ModelProfile,
    ReasoningLevel,
    RunStatus,
)
from projectctl.core.errors import RunStoreError
from projectctl.project.bootstrap import initialize_project
from projectctl.schemas.run import RunManifest, WorkerDescriptor
from projectctl.schemas.task_claim import TaskClaim, TaskClaimRequest
from projectctl.storage.runs import RunStore


NOW = datetime(2026, 10, 4, 6, 0, tzinfo=timezone.utc)
BASE = "a" * 40


def setup_run(tmp_path: Path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    monkeypatch.setenv("PROJECTCTL_HOME", str(tmp_path / "home"))
    initialize_project(repo)
    manifest = RunManifest(
        run_id="run-1",
        task_id="bd-1",
        execution_plan_digest="plan",
        status=RunStatus.PREPARING,
        base_commit=BASE,
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
    request = TaskClaimRequest(
        task_id="bd-1",
        run_id="run-1",
        actor="projectctl:test",
        base_commit=BASE,
        integration_target_ref="main",
        claim_token="a" * 32,
        requested_at=NOW,
    )
    claim = TaskClaim(
        provider="beads",
        task_id=request.task_id,
        run_id=request.run_id,
        actor=request.actor,
        base_commit=request.base_commit,
        integration_target_ref=request.integration_target_ref,
        claim_token=request.claim_token,
        request_digest=digest(request),
        acquired=True,
        observed_at=NOW,
    )
    return request, claim


def test_durable_claim_is_bound_to_request_and_run_events(tmp_path: Path, monkeypatch):
    repo, store = setup_run(tmp_path, monkeypatch)
    request, claim = values()
    persist_claim_request(repo, store=store, request=request)
    persist_claim(repo, store=store, request=request, claim=claim)

    loaded_request, loaded_claim = load_durable_claim(
        repo,
        store=store,
        run_id="run-1",
    )
    assert loaded_request == request
    assert loaded_claim == claim


def test_claim_artifact_tamper_is_detected(tmp_path: Path, monkeypatch):
    repo, store = setup_run(tmp_path, monkeypatch)
    request, claim = values()
    persist_claim_request(repo, store=store, request=request)
    persist_claim(repo, store=store, request=request, claim=claim)

    path = repo / ".projectctl" / "runs" / "run-1" / "task-claim.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["actor"] = "tampered"
    path.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(RunStoreError, match="anchored"):
        load_durable_claim(repo, store=store, run_id="run-1")


def test_legacy_missing_is_allowed_only_when_both_claim_artifacts_are_absent(
    tmp_path: Path, monkeypatch
):
    repo, store = setup_run(tmp_path, monkeypatch)
    assert load_durable_claim(
        repo,
        store=store,
        run_id="run-1",
        allow_legacy_missing=True,
    ) is None

    request, claim = values()
    persist_claim_request(repo, store=store, request=request)
    with pytest.raises(RunStoreError, match="incomplete"):
        load_durable_claim(
            repo,
            store=store,
            run_id="run-1",
            allow_legacy_missing=True,
        )
