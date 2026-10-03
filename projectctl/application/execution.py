from __future__ import annotations

import json
import os
import shutil
import socket
import sys
import subprocess
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path

from projectctl.application.scheduling import collect_scheduling_bundle
from projectctl.application.tasks import capture_task_snapshot, task_store_for_project
from projectctl.application.task_lifecycle import reconcile_terminal_task
from projectctl.context import ContextBundle, assemble_context
from projectctl.core.digest import digest
from projectctl.core.enums import (
    RunStatus,
    RunTerminalReason,
    WorkerResultStatus,
    WorkerStrategyKind,
)
from projectctl.core.errors import (
    CapabilityMismatchError,
    ClaimConflictError,
    ConfigurationError,
    RunStoreError,
    RunLeaseError,
    StaleSnapshotError,
    WorkerError,
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
from projectctl.schemas.capabilities import (
    StrategyFallbackPolicy,
    WorkerCapabilities,
    WorkerStrategyDecision,
)
from projectctl.schemas.execution import ExecutionPlan, ExecutionPolicy, WorkerRequest, WorkerResult
from projectctl.schemas.run import RunManifest, WorkerDescriptor
from projectctl.schemas.run_store import RunRecord
from projectctl.storage.runs import RunStore
from projectctl.runtime import LeaseHeartbeat
from projectctl.workers.capability_digest import effective_capability_digest
from projectctl.workers.codex import CodexWorkerAdapter
from projectctl.workers.strategy import negotiate_strategy


@dataclass(frozen=True)
class ExecutionPlanningBundle:
    plan: ExecutionPlan
    capabilities: WorkerCapabilities
    strategy: WorkerStrategyDecision


@dataclass(frozen=True)
class PreparedRun:
    plan: ExecutionPlan
    record: RunRecord
    worktree: WorktreeInfo


@dataclass(frozen=True)
class StartedRun:
    record: RunRecord
    result: WorkerResult
    context: ContextBundle


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


def _load_json_model(path: Path, model):
    if not path.exists():
        raise RunStoreError(f"Missing run artifact: {path}")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return model.model_validate(raw)
    except Exception as exc:
        raise RunStoreError(f"Invalid run artifact {path.name}: {exc}") from exc


def _adapter_for_provider(provider: str) -> CodexWorkerAdapter:
    if provider == "codex":
        return CodexWorkerAdapter()
    raise ConfigurationError(f"Worker provider {provider!r} is not implemented.")


def build_next_execution_bundle(
    project_root: Path,
    *,
    integration_target_ref: str | None = None,
    requested_strategy: WorkerStrategyKind | None = None,
    fallback: StrategyFallbackPolicy | None = None,
) -> ExecutionPlanningBundle:
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
    task = next(task for task in bundle.tasks.tasks if task.id == decision.selected_task_id)

    profile_config = bundle.config.model_profiles[candidate.model.profile]
    worker = WorkerDescriptor(
        provider=profile_config.provider,
        model_profile=candidate.model.profile,
        reasoning=candidate.model.reasoning,
        actual_model=profile_config.model,
    )
    adapter = _adapter_for_provider(worker.provider)
    capabilities = adapter.version_capabilities()
    strategy = negotiate_strategy(
        task,
        capabilities,
        requested=requested_strategy,
        fallback=fallback or StrategyFallbackPolicy(),
    )
    if not strategy.compatible or strategy.resolved is None or strategy.execution is None:
        unsupported = ", ".join(strategy.unsupported) or "unknown capability mismatch"
        raise CapabilityMismatchError(
            f"Worker strategy {strategy.requested.value} cannot be executed: {unsupported}. "
            "Use an explicit strategy/fallback only after reviewing the capability report."
        )

    target_ref = integration_target_ref or current_branch(project_root)
    base_commit = resolve_commit(project_root, target_ref)
    phase = strategy.execution
    execution_policy = ExecutionPolicy(
        sandbox=phase.sandbox,
        network=phase.network,
        approval=phase.approval,
    )

    plan = ExecutionPlan(
        plan_id=f"ep-{uuid.uuid4().hex}",
        project_id=bundle.config.project.id,
        task_id=decision.selected_task_id,
        task_source_revision=bundle.tasks.source_revision,
        scheduler_decision_digest=digest(decision),
        task_snapshot_digest=decision.task_snapshot_digest,
        project_state_digest=decision.project_state_digest,
        quota_snapshot_digest=decision.quota_snapshot_digest,
        capability_snapshot_digest=effective_capability_digest(capabilities),
        strategy_decision_digest=digest(strategy),
        strategy=strategy.resolved,
        base_commit=base_commit,
        integration_target_ref=target_ref,
        worker=worker,
        execution_policy=execution_policy,
        created_at=utc_now(),
    )
    return ExecutionPlanningBundle(
        plan=plan,
        capabilities=capabilities,
        strategy=strategy,
    )


def build_next_execution_plan(
    project_root: Path,
    *,
    integration_target_ref: str | None = None,
    requested_strategy: WorkerStrategyKind | None = None,
    fallback: StrategyFallbackPolicy | None = None,
) -> ExecutionPlan:
    return build_next_execution_bundle(
        project_root,
        integration_target_ref=integration_target_ref,
        requested_strategy=requested_strategy,
        fallback=fallback,
    ).plan


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
    requested_strategy: WorkerStrategyKind | None = None,
    fallback: StrategyFallbackPolicy | None = None,
) -> PreparedRun:
    root = project_root.resolve()
    actor = _actor()

    with project_lock(root, "run-prepare"):
        planning = build_next_execution_bundle(
            root,
            integration_target_ref=integration_target_ref,
            requested_strategy=requested_strategy,
            fallback=fallback,
        )
        plan = planning.plan
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
            _atomic_json(run_dir / "execution-plan.json", plan)
            _atomic_json(run_dir / "worker-capabilities.json", planning.capabilities)
            _atomic_json(run_dir / "worker-strategy.json", planning.strategy)
            store.create(
                manifest,
                worktree_path=worktree_path,
                lease_owner=actor,
            )
        except Exception:
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


def _mark_start_failure(
    store: RunStore,
    run_id: str,
    *,
    expected: RunStatus,
    status: RunStatus,
    reason: RunTerminalReason,
) -> RunRecord:
    return store.transition(
        run_id,
        expected={expected},
        status=status,
        terminal_reason=reason,
    )


def start_prepared_run(project_root: Path, run_id: str) -> StartedRun:
    root = project_root.resolve()
    actor = _actor()
    store = RunStore(root)
    record = store.acquire_lease(run_id, owner=actor)
    run_dir = root / ".projectctl" / "runs" / run_id

    try:
        if record.status != RunStatus.CLAIMED:
            raise RunStoreError(
                f"Run {run_id} cannot start from status {record.status.value}; expected claimed."
            )

        plan = _load_json_model(run_dir / "execution-plan.json", ExecutionPlan)
        stored_capabilities = _load_json_model(
            run_dir / "worker-capabilities.json", WorkerCapabilities
        )
        stored_strategy = _load_json_model(
            run_dir / "worker-strategy.json", WorkerStrategyDecision
        )

        if digest(plan) != record.execution_plan_digest:
            _mark_start_failure(
                store,
                run_id,
                expected=RunStatus.CLAIMED,
                status=RunStatus.FAILED,
                reason=RunTerminalReason.CONTEXT_INVALID,
            )
            raise RunStoreError("ExecutionPlan digest no longer matches the run record.")
        if effective_capability_digest(stored_capabilities) != plan.capability_snapshot_digest:
            _mark_start_failure(
                store,
                run_id,
                expected=RunStatus.CLAIMED,
                status=RunStatus.NEEDS_DECISION,
                reason=RunTerminalReason.CAPABILITY_CHANGED,
            )
            raise CapabilityMismatchError("Stored capability snapshot does not match ExecutionPlan.")
        if digest(stored_strategy) != plan.strategy_decision_digest:
            _mark_start_failure(
                store,
                run_id,
                expected=RunStatus.CLAIMED,
                status=RunStatus.FAILED,
                reason=RunTerminalReason.CONTEXT_INVALID,
            )
            raise RunStoreError("Stored worker strategy does not match ExecutionPlan.")
        if stored_strategy.resolved != plan.strategy:
            _mark_start_failure(
                store,
                run_id,
                expected=RunStatus.CLAIMED,
                status=RunStatus.FAILED,
                reason=RunTerminalReason.CONTEXT_INVALID,
            )
            raise RunStoreError("Stored worker strategy resolution differs from ExecutionPlan.")

        manager = WorktreeManager(root)
        expected_worktree = manager.path_for(record.worktree_id)
        actual_worktree = Path(record.worktree_path).resolve()
        if actual_worktree != expected_worktree or not actual_worktree.exists():
            _mark_start_failure(
                store,
                run_id,
                expected=RunStatus.CLAIMED,
                status=RunStatus.NEEDS_DECISION,
                reason=RunTerminalReason.RECOVERY_UNSAFE,
            )
            raise WorktreeError("Recorded worktree is missing or outside the expected run location.")
        if resolve_commit(actual_worktree, "HEAD") != plan.base_commit:
            _mark_start_failure(
                store,
                run_id,
                expected=RunStatus.CLAIMED,
                status=RunStatus.FAILED,
                reason=RunTerminalReason.STALE_BASE,
            )
            raise StaleSnapshotError("Prepared worktree HEAD no longer matches ExecutionPlan base.")

        dirty = subprocess.run(
            ["git", "-C", str(actual_worktree), "status", "--porcelain"],
            capture_output=True,
            text=True,
            check=False,
        )
        if dirty.returncode != 0 or dirty.stdout.strip():
            _mark_start_failure(
                store,
                run_id,
                expected=RunStatus.CLAIMED,
                status=RunStatus.FAILED,
                reason=RunTerminalReason.CONTEXT_INVALID,
            )
            raise WorktreeError("Prepared worktree must be clean before worker start.")

        adapter = _adapter_for_provider(plan.worker.provider)
        try:
            live_capabilities = adapter.probe()
        except WorkerError:
            _mark_start_failure(
                store,
                run_id,
                expected=RunStatus.CLAIMED,
                status=RunStatus.FAILED,
                reason=RunTerminalReason.INFRASTRUCTURE_ERROR,
            )
            raise

        live_digest = effective_capability_digest(live_capabilities)
        if live_digest != plan.capability_snapshot_digest:
            _atomic_json(run_dir / "worker-capabilities-live.json", live_capabilities)
            _mark_start_failure(
                store,
                run_id,
                expected=RunStatus.CLAIMED,
                status=RunStatus.NEEDS_DECISION,
                reason=RunTerminalReason.CAPABILITY_CHANGED,
            )
            raise CapabilityMismatchError(
                "Worker capability surface changed between prepare and start."
            )

        current_task = task_store_for_project(root).get(plan.task_id)
        live_strategy = negotiate_strategy(
            current_task,
            live_capabilities,
            requested=plan.strategy,
        )
        if not live_strategy.compatible or live_strategy.resolved != plan.strategy:
            _mark_start_failure(
                store,
                run_id,
                expected=RunStatus.CLAIMED,
                status=RunStatus.NEEDS_DECISION,
                reason=RunTerminalReason.CAPABILITY_CHANGED,
            )
            raise CapabilityMismatchError(
                "Prepared worker strategy is no longer compatible with the live capability surface."
            )

        context_rel = f".projectctl/runs/{run_id}/context-manifest.json"
        try:
            context = assemble_context(
                root,
                worktree=actual_worktree,
                run_id=run_id,
                plan=plan,
                strategy=stored_strategy,
                context_manifest_path=context_rel,
            )
            _atomic_json(run_dir / "context-manifest.json", context.manifest)
            _atomic_json(run_dir / "worker-request.json", context.request)
            _atomic_json(run_dir / "worker-capabilities-live.json", live_capabilities)
        except Exception:
            _mark_start_failure(
                store,
                run_id,
                expected=RunStatus.CLAIMED,
                status=RunStatus.FAILED,
                reason=RunTerminalReason.CONTEXT_INVALID,
            )
            raise

        pre_head = resolve_commit(actual_worktree, "HEAD")
        store.transition(
            run_id,
            expected={RunStatus.CLAIMED},
            status=RunStatus.RUNNING,
            context_manifest=context_rel,
        )
        store.append_event(
            run_id,
            "worker.started",
            {
                "strategy": plan.strategy.value,
                "context_manifest_digest": digest(context.manifest),
            },
        )

        try:
            with LeaseHeartbeat(store, run_id, owner=actor):
                result = adapter.start(context.request, workspace=actual_worktree)
        except Exception as exc:
            if isinstance(exc, RunLeaseError):
                raise
            _mark_start_failure(
                store,
                run_id,
                expected=RunStatus.RUNNING,
                status=RunStatus.FAILED,
                reason=RunTerminalReason.WORKER_ERROR,
            )
            store.append_event(
                run_id,
                "worker.error",
                {"type": type(exc).__name__, "message": str(exc)},
            )
            raise

        _atomic_json(run_dir / "worker-result.json", result)
        store.append_event(
            run_id,
            "worker.result",
            {
                "status": result.status.value,
                "worker_thread_id": result.worker_thread_id,
                "worker_result_digest": digest(result),
            },
        )

        post_head = resolve_commit(actual_worktree, "HEAD")
        if post_head != pre_head:
            final_record = _mark_start_failure(
                store,
                run_id,
                expected=RunStatus.RUNNING,
                status=RunStatus.FAILED,
                reason=RunTerminalReason.UNEXPECTED_GIT_HISTORY,
            )
            raise WorkerError(
                "Worker changed Git HEAD/history. The worktree was preserved for inspection."
            )

        if result.status == WorkerResultStatus.IMPLEMENTED:
            final_record = store.transition(
                run_id,
                expected={RunStatus.RUNNING},
                status=RunStatus.VERIFYING,
                worker_thread_id=result.worker_thread_id,
            )
        elif result.status == WorkerResultStatus.BLOCKED:
            reason = (
                RunTerminalReason.POLICY_BLOCKED
                if result.requested_permissions
                else RunTerminalReason.WORKER_BLOCKED
            )
            status = (
                RunStatus.BLOCKED_POLICY
                if result.requested_permissions
                else RunStatus.NEEDS_DECISION
            )
            final_record = store.transition(
                run_id,
                expected={RunStatus.RUNNING},
                status=status,
                terminal_reason=reason,
                worker_thread_id=result.worker_thread_id,
            )
        elif result.status == WorkerResultStatus.CANCELLED:
            final_record = store.transition(
                run_id,
                expected={RunStatus.RUNNING},
                status=RunStatus.CANCELLED,
                terminal_reason=RunTerminalReason.WORKER_CANCELLED,
                worker_thread_id=result.worker_thread_id,
            )
        else:
            final_record = store.transition(
                run_id,
                expected={RunStatus.RUNNING},
                status=RunStatus.FAILED,
                terminal_reason=RunTerminalReason.WORKER_ERROR,
                worker_thread_id=result.worker_thread_id,
            )

        final_record = reconcile_terminal_task(
            root,
            store=store,
            run_id=run_id,
            actor=actor,
        )
        return StartedRun(record=final_record, result=result, context=context)
    finally:
        if sys.exc_info()[0] is not None:
            try:
                current = store.get(run_id)
                if current.status == RunStatus.CLAIMED:
                    store.transition(
                        run_id,
                        expected={RunStatus.CLAIMED},
                        status=RunStatus.FAILED,
                        terminal_reason=RunTerminalReason.INFRASTRUCTURE_ERROR,
                    )
            except Exception:
                pass
            try:
                reconcile_terminal_task(
                    root,
                    store=store,
                    run_id=run_id,
                    actor=actor,
                )
            except Exception:
                pass
        try:
            store.release_lease(run_id, owner=actor)
        except Exception:
            pass


def abort_prepared_run(project_root: Path, run_id: str) -> RunRecord:
    root = project_root.resolve()
    actor = _actor()
    store = RunStore(root)
    record = store.acquire_lease(run_id, owner=actor)
    if record.status not in {RunStatus.PLANNED, RunStatus.PREPARING, RunStatus.CLAIMED}:
        store.release_lease(run_id, owner=actor)
        raise RunStoreError(
            f"Run {run_id} cannot be aborted from status {record.status.value} in M1.2b."
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
