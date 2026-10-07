from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime
from pathlib import Path

from projectctl.application.tasks import capture_task_snapshot
from projectctl.core.digest import digest
from projectctl.core.errors import ConfigurationError, RunStoreError, StaleSnapshotError
from projectctl.core.time import utc_now
from projectctl.git import resolve_commit
from projectctl.parallel.catalog import PARALLEL_SCOPE_PATH, load_parallel_scope_catalog
from projectctl.project.loader import load_project_config
from projectctl.project.state import load_project_state, semantic_project_state_digest
from projectctl.scheduler.digests import (
    semantic_task_digest,
    semantic_task_scope_digest,
)
from projectctl.schemas.execution_input import (
    ClaimTransitionEvidence,
    ExecutionInputEvidence,
    ExecutionInputManifest,
    ExecutionPathScope,
)
from projectctl.schemas.parallel import ParallelTaskScope
from projectctl.schemas.task import NormalizedTask, TaskSnapshot
from projectctl.schemas.task_claim import TaskClaim


def semantic_execution_input_digest(manifest: ExecutionInputManifest) -> str:
    payload = manifest.model_dump(mode="json")
    payload.pop("created_at", None)
    transition = payload.get("claim_transition")
    if isinstance(transition, dict):
        transition.pop("validated_at", None)
    return digest(payload)


def _git(
    root: Path,
    *args: str,
    check: bool = True,
    text: bool = True,
):
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=text,
        check=False,
    )
    if check and result.returncode != 0:
        stderr = result.stderr
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", errors="replace")
        stdout = result.stdout
        if isinstance(stdout, bytes):
            stdout = stdout.decode("utf-8", errors="replace")
        raise ConfigurationError(
            (stderr or stdout or f"git {' '.join(args)} failed").strip()
        )
    return result


def _git_object_type(root: Path, commit: str, path: str) -> str:
    result = _git(root, "cat-file", "-t", f"{commit}:{path}", check=False)
    if result.returncode != 0:
        raise ConfigurationError(
            f"Execution input scope {path!r} does not exist at base {commit[:12]}."
        )
    return result.stdout.strip()


def _blob_digest(root: Path, commit: str, path: str) -> str:
    result = _git(root, "show", f"{commit}:{path}", text=False)
    return "sha256:" + hashlib.sha256(result.stdout).hexdigest()


def input_scope_digest(
    project_root: Path,
    commit: str,
    scope: ExecutionPathScope,
) -> str:
    root = project_root.resolve()
    object_type = _git_object_type(root, commit, scope.path)
    if scope.kind == "exact":
        if object_type != "blob":
            raise ConfigurationError(
                f"Exact execution input {scope.path!r} must resolve to a tracked file "
                f"at base {commit[:12]}, found {object_type!r}."
            )
        return digest(
            {
                "kind": "exact",
                "path": scope.path,
                "blob": _blob_digest(root, commit, scope.path),
            }
        )

    if object_type != "tree":
        raise ConfigurationError(
            f"Tree execution input {scope.path!r} must resolve to a tracked directory "
            f"at base {commit[:12]}, found {object_type!r}."
        )
    result = _git(
        root,
        "ls-tree",
        "-r",
        "--full-tree",
        "--name-only",
        commit,
        "--",
        scope.path,
    )
    prefix = scope.path.rstrip("/") + "/"
    files = sorted(
        line.strip()
        for line in result.stdout.splitlines()
        if line.strip() and line.strip().startswith(prefix)
    )
    if not files:
        raise ConfigurationError(
            f"Tree execution input {scope.path!r} has no tracked files at base "
            f"{commit[:12]}."
        )
    return digest(
        {
            "kind": "tree",
            "path": scope.path,
            "files": [
                {"path": path, "blob": _blob_digest(root, commit, path)}
                for path in files
            ],
        }
    )


def _optional_task_scope(root: Path, task_id: str) -> ParallelTaskScope | None:
    path = root / PARALLEL_SCOPE_PATH
    if not path.exists():
        return None
    catalog = load_parallel_scope_catalog(root)
    return catalog.tasks.get(task_id)


def _execution_scope_material(
    root: Path,
    *,
    task_id: str,
    base_commit: str,
) -> tuple[
    str | None,
    list[ExecutionInputEvidence],
    list[ExecutionPathScope],
    list[str],
]:
    scope = _optional_task_scope(root, task_id)
    if scope is None:
        return None, [], [], []

    inputs = [
        ExecutionInputEvidence(
            scope=ExecutionPathScope(path=item.path, kind=item.kind),
            digest=input_scope_digest(
                root,
                base_commit,
                ExecutionPathScope(path=item.path, kind=item.kind),
            ),
        )
        for item in scope.inputs
    ]
    writes = [
        ExecutionPathScope(path=item.path, kind=item.kind)
        for item in scope.writes
    ]
    return digest(scope), inputs, writes, sorted(scope.resources)


def build_preclaim_execution_input(
    project_root: Path,
    *,
    tasks: TaskSnapshot,
    task_id: str,
    base_commit: str,
    integration_target_ref: str,
    scheduler_task_snapshot_digest: str,
    now: datetime | None = None,
) -> ExecutionInputManifest:
    root = project_root.resolve()
    now = now or utc_now()
    if now.tzinfo is None:
        raise ValueError("Execution-input time must be timezone-aware.")

    config = load_project_config(root)
    state = load_project_state(root, allow_missing=True)
    scoped_digest, scoped_ids = semantic_task_scope_digest(tasks, task_id)
    task = next((item for item in tasks.tasks if item.id == task_id), None)
    if task is None:
        raise ConfigurationError(
            f"Execution input cannot find selected task {task_id!r}."
        )

    scope_digest, inputs, writes, resources = _execution_scope_material(
        root,
        task_id=task_id,
        base_commit=base_commit,
    )
    return ExecutionInputManifest(
        project_id=config.project.id,
        task_id=task_id,
        task_provider=tasks.provider,
        scheduler_task_snapshot_digest=scheduler_task_snapshot_digest,
        project_state_digest=semantic_project_state_digest(state),
        preclaim_task_scope_digest=scoped_digest,
        admitted_task_scope_digest=scoped_digest,
        scoped_task_ids=scoped_ids,
        base_commit=base_commit,
        integration_target_ref=integration_target_ref,
        scope_digest=scope_digest,
        inputs=inputs,
        writes=writes,
        resources=resources,
        phase="preclaim",
        lineage_kind="initial",
        created_at=now,
    )


def _task_by_id(snapshot: TaskSnapshot, task_id: str) -> NormalizedTask:
    task = next((item for item in snapshot.tasks if item.id == task_id), None)
    if task is None:
        raise StaleSnapshotError(
            f"Execution input task {task_id!r} disappeared from task authority."
        )
    return task


def finalize_execution_input(
    preclaim: ExecutionInputManifest,
    *,
    before_snapshot: TaskSnapshot,
    after_snapshot: TaskSnapshot,
    claim: TaskClaim,
    claimer,
    now: datetime | None = None,
) -> ExecutionInputManifest:
    now = now or utc_now()
    if preclaim.phase != "preclaim":
        raise ValueError("Only a preclaim execution input can be finalized.")
    if not claim.acquired or claim.task_id != preclaim.task_id:
        raise StaleSnapshotError(
            "Execution input cannot bind an unowned or different task claim."
        )
    if before_snapshot.provider != after_snapshot.provider:
        raise StaleSnapshotError("Task authority provider changed during claim.")

    before_scope_digest, before_ids = semantic_task_scope_digest(
        before_snapshot, preclaim.task_id
    )
    if (
        before_scope_digest != preclaim.preclaim_task_scope_digest
        or before_ids != preclaim.scoped_task_ids
    ):
        raise StaleSnapshotError(
            "Task/dependency input changed before claim transition could be bound."
        )

    after_scope_digest, after_ids = semantic_task_scope_digest(
        after_snapshot, preclaim.task_id
    )
    if after_ids != preclaim.scoped_task_ids:
        raise StaleSnapshotError(
            "Task dependency membership changed while acquiring the claim."
        )

    before_task = _task_by_id(before_snapshot, preclaim.task_id)
    after_task = _task_by_id(after_snapshot, preclaim.task_id)
    if not claimer.validate_transition(before_task, after_task, claim):
        raise StaleSnapshotError(
            "Post-claim selected-task state is not the expected consequence "
            "of the durable claim."
        )

    before_by_id = {item.id: item for item in before_snapshot.tasks}
    after_by_id = {item.id: item for item in after_snapshot.tasks}
    for dependency_id in preclaim.scoped_task_ids:
        if dependency_id == preclaim.task_id:
            continue
        before_dep = before_by_id.get(dependency_id)
        after_dep = after_by_id.get(dependency_id)
        if before_dep is None or after_dep is None:
            raise StaleSnapshotError(
                f"Relevant dependency {dependency_id!r} disappeared during claim."
            )
        if semantic_task_digest(before_dep) != semantic_task_digest(after_dep):
            raise StaleSnapshotError(
                f"Relevant dependency {dependency_id!r} changed during claim."
            )

    before_selected_digest = semantic_task_digest(before_task)
    after_selected_digest = semantic_task_digest(after_task)
    transition = ClaimTransitionEvidence(
        provider=claim.provider,
        claim_digest=digest(claim),
        before_selected_task_digest=before_selected_digest,
        after_selected_task_digest=after_selected_digest,
        transition_kind=(
            "unchanged"
            if before_selected_digest == after_selected_digest
            else "provider_native"
        ),
        validated_at=now,
    )
    return preclaim.model_copy(
        update={
            "admitted_task_scope_digest": after_scope_digest,
            "phase": "admitted",
            "claim_transition": transition,
            "created_at": now,
        }
    )


def revalidate_execution_input(
    project_root: Path,
    manifest: ExecutionInputManifest,
    *,
    require_admitted: bool = True,
) -> TaskSnapshot:
    root = project_root.resolve()
    if require_admitted and manifest.phase != "admitted":
        raise StaleSnapshotError(
            "Worker/verification execution requires an admitted execution input."
        )

    config = load_project_config(root)
    if config.project.id != manifest.project_id:
        raise StaleSnapshotError("Execution-input project identity changed.")
    if resolve_commit(root, manifest.integration_target_ref) != manifest.base_commit:
        raise StaleSnapshotError(
            "Execution-input base is stale relative to its integration target."
        )
    state = load_project_state(root, allow_missing=True)
    if semantic_project_state_digest(state) != manifest.project_state_digest:
        raise StaleSnapshotError("Execution-input project state changed.")

    tasks = capture_task_snapshot(
        root,
        state="all",
        read_cache_max_age_seconds=0,
    )
    current_digest, current_ids = semantic_task_scope_digest(
        tasks, manifest.task_id
    )
    expected_task_digest = (
        manifest.admitted_task_scope_digest
        if manifest.phase == "admitted"
        else manifest.preclaim_task_scope_digest
    )
    if (
        current_digest != expected_task_digest
        or current_ids != manifest.scoped_task_ids
    ):
        raise StaleSnapshotError(
            "Execution-input task/dependency state changed after claim admission."
        )

    scope_digest, inputs, writes, resources = _execution_scope_material(
        root,
        task_id=manifest.task_id,
        base_commit=manifest.base_commit,
    )
    if scope_digest != manifest.scope_digest:
        raise StaleSnapshotError("Execution input scope declaration changed.")
    if inputs != manifest.inputs or writes != manifest.writes or resources != manifest.resources:
        raise StaleSnapshotError("Execution input code/resource scope changed.")
    return tasks


def load_execution_input(
    run_dir: Path,
    *,
    expected_digest: str | None = None,
) -> ExecutionInputManifest:
    path = run_dir / "execution-input.json"
    if not path.exists():
        raise RunStoreError(f"Missing run artifact: {path}")
    try:
        manifest = ExecutionInputManifest.model_validate(
            json.loads(path.read_text(encoding="utf-8"))
        )
    except Exception as exc:
        raise RunStoreError(f"Invalid run artifact {path.name}: {exc}") from exc
    if (
        expected_digest is not None
        and semantic_execution_input_digest(manifest) != expected_digest
    ):
        raise RunStoreError(
            "ExecutionInputManifest digest does not match its ExecutionPlan binding."
        )
    return manifest


def execution_input_path_allowed(
    scopes: list[ExecutionPathScope],
    path: str,
) -> bool:
    for scope in scopes:
        if scope.kind == "exact" and scope.path == path:
            return True
        if scope.kind == "tree":
            prefix = scope.path.rstrip("/") + "/"
            if path == scope.path or path.startswith(prefix):
                return True
    return False


def rebind_execution_input_base(
    project_root: Path,
    manifest: ExecutionInputManifest,
    *,
    new_base: str,
    now: datetime | None = None,
) -> ExecutionInputManifest:
    root = project_root.resolve()
    now = now or utc_now()
    old_digest = semantic_execution_input_digest(manifest)
    new_inputs = [
        ExecutionInputEvidence(
            scope=item.scope,
            digest=input_scope_digest(root, new_base, item.scope),
        )
        for item in manifest.inputs
    ]
    if [item.digest for item in new_inputs] != [item.digest for item in manifest.inputs]:
        raise StaleSnapshotError(
            "Reapplication target changed declared execution input content."
        )
    return manifest.model_copy(
        update={
            "base_commit": new_base,
            "inputs": new_inputs,
            "lineage_kind": "reapplication",
            "parent_execution_input_digest": old_digest,
            "created_at": now,
        }
    )
