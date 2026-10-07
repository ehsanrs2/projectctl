from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
import uuid
from datetime import datetime
from pathlib import Path

from projectctl.application.tasks import capture_task_snapshot
from projectctl.core.digest import digest
from projectctl.core.errors import ConfigurationError, StaleSnapshotError
from projectctl.core.time import utc_now
from projectctl.parallel.catalog import PARALLEL_SCOPE_PATH, load_parallel_scope_catalog
from projectctl.project.loader import load_project_config
from projectctl.project.state import load_project_state, semantic_project_state_digest
from projectctl.scheduler.digests import (
    semantic_task_digest,
    semantic_task_scope_digest,
)
from projectctl.schemas.execution_input import (
    ClaimTransitionEvidence,
    ExecutionCodeInput,
    ExecutionInputLineage,
    ExecutionInputManifest,
    ExecutionPathScope,
    ExecutionTaskInput,
)
from projectctl.schemas.task import TaskSnapshot
from projectctl.schemas.task_claim import TaskClaim, TaskClaimRequest


def _atomic_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(
        value.model_dump(mode="json"),
        indent=2,
        sort_keys=True,
        ensure_ascii=False,
    ) + "\n"
    fd, tmp_name = tempfile.mkstemp(
        prefix=".projectctl-execution-input-",
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


def _git(root: Path, *args: str, check: bool = True, text: bool = True):
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


def execution_code_input_digest(
    root: Path,
    commit: str,
    scope: ExecutionPathScope,
) -> str:
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
            f"Tree execution input {scope.path!r} has no tracked files at "
            f"base {commit[:12]}."
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


def execution_input_semantic_digest(manifest: ExecutionInputManifest) -> str:
    """Digest execution-invalidating inputs, excluding scheduler audit/time identity."""
    return digest(
        {
            "project_id": manifest.project_id,
            "task_id": manifest.task_id,
            "integration_target_ref": manifest.integration_target_ref,
            "base_commit": manifest.base_commit,
            "project_state_digest": manifest.project_state_digest,
            "task_scope_digest": manifest.task_scope_digest,
            "task_scope_ids": manifest.task_scope_ids,
            "task_inputs": [
                {"task_id": item.task_id, "digest": item.digest}
                for item in manifest.task_inputs
            ],
            "references_digest": manifest.references_digest,
            "code_inputs": [
                {
                    "scope": item.scope.model_dump(mode="json"),
                    "digest": item.digest,
                }
                for item in manifest.code_inputs
            ],
            "write_scopes": [
                item.model_dump(mode="json") for item in manifest.write_scopes
            ],
            "resources": manifest.resources,
            "scope_policy_digest": manifest.scope_policy_digest,
            "lineage": (
                manifest.lineage.model_dump(mode="json")
                if manifest.lineage is not None
                else None
            ),
        }
    )


def _optional_scope(root: Path, task_id: str):
    path = root / PARALLEL_SCOPE_PATH
    if not path.exists():
        return None
    catalog = load_parallel_scope_catalog(root)
    return catalog.tasks.get(task_id)


def _task_inputs(snapshot: TaskSnapshot, ids: list[str]) -> list[ExecutionTaskInput]:
    by_id = {item.id: item for item in snapshot.tasks}
    result: list[ExecutionTaskInput] = []
    for task_id in ids:
        task = by_id.get(task_id)
        if task is None:
            raise StaleSnapshotError(
                f"Execution input task {task_id!r} disappeared from task authority."
            )
        result.append(
            ExecutionTaskInput(
                task_id=task_id,
                digest=semantic_task_digest(task),
                task=task,
            )
        )
    return result


def build_execution_input_manifest(
    project_root: Path,
    *,
    task_id: str,
    tasks: TaskSnapshot,
    scheduler_task_snapshot_digest: str,
    project_state_digest: str,
    integration_target_ref: str,
    base_commit: str,
    now: datetime | None = None,
    explicit_scope=None,
    project_id: str | None = None,
) -> ExecutionInputManifest:
    root = project_root.resolve()
    now = now or utc_now()
    if now.tzinfo is None:
        raise ValueError("Execution input time must be timezone-aware.")

    resolved_project_id = (
        project_id
        if project_id is not None
        else load_project_config(root).project.id
    )
    task = next((item for item in tasks.tasks if item.id == task_id), None)
    if task is None:
        raise ConfigurationError(f"Selected task {task_id!r} is missing.")

    scoped_digest, scoped_ids = semantic_task_scope_digest(tasks, task_id)
    scope = explicit_scope if explicit_scope is not None else _optional_scope(root, task_id)
    code_inputs: list[ExecutionCodeInput] = []
    write_scopes: list[ExecutionPathScope] = []
    resources: list[str] = []
    scope_policy_digest = None
    if scope is not None:
        input_scopes = [
            ExecutionPathScope(path=item.path, kind=item.kind)
            for item in scope.inputs
        ]
        code_inputs = [
            ExecutionCodeInput(
                scope=item,
                digest=execution_code_input_digest(root, base_commit, item),
            )
            for item in input_scopes
        ]
        write_scopes = [
            ExecutionPathScope(path=item.path, kind=item.kind)
            for item in scope.writes
        ]
        resources = sorted(scope.resources)
        scope_policy_digest = digest(scope)

    return ExecutionInputManifest(
        input_id=f"execution-input-{uuid.uuid4().hex}",
        project_id=resolved_project_id,
        task_id=task_id,
        integration_target_ref=integration_target_ref,
        base_commit=base_commit,
        project_state_digest=project_state_digest,
        scheduler_task_snapshot_digest=scheduler_task_snapshot_digest,
        task_scope_digest=scoped_digest,
        task_scope_ids=scoped_ids,
        task_inputs=_task_inputs(tasks, scoped_ids),
        references_digest=digest(task.references),
        code_inputs=code_inputs,
        write_scopes=write_scopes,
        resources=resources,
        scope_policy_digest=scope_policy_digest,
        created_at=now,
    )


def persist_execution_input(path: Path, manifest: ExecutionInputManifest) -> None:
    _atomic_json(path, manifest)


def persist_claim_transition(path: Path, evidence: ClaimTransitionEvidence) -> None:
    _atomic_json(path, evidence)


def load_execution_input(path: Path) -> ExecutionInputManifest:
    try:
        return ExecutionInputManifest.model_validate(
            json.loads(path.read_text(encoding="utf-8"))
        )
    except Exception as exc:
        raise ConfigurationError(f"Invalid execution input manifest {path}: {exc}") from exc


def load_claim_transition(path: Path) -> ClaimTransitionEvidence:
    try:
        return ClaimTransitionEvidence.model_validate(
            json.loads(path.read_text(encoding="utf-8"))
        )
    except Exception as exc:
        raise ConfigurationError(f"Invalid claim transition evidence {path}: {exc}") from exc


def _validate_project_base_and_scope(
    root: Path,
    manifest: ExecutionInputManifest,
    *,
    require_target_at_base: bool,
) -> TaskSnapshot:
    config = load_project_config(root)
    if config.project.id != manifest.project_id:
        raise StaleSnapshotError("Execution input project identity changed.")

    if require_target_at_base:
        from projectctl.git import resolve_commit

        if resolve_commit(root, manifest.integration_target_ref) != manifest.base_commit:
            raise StaleSnapshotError("Execution input integration target advanced.")

    state = load_project_state(root, allow_missing=True)
    if semantic_project_state_digest(state) != manifest.project_state_digest:
        raise StaleSnapshotError("Execution input project state changed.")

    scope = _optional_scope(root, manifest.task_id)
    if manifest.scope_policy_digest is None:
        if scope is not None:
            raise StaleSnapshotError(
                "A task scope declaration appeared after execution planning."
            )
    else:
        if scope is None or digest(scope) != manifest.scope_policy_digest:
            raise StaleSnapshotError("Execution scope declaration changed.")

    current_code_inputs = [
        ExecutionCodeInput(
            scope=item.scope,
            digest=execution_code_input_digest(root, manifest.base_commit, item.scope),
        )
        for item in manifest.code_inputs
    ]
    if current_code_inputs != manifest.code_inputs:
        raise StaleSnapshotError("Execution code input evidence changed at the recorded base.")

    return capture_task_snapshot(
        root,
        state="all",
        read_cache_max_age_seconds=0,
    )


def validate_preclaim_execution_input(
    project_root: Path,
    manifest: ExecutionInputManifest,
) -> None:
    root = project_root.resolve()
    tasks = _validate_project_base_and_scope(
        root,
        manifest,
        require_target_at_base=True,
    )
    current = _task_inputs(tasks, manifest.task_scope_ids)
    if [
        (item.task_id, item.digest) for item in current
    ] != [
        (item.task_id, item.digest) for item in manifest.task_inputs
    ]:
        raise StaleSnapshotError("Execution task/dependency inputs changed before claim.")


def build_claim_transition_evidence(
    project_root: Path,
    *,
    run_id: str,
    manifest: ExecutionInputManifest,
    request: TaskClaimRequest,
    claim: TaskClaim,
    claimer,
) -> ClaimTransitionEvidence:
    root = project_root.resolve()
    tasks = _validate_project_base_and_scope(
        root,
        manifest,
        require_target_at_base=True,
    )
    current_inputs = _task_inputs(tasks, manifest.task_scope_ids)
    pre_by_id = {item.task_id: item for item in manifest.task_inputs}
    post_by_id = {item.task_id: item for item in current_inputs}

    before = pre_by_id[manifest.task_id].task
    after = post_by_id[manifest.task_id].task
    request_digest = digest(request)
    if (
        request.task_id != manifest.task_id
        or request.run_id != run_id
        or request.base_commit != manifest.base_commit
        or request.integration_target_ref != manifest.integration_target_ref
        or claim.task_id != request.task_id
        or claim.run_id != request.run_id
        or claim.base_commit != request.base_commit
        or claim.integration_target_ref != request.integration_target_ref
        or claim.claim_token != request.claim_token
        or claim.request_digest != request_digest
    ):
        raise StaleSnapshotError(
            "Durable claim identity does not match the execution input/request."
        )
    if not claimer.validate(claim):
        raise StaleSnapshotError(
            "Durable task claim no longer proves current execution ownership."
        )
    if not claimer.validate_transition(claim, before, after):
        raise StaleSnapshotError(
            "Selected task post-claim state is not the expected result of this claim."
        )

    for task_id in manifest.task_scope_ids:
        if task_id == manifest.task_id:
            continue
        if pre_by_id[task_id].digest != post_by_id[task_id].digest:
            raise StaleSnapshotError(
                f"Relevant dependency {task_id!r} changed during claim acquisition."
            )

    scoped_digest, scoped_ids = semantic_task_scope_digest(tasks, manifest.task_id)
    return ClaimTransitionEvidence(
        run_id=run_id,
        task_id=manifest.task_id,
        provider=claim.provider,
        execution_input_digest=execution_input_semantic_digest(manifest),
        claim_request_digest=request_digest,
        claim_digest=digest(claim),
        preclaim_task_digest=pre_by_id[manifest.task_id].digest,
        postclaim_task_digest=post_by_id[manifest.task_id].digest,
        postclaim_task_scope_digest=scoped_digest,
        postclaim_task_scope_ids=scoped_ids,
        postclaim_task_inputs=current_inputs,
        observed_at=utc_now(),
    )


def validate_admitted_execution_input(
    project_root: Path,
    manifest: ExecutionInputManifest,
    transition: ClaimTransitionEvidence,
    *,
    require_target_at_base: bool = True,
) -> None:
    root = project_root.resolve()
    if transition.execution_input_digest != execution_input_semantic_digest(manifest):
        raise StaleSnapshotError("Claim transition is bound to another execution input.")
    if transition.task_id != manifest.task_id:
        raise StaleSnapshotError("Claim transition task identity changed.")

    tasks = _validate_project_base_and_scope(
        root,
        manifest,
        require_target_at_base=require_target_at_base,
    )
    current = _task_inputs(tasks, transition.postclaim_task_scope_ids)
    scoped_digest, scoped_ids = semantic_task_scope_digest(tasks, manifest.task_id)
    if (
        scoped_digest != transition.postclaim_task_scope_digest
        or scoped_ids != transition.postclaim_task_scope_ids
    ):
        raise StaleSnapshotError(
            "Claim-admitted task/dependency scope changed after ownership acquisition."
        )
    if [
        (item.task_id, item.digest) for item in current
    ] != [
        (item.task_id, item.digest) for item in transition.postclaim_task_inputs
    ]:
        raise StaleSnapshotError(
            "Claim-admitted task/dependency inputs changed after ownership acquisition."
        )


def derive_reapplied_execution_input(
    source: ExecutionInputManifest,
    *,
    target_base_commit: str,
    reapplication_id: str,
) -> ExecutionInputManifest:
    return source.model_copy(
        update={
            "input_id": f"execution-input-{uuid.uuid4().hex}",
            "base_commit": target_base_commit,
            "lineage": ExecutionInputLineage(
                source_execution_input_digest=execution_input_semantic_digest(source),
                transformation="parallel_reapplication",
                reapplication_id=reapplication_id,
            ),
            "created_at": utc_now(),
        }
    )
