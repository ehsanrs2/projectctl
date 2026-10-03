from __future__ import annotations

import json
import os
import socket
import shutil
import subprocess
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path

from projectctl.application.scheduling import collect_scheduling_bundle
from projectctl.application.tasks import capture_task_snapshot
from projectctl.core.digest import digest
from projectctl.core.enums import RunStatus, RunTerminalReason
from projectctl.core.errors import (
    ClaimConflictError,
    ConfigurationError,
    RunStoreError,
    StaleSnapshotError,
    WorktreeError,
)
from projectctl.core.time import utc_now
from projectctl.git import WorktreeInfo, WorktreeManager, current_branch, resolve_commit
from projectctl.integrations.beads.claim import BeadsTaskClaimer
from projectctl.project.loader import load_project_config
from projectctl.project.locking import project_lock
from projectctl.project.state import load_project_state, semantic_project_state_digest
from projectctl.quota.manual import ManualQuotaProvider
from projectctl.scheduler.digests import semantic_task_snapshot_digest
from projectctl.schemas.execution import ExecutionPlan
from projectctl.schemas.run import RunManifest, WorkerDescriptor
from projectctl.schemas.run_store import RunRecord
from projectctl.storage.runs import RunStore


@dataclass(frozen=True)
class PreparedRun:
    plan: ExecutionPlan
    record: RunRecord
    worktree: WorktreeInfo


def _actor() -> str:
    return f"projectctl:{socket.gethostname()}:{os.getpid()}"


def _repository_clean(project_root: Path) -> bool:
    result = subprocess.run(
        ["git", "-C", str(project_root), "status", "--porcelain"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise WorktreeError(
            (result.stderr or result.stdout or "git status failed").strip()
        )
    return not result.stdout.strip()


def _atomic_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(
        value.model_dump(mode="json") if hasattr(value, "model_dump") else value,
        indent=2,
        sort_keys=True,
        ensure_ascii=False,
    ) + "\n"
    fd, tmp_name = tempfile.mkstemp(prefix=".projectctl-", suffix=".json", dir=path.parent)
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


def build_next_execution_plan(
    project_root: Path,
    *,
    integration_target_ref: str | None = None,
) -> ExecutionPlan:
    if not _repository_clean(project_root):
        raise StaleSnapshotError(
            "Repository has uncommitted changes; commit or stash them before preparing a run."
        )

    bundle = collect_scheduling_bundle(project_root)
    decision = bundle.decision
    if decision.selected_task_id is None:
        raise ConfigurationError("Scheduler did not select an eligible task.")

    candidate = next(
        c for c in decision.candidates if c.task_id == decision.selected_task_id
    )
    if candidate.model is None:
        raise ConfigurationError(
            f"Selected task {decision.selected_task_id} has no model recommendation."
        )

    target_ref = integration_target_ref or current_branch(project_root)
    base_commit = resolve_commit(project_root, target_ref)
    profile_config = bundle.config.model_profiles[candidate.model.profile]
    worker = WorkerDescriptor(
        provider=profile_config.provider,
        model_profile=candidate.model.profile,
        reasoning=candidate.model.reasoning,
        actual_model=profile_config.model,
    )
    return ExecutionPlan(
        plan_id=f"ep-{uuid.uuid4().hex}",
        project_id=bundle.config.project.id,
        task_id=decision.selected_task_id,
        task_source_revision=bundle.tasks.source_revision,
        scheduler_decision_digest=digest(decision),
        task_snapshot_digest=decision.task_snapshot_digest,
        project_state_digest=decision.project_state_digest,
        quota_snapshot_digest=decision.quota_snapshot_digest,
        base_commit=base_commit,
        integration_target_ref=target_ref,
        worker=worker,
        created_at=utc_now(),
    )


def _validate_plan_inputs(project_root: Path, plan: ExecutionPlan) -> RunTerminalReason | None:
    if resolve_commit(project_root, plan.integration_target_ref) != plan.base_commit:
        return RunTerminalReason.STALE_BASE

    tasks = capture_task_snapshot(project_root, state="all")
    if semantic_task_snapshot_digest(tasks) != plan.task_snapshot_digest:
        return RunTerminalReason.CONTEXT_INVALID

    state = load_project_state(project_root, allow_missing=True)
    if semantic_project_state_digest(state) != plan.project_state_digest:
        return RunTerminalReason.CONTEXT_INVALID

    config = load_project_config(project_root)
    quota = ManualQuotaProvider().get_snapshot(config.quota.account)
    if digest(quota) != plan.quota_snapshot_digest:
        return RunTerminalReason.QUOTA_EXHAUSTED

    return None


def _claimer(project_root: Path):
    provider = load_project_config(project_root).task_store.provider
    if provider == "beads":
        return BeadsTaskClaimer(project_root)
    raise ConfigurationError(
        f"Task claiming is not implemented for provider {provider!r}."
    )


def prepare_next_run(
    project_root: Path,
    *,
    integration_target_ref: str | None = None,
) -> PreparedRun:
    root = project_root.resolve()
    actor = _actor()

    with project_lock(root, "run-prepare"):
        plan = build_next_execution_plan(
            root,
            integration_target_ref=integration_target_ref,
        )
        run_id = f"run-{uuid.uuid4().hex}"
        branch_name = f"projectctl/run/{run_id}"
        worktree_id = run_id
        manager = WorktreeManager(root)
        worktree_path = manager.path_for(worktree_id)
        run_dir = root / ".projectctl" / "runs" / run_id

        manifest = RunManifest(
            run_id=run_id,
            task_id=plan.task_id,
            execution_plan_digest=digest(plan),
            status=RunStatus.PLANNED,
            base_commit=plan.base_commit,
            branch_name=branch_name,
            worktree_id=worktree_id,
            worker=plan.worker,
        )
        store = RunStore(root)
        try:
            store.create(
                manifest,
                worktree_path=worktree_path,
                lease_owner=actor,
            )
        except Exception:
            shutil.rmtree(run_dir, ignore_errors=True)
            raise
        try:
            _atomic_json(run_dir / "execution-plan.json", plan)
        except Exception:
            store.transition(
                run_id,
                expected={RunStatus.PLANNED},
                status=RunStatus.FAILED,
                terminal_reason=RunTerminalReason.INFRASTRUCTURE_ERROR,
            )
            store.release_lease(run_id, owner=actor)
            shutil.rmtree(run_dir, ignore_errors=True)
            raise

        store.transition(
            run_id,
            expected={RunStatus.PLANNED},
            status=RunStatus.PREPARING,
        )

        stale_reason = _validate_plan_inputs(root, plan)
        if stale_reason is not None:
            store.transition(
                run_id,
                expected={RunStatus.PREPARING},
                status=RunStatus.FAILED,
                terminal_reason=stale_reason,
            )
            store.release_lease(run_id, owner=actor)
            raise StaleSnapshotError(
                f"Execution plan became stale during preflight: {stale_reason.value}"
            )

        claimer = _claimer(root)
        claim = claimer.claim(plan.task_id, actor=actor)
        if not claim.claimed:
            store.transition(
                run_id,
                expected={RunStatus.PREPARING},
                status=RunStatus.FAILED,
                terminal_reason=RunTerminalReason.CLAIM_LOST,
            )
            store.release_lease(run_id, owner=actor)
            raise ClaimConflictError(
                claim.reason or f"Task {plan.task_id} could not be claimed."
            )

        store.transition(
            run_id,
            expected={RunStatus.PREPARING},
            status=RunStatus.CLAIMED,
        )

        try:
            worktree = manager.create(
                worktree_id=worktree_id,
                branch_name=branch_name,
                base_commit=plan.base_commit,
            )
        except Exception as exc:
            release_ok = True
            try:
                claimer.release(plan.task_id, actor=actor)
            except Exception:
                release_ok = False
            reason = (
                RunTerminalReason.INFRASTRUCTURE_ERROR
                if release_ok
                else RunTerminalReason.RECOVERY_UNSAFE
            )
            status = RunStatus.FAILED if release_ok else RunStatus.NEEDS_DECISION
            store.transition(
                run_id,
                expected={RunStatus.CLAIMED},
                status=status,
                terminal_reason=reason,
            )
            store.release_lease(run_id, owner=actor)
            raise WorktreeError(f"Could not prepare isolated worktree: {exc}") from exc

        record = store.release_lease(run_id, owner=actor)
        return PreparedRun(plan=plan, record=record, worktree=worktree)


def abort_prepared_run(project_root: Path, run_id: str) -> RunRecord:
    root = project_root.resolve()
    actor = _actor()
    store = RunStore(root)
    record = store.acquire_lease(run_id, owner=actor)
    if record.status not in {RunStatus.PLANNED, RunStatus.PREPARING, RunStatus.CLAIMED}:
        store.release_lease(run_id, owner=actor)
        raise RunStoreError(
            f"Run {run_id} cannot be aborted from status {record.status.value} in M1.1."
        )

    manager = WorktreeManager(root)
    claimer = _claimer(root)

    manager.remove(
        worktree_id=record.worktree_id,
        branch_name=record.branch_name,
        force=True,
    )

    if record.status == RunStatus.CLAIMED:
        try:
            claimer.release(record.task_id, actor=actor)
        except Exception as exc:
            store.transition(
                run_id,
                expected={RunStatus.CLAIMED},
                status=RunStatus.NEEDS_DECISION,
                terminal_reason=RunTerminalReason.RECOVERY_UNSAFE,
            )
            store.release_lease(run_id, owner=actor)
            raise RunStoreError(
                f"Worktree was removed but task claim could not be released: {exc}"
            ) from exc

    try:
        result = store.transition(
            run_id,
            expected={record.status},
            status=RunStatus.CANCELLED,
            terminal_reason=RunTerminalReason.USER_CANCELLED,
        )
    except Exception as exc:
        try:
            store.transition(
                run_id,
                expected={record.status},
                status=RunStatus.NEEDS_DECISION,
                terminal_reason=RunTerminalReason.RECOVERY_UNSAFE,
            )
        except Exception:
            pass
        store.release_lease(run_id, owner=actor)
        raise RunStoreError(
            f"Run cleanup completed but cancellation state could not be recorded: {exc}"
        ) from exc

    store.release_lease(run_id, owner=actor)
    return result
