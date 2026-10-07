from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
import uuid
from datetime import datetime
from pathlib import Path, PurePosixPath

from projectctl.application.tasks import capture_task_snapshot
from projectctl.application.execution_inputs import (
    build_preclaim_execution_input,
    semantic_execution_input_digest,
)
from projectctl.core.digest import digest
from projectctl.core.enums import TaskStatus
from projectctl.core.errors import ConfigurationError, StaleSnapshotError
from projectctl.core.time import utc_now
from projectctl.git.worktrees import current_branch, resolve_commit
from projectctl.parallel.catalog import task_parallel_scope
from projectctl.project.loader import load_project_config
from projectctl.project.state import (
    load_project_state,
    semantic_project_state_digest,
)
from projectctl.scheduler.digests import (
    semantic_task_scope_digest,
    semantic_task_snapshot_digest,
)
from projectctl.schemas.parallel import (
    ParallelConflict,
    ParallelInputEvidence,
    ParallelPathScope,
    ParallelPlan,
    ParallelSafetyDecision,
)


def _git(
    project_root: Path,
    *args: str,
    check: bool = True,
    text: bool = True,
):
    completed = subprocess.run(
        ["git", "-C", str(project_root), *args],
        capture_output=True,
        text=text,
        check=False,
    )
    if check and completed.returncode != 0:
        stderr = (
            completed.stderr.strip()
            if isinstance(completed.stderr, str)
            else completed.stderr.decode("utf-8", errors="replace").strip()
        )
        raise ConfigurationError(
            f"Git command failed while building parallel proof: {stderr or args!r}"
        )
    return completed


def _git_object_type(
    project_root: Path,
    commit: str,
    path: str,
) -> str:
    result = _git(
        project_root,
        "cat-file",
        "-t",
        f"{commit}:{path}",
        check=False,
    )
    if result.returncode != 0:
        raise ConfigurationError(
            f"Parallel input scope {path!r} does not exist at base {commit[:12]}."
        )
    return result.stdout.strip()


def _blob_digest(project_root: Path, commit: str, path: str) -> str:
    result = _git(
        project_root,
        "show",
        f"{commit}:{path}",
        text=False,
    )
    return "sha256:" + hashlib.sha256(result.stdout).hexdigest()


def _input_scope_digest(
    project_root: Path,
    commit: str,
    scope: ParallelPathScope,
) -> str:
    object_type = _git_object_type(project_root, commit, scope.path)
    if scope.kind == "exact":
        if object_type != "blob":
            raise ConfigurationError(
                f"Exact parallel input {scope.path!r} must resolve to a tracked file "
                f"at base {commit[:12]}, found {object_type!r}."
            )
        return digest(
            {
                "kind": "exact",
                "path": scope.path,
                "blob": _blob_digest(project_root, commit, scope.path),
            }
        )

    if object_type != "tree":
        raise ConfigurationError(
            f"Tree parallel input {scope.path!r} must resolve to a tracked directory "
            f"at base {commit[:12]}, found {object_type!r}."
        )
    result = _git(
        project_root,
        "ls-tree",
        "-r",
        "--full-tree",
        "--name-only",
        commit,
        "--",
        scope.path,
    )
    files = [
        line.strip()
        for line in result.stdout.splitlines()
        if line.strip()
    ]
    prefix = scope.path.rstrip("/") + "/"
    files = sorted(
        path for path in files if path.startswith(prefix)
    )
    if not files:
        raise ConfigurationError(
            f"Tree parallel input {scope.path!r} has no tracked files at "
            f"base {commit[:12]}."
        )
    return digest(
        {
            "kind": "tree",
            "path": scope.path,
            "files": [
                {
                    "path": path,
                    "blob": _blob_digest(project_root, commit, path),
                }
                for path in files
            ],
        }
    )


def _atomic_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(
        value.model_dump(mode="json"),
        indent=2,
        ensure_ascii=False,
        sort_keys=True,
    ) + "\n"
    fd, tmp_name = tempfile.mkstemp(
        prefix=".projectctl-parallel-",
        suffix=".json",
        dir=path.parent,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    finally:
        try:
            Path(tmp_name).unlink()
        except FileNotFoundError:
            pass


def _scope_contains(scope: ParallelPathScope, path: str) -> bool:
    if scope.kind == "exact":
        return scope.path == path
    prefix = scope.path.rstrip("/") + "/"
    return path == scope.path or path.startswith(prefix)


def _path_scopes_overlap(
    left: ParallelPathScope,
    right: ParallelPathScope,
) -> bool:
    if left.kind == "exact" and right.kind == "exact":
        return left.path == right.path
    if left.kind == "tree":
        if _scope_contains(left, right.path):
            return True
    if right.kind == "tree":
        if _scope_contains(right, left.path):
            return True
    return False


def _first_overlap(
    left: list[ParallelPathScope],
    right: list[ParallelPathScope],
) -> tuple[ParallelPathScope, ParallelPathScope] | None:
    for left_scope in left:
        for right_scope in right:
            if _path_scopes_overlap(left_scope, right_scope):
                return left_scope, right_scope
    return None


def build_parallel_plan(
    project_root: Path,
    task_id: str,
    *,
    integration_target_ref: str | None = None,
    now: datetime | None = None,
    persist: bool = True,
) -> ParallelPlan:
    root = project_root.resolve()
    now = now or utc_now()
    if now.tzinfo is None:
        raise ValueError("Parallel planning time must be timezone-aware.")

    config = load_project_config(root)
    state = load_project_state(root, allow_missing=True)
    tasks = capture_task_snapshot(
        root,
        state="all",
        read_cache_max_age_seconds=0,
    )
    task = next((item for item in tasks.tasks if item.id == task_id), None)
    if task is None:
        raise ConfigurationError(f"Unknown task for parallel planning: {task_id}")
    if task.status != TaskStatus.READY:
        raise ConfigurationError(
            f"Task {task_id!r} is {task.status.value!r}; parallel planning requires READY."
        )

    scope = task_parallel_scope(root, task_id)
    target_ref = integration_target_ref or current_branch(root)
    base_commit = resolve_commit(root, target_ref)
    scoped_task_digest, scoped_task_ids = semantic_task_scope_digest(tasks, task_id)
    project_state_digest = semantic_project_state_digest(state)
    execution_input = build_preclaim_execution_input(
        root,
        tasks=tasks,
        task_id=task_id,
        base_commit=base_commit,
        integration_target_ref=target_ref,
        scheduler_task_snapshot_digest=semantic_task_snapshot_digest(tasks),
        now=now,
    )
    input_evidence = [
        ParallelInputEvidence(
            scope=item,
            digest=_input_scope_digest(root, base_commit, item),
        )
        for item in scope.inputs
    ]

    plan = ParallelPlan(
        plan_id=f"parallel-plan-{uuid.uuid4().hex}",
        project_id=config.project.id,
        task_id=task_id,
        integration_target_ref=target_ref,
        base_commit=base_commit,
        project_state_digest=project_state_digest,
        scoped_task_digest=scoped_task_digest,
        scoped_task_ids=scoped_task_ids,
        scope_digest=digest(scope),
        inputs=input_evidence,
        writes=scope.writes,
        resources=sorted(scope.resources),
        execution_input_digest=semantic_execution_input_digest(execution_input),
        created_at=now,
    )
    if persist:
        _atomic_json(
            root / ".projectctl" / "parallel" / "plans" / f"{plan.plan_id}.json",
            plan,
        )
        _atomic_json(
            root
            / ".projectctl"
            / "parallel"
            / "inputs"
            / f"{plan.plan_id}.json",
            execution_input,
        )
    return plan


def revalidate_parallel_plan(
    project_root: Path,
    plan: ParallelPlan,
) -> None:
    root = project_root.resolve()
    config = load_project_config(root)
    if config.project.id != plan.project_id:
        raise StaleSnapshotError(
            "Parallel plan project identity no longer matches this project."
        )
    if resolve_commit(root, plan.integration_target_ref) != plan.base_commit:
        raise StaleSnapshotError(
            "Parallel plan base is stale relative to its integration target."
        )

    state = load_project_state(root, allow_missing=True)
    if semantic_project_state_digest(state) != plan.project_state_digest:
        raise StaleSnapshotError(
            "Parallel plan project-state input changed."
        )

    tasks = capture_task_snapshot(
        root,
        state="all",
        read_cache_max_age_seconds=0,
    )
    scoped_digest, scoped_ids = semantic_task_scope_digest(tasks, plan.task_id)
    if scoped_digest != plan.scoped_task_digest or scoped_ids != plan.scoped_task_ids:
        raise StaleSnapshotError(
            "Parallel plan scoped task/dependency input changed."
        )

    scope = task_parallel_scope(root, plan.task_id)
    if digest(scope) != plan.scope_digest:
        raise StaleSnapshotError(
            "Parallel task scope declaration changed."
        )

    current_inputs = [
        ParallelInputEvidence(
            scope=item,
            digest=_input_scope_digest(root, plan.base_commit, item),
        )
        for item in scope.inputs
    ]
    if current_inputs != plan.inputs:
        raise StaleSnapshotError(
            "Parallel plan file/tree inputs changed at the recorded base."
        )


def assess_parallel_safety(
    left: ParallelPlan,
    right: ParallelPlan,
    *,
    now: datetime | None = None,
    persist_root: Path | None = None,
) -> ParallelSafetyDecision:
    now = now or utc_now()
    if now.tzinfo is None:
        raise ValueError("Parallel safety evaluation time must be timezone-aware.")

    conflicts: list[ParallelConflict] = []

    if left.project_id != right.project_id:
        conflicts.append(
            ParallelConflict(
                reason="project_mismatch",
                detail=(
                    f"project_id differs: {left.project_id!r} vs "
                    f"{right.project_id!r}"
                ),
            )
        )

    if left.task_id == right.task_id:
        conflicts.append(
            ParallelConflict(
                reason="same_task",
                detail=f"Both plans target task {left.task_id!r}.",
            )
        )

    if left.project_state_digest != right.project_state_digest:
        conflicts.append(
            ParallelConflict(
                reason="project_state_mismatch",
                detail="Plans were derived from different project-state inputs.",
            )
        )

    if (
        left.task_id in right.scoped_task_ids
        or right.task_id in left.scoped_task_ids
    ):
        conflicts.append(
            ParallelConflict(
                reason="task_dependency",
                detail=(
                    f"Task dependency relationship exists between "
                    f"{left.task_id!r} and {right.task_id!r}."
                ),
            )
        )

    write_write = _first_overlap(left.writes, right.writes)
    if write_write is not None:
        conflicts.append(
            ParallelConflict(
                reason="write_write_overlap",
                detail=(
                    f"Write scopes overlap: {write_write[0].path!r} "
                    f"({write_write[0].kind}) vs {write_write[1].path!r} "
                    f"({write_write[1].kind})."
                ),
            )
        )

    right_inputs = [item.scope for item in right.inputs]
    left_write_right_input = _first_overlap(left.writes, right_inputs)
    if left_write_right_input is not None:
        conflicts.append(
            ParallelConflict(
                reason="write_input_overlap",
                detail=(
                    f"Left write {left_write_right_input[0].path!r} can invalidate "
                    f"right input {left_write_right_input[1].path!r}."
                ),
            )
        )

    left_inputs = [item.scope for item in left.inputs]
    right_write_left_input = _first_overlap(right.writes, left_inputs)
    if right_write_left_input is not None:
        conflicts.append(
            ParallelConflict(
                reason="write_input_overlap",
                detail=(
                    f"Right write {right_write_left_input[0].path!r} can invalidate "
                    f"left input {right_write_left_input[1].path!r}."
                ),
            )
        )

    shared_resources = sorted(set(left.resources) & set(right.resources))
    if shared_resources:
        conflicts.append(
            ParallelConflict(
                reason="resource_overlap",
                detail="Exclusive resource keys overlap: " + ", ".join(shared_resources),
            )
        )

    shared_target = left.integration_target_ref == right.integration_target_ref
    shared_base = left.base_commit == right.base_commit
    if shared_target and not shared_base:
        conflicts.append(
            ParallelConflict(
                reason="target_base_mismatch",
                detail=(
                    f"Shared integration target {left.integration_target_ref!r} "
                    "was planned from different base commits."
                ),
            )
        )

    independent = not conflicts
    decision = ParallelSafetyDecision(
        decision_id=f"parallel-safety-{uuid.uuid4().hex}",
        evaluated_at=now,
        left_plan_digest=digest(left),
        right_plan_digest=digest(right),
        independent=independent,
        shared_target=shared_target,
        shared_base=shared_base,
        integration_requires_reverification=(
            independent and shared_target
        ),
        conflicts=conflicts,
    )

    if persist_root is not None:
        root = persist_root.resolve()
        _atomic_json(
            root
            / ".projectctl"
            / "parallel"
            / "decisions"
            / f"{decision.decision_id}.json",
            decision,
        )
    return decision
