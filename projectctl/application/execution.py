from __future__ import annotations

import hashlib
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
    QuotaError,
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
from projectctl.quota import QuotaCheckpointMonitor, QuotaManager, read_current_quota
from projectctl.scheduler.digests import semantic_task_snapshot_digest
from projectctl.schemas.capabilities import (
    StrategyFallbackPolicy,
    WorkerCapabilities,
    WorkerStrategyDecision,
)
from projectctl.schemas.execution import (
    ExecutionPlan,
    ExecutionPolicy,
    WorkerCheckpoint,
    WorkerRequest,
    WorkerResult,
    parse_worker_checkpoint,
)
from projectctl.schemas.run import ContextManifest, RunManifest, WorkerDescriptor
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
    context: ContextBundle
    result: WorkerResult | None = None
    checkpoint: WorkerCheckpoint | None = None


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

    task = next((item for item in tasks.tasks if item.id == plan.task_id), None)
    if task is None:
        return RunTerminalReason.CONTEXT_INVALID

    config = load_project_config(project_root)
    quota = read_current_quota(config.quota.account)
    quota_manager = QuotaManager(config.quota)
    quota_state = quota_manager.state(quota, now=utc_now())
    if quota_state.stale or not quota_manager.eligible_for_resource(
        task.resource_class, quota_state
    ):
        return RunTerminalReason.QUOTA_EXHAUSTED

    return None


def _claimer(project_root: Path):
    provider = load_project_config(project_root).task_store.provider
    if provider == "beads":
        return BeadsTaskClaimer(project_root)
    raise ConfigurationError(
        f"Task claiming is not implemented for provider {provider!r}."
    )


def _assert_task_store_execution_capable(project_root: Path) -> None:
    provider = load_project_config(project_root).task_store.provider
    if provider == "beads":
        return
    if provider == "github":
        raise ConfigurationError(
            "GitHub Issues task authority is read-only in M3.0a. "
            "Scheduling/status reads are supported, but run preparation requires "
            "the M3.0b concurrency-safe claim protocol."
        )
    raise ConfigurationError(
        f"Task execution is not implemented for provider {provider!r}."
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
    _assert_task_store_execution_capable(root)

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


def _quota_monitor(project_root: Path, task) -> QuotaCheckpointMonitor:
    config = load_project_config(project_root)
    return QuotaCheckpointMonitor(
        account=config.quota.account,
        policy=config.quota,
        resource_class=task.resource_class,
    )


def _load_worker_checkpoint(path: Path) -> WorkerCheckpoint:
    if not path.exists():
        raise RunStoreError(f"Missing worker checkpoint: {path}")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        checkpoint = parse_worker_checkpoint(raw)
    except Exception as exc:
        raise RunStoreError(f"Invalid worker checkpoint {path.name}: {exc}") from exc
    if not isinstance(checkpoint, WorkerCheckpoint):
        raise RunStoreError(
            "Legacy WorkerCheckpoint v1 is audit-readable but not automatically resumable."
        )
    return checkpoint


def _checkpoint_artifact_ref(run_id: str) -> str:
    return (
        f".projectctl/runs/{run_id}/checkpoints/"
        f"checkpoint-{uuid.uuid4().hex}.json"
    )


def _worktree_state_digest(worktree: Path) -> str:
    diff = subprocess.run(
        ["git", "-C", str(worktree), "diff", "--binary", "HEAD"],
        capture_output=True,
        check=False,
    )
    if diff.returncode != 0:
        raise WorktreeError(
            (diff.stderr or diff.stdout or b"git diff failed").decode(
                "utf-8", errors="replace"
            ).strip()
        )

    untracked = subprocess.run(
        ["git", "-C", str(worktree), "ls-files", "--others", "--exclude-standard", "-z"],
        capture_output=True,
        check=False,
    )
    if untracked.returncode != 0:
        raise WorktreeError(
            (untracked.stderr or untracked.stdout or b"git ls-files failed").decode(
                "utf-8", errors="replace"
            ).strip()
        )

    entries: list[dict[str, str]] = []
    for raw in untracked.stdout.split(b"\0"):
        if not raw:
            continue
        relative = raw.decode("utf-8", errors="surrogateescape")
        path = worktree / relative
        try:
            if path.is_symlink():
                payload = os.readlink(path).encode("utf-8", errors="surrogateescape")
                kind = "symlink"
            elif path.is_file():
                payload = path.read_bytes()
                kind = "file"
            else:
                continue
        except OSError as exc:
            raise WorktreeError(
                f"Could not hash untracked workspace path {relative}: {exc}"
            ) from exc
        entries.append(
            {
                "path": relative,
                "kind": kind,
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        )

    return digest(
        {
            "head": resolve_commit(worktree, "HEAD"),
            "diff_sha256": hashlib.sha256(diff.stdout).hexdigest(),
            "untracked": sorted(entries, key=lambda item: item["path"]),
        }
    )


def _checkpoint_event_matches(
    store: RunStore,
    run_id: str,
    checkpoint_ref: str,
    checkpoint: WorkerCheckpoint,
) -> bool:
    expected = digest(checkpoint)
    for event in reversed(store.events(run_id)):
        if event.event_type != "worker.checkpointed":
            continue
        if event.payload.get("checkpoint_ref") != checkpoint_ref:
            continue
        return event.payload.get("checkpoint_digest") == expected
    return False


def _persist_checkpoint(
    root: Path,
    *,
    store: RunStore,
    run_id: str,
    worktree: Path,
    checkpoint: WorkerCheckpoint,
) -> tuple[RunRecord, WorkerCheckpoint]:
    if digest(checkpoint.quota_snapshot) != checkpoint.quota_snapshot_digest:
        raise WorkerError("Checkpoint quota snapshot digest does not match its payload.")

    durable = checkpoint.model_copy(
        update={"workspace_digest": _worktree_state_digest(worktree)}
    )
    checkpoint_ref = _checkpoint_artifact_ref(run_id)
    _atomic_json(root / checkpoint_ref, durable)
    record = store.transition(
        run_id,
        expected={RunStatus.RUNNING},
        status=RunStatus.RUNNING,
        worker_thread_id=durable.worker_thread_id,
        checkpoint_at=durable.checkpoint_at,
        checkpoint_ref=checkpoint_ref,
    )
    store.append_event(
        run_id,
        "worker.checkpointed",
        {
            "checkpoint_ref": checkpoint_ref,
            "checkpoint_digest": digest(durable),
            "workspace_digest": durable.workspace_digest,
            "reason": durable.reason.value,
            "quota_mode": durable.quota_mode.value,
            "quota_stale": durable.quota_stale,
            "quota_snapshot_digest": durable.quota_snapshot_digest,
            "worker_thread_id": durable.worker_thread_id,
            "worker_turn_id": durable.worker_turn_id,
        },
    )
    return record, durable


def _finalize_worker_outcome(
    root: Path,
    *,
    store: RunStore,
    run_id: str,
    run_dir: Path,
    actor: str,
    actual_worktree: Path,
    pre_head: str,
    context: ContextBundle,
    outcome: WorkerResult | WorkerCheckpoint,
) -> StartedRun:
    post_head = resolve_commit(actual_worktree, "HEAD")
    if post_head != pre_head:
        _mark_start_failure(
            store,
            run_id,
            expected=RunStatus.RUNNING,
            status=RunStatus.FAILED,
            reason=RunTerminalReason.UNEXPECTED_GIT_HISTORY,
        )
        raise WorkerError(
            "Worker changed Git HEAD/history. The worktree was preserved for inspection."
        )

    if isinstance(outcome, WorkerCheckpoint):
        record, durable_checkpoint = _persist_checkpoint(
            root,
            store=store,
            run_id=run_id,
            worktree=actual_worktree,
            checkpoint=outcome,
        )
        return StartedRun(
            record=record,
            context=context,
            checkpoint=durable_checkpoint,
        )

    result = outcome
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

    if result.status == WorkerResultStatus.IMPLEMENTED:
        final_record = store.transition(
            run_id,
            expected={RunStatus.RUNNING},
            status=RunStatus.VERIFYING,
            worker_thread_id=result.worker_thread_id,
            clear_checkpoint=True,
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
            clear_checkpoint=True,
        )
    elif result.status == WorkerResultStatus.CANCELLED:
        final_record = store.transition(
            run_id,
            expected={RunStatus.RUNNING},
            status=RunStatus.CANCELLED,
            terminal_reason=RunTerminalReason.WORKER_CANCELLED,
            worker_thread_id=result.worker_thread_id,
            clear_checkpoint=True,
        )
    else:
        final_record = store.transition(
            run_id,
            expected={RunStatus.RUNNING},
            status=RunStatus.FAILED,
            terminal_reason=RunTerminalReason.WORKER_ERROR,
            worker_thread_id=result.worker_thread_id,
            clear_checkpoint=True,
        )

    final_record = reconcile_terminal_task(
        root,
        store=store,
        run_id=run_id,
        actor=actor,
    )
    return StartedRun(
        record=final_record,
        context=context,
        result=result,
    )


def _run_worker_operation(
    root: Path,
    *,
    store: RunStore,
    run_id: str,
    run_dir: Path,
    actor: str,
    actual_worktree: Path,
    context: ContextBundle,
    operation,
) -> StartedRun:
    pre_head = resolve_commit(actual_worktree, "HEAD")
    try:
        with LeaseHeartbeat(store, run_id, owner=actor):
            outcome = operation()
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
        reconcile_terminal_task(
            root,
            store=store,
            run_id=run_id,
            actor=actor,
        )
        raise

    return _finalize_worker_outcome(
        root,
        store=store,
        run_id=run_id,
        run_dir=run_dir,
        actor=actor,
        actual_worktree=actual_worktree,
        pre_head=pre_head,
        context=context,
        outcome=outcome,
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

        monitor = _quota_monitor(root, current_task)
        return _run_worker_operation(
            root,
            store=store,
            run_id=run_id,
            run_dir=run_dir,
            actor=actor,
            actual_worktree=actual_worktree,
            context=context,
            operation=lambda: adapter.start(
                context.request,
                workspace=actual_worktree,
                checkpoint_monitor=monitor,
            ),
        )
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


def resume_checkpointed_run(project_root: Path, run_id: str) -> StartedRun:
    root = project_root.resolve()
    actor = _actor()
    store = RunStore(root)
    record = store.acquire_lease(run_id, owner=actor)
    run_dir = root / ".projectctl" / "runs" / run_id

    try:
        if record.status != RunStatus.RUNNING or not record.checkpoint_ref:
            raise RunStoreError(
                f"Run {run_id} is not a resumable checkpointed RUNNING run."
            )

        plan = _load_json_model(run_dir / "execution-plan.json", ExecutionPlan)
        if digest(plan) != record.execution_plan_digest:
            _mark_start_failure(
                store,
                run_id,
                expected=RunStatus.RUNNING,
                status=RunStatus.FAILED,
                reason=RunTerminalReason.CONTEXT_INVALID,
            )
            raise RunStoreError("ExecutionPlan digest no longer matches the run record.")

        checkpoint_path = (root / record.checkpoint_ref).resolve()
        if not checkpoint_path.is_relative_to(root):
            raise RunStoreError("Checkpoint path escapes the project root.")
        checkpoint = _load_worker_checkpoint(checkpoint_path)
        if (
            not _checkpoint_event_matches(
                store, run_id, record.checkpoint_ref, checkpoint
            )
            or checkpoint.run_id != record.run_id
            or checkpoint.task_id != record.task_id
            or checkpoint.worktree_id != record.worktree_id
            or checkpoint.base_commit != record.base_commit
            or checkpoint.branch_name != record.branch_name
            or digest(checkpoint.quota_snapshot) != checkpoint.quota_snapshot_digest
        ):
            _mark_start_failure(
                store,
                run_id,
                expected=RunStatus.RUNNING,
                status=RunStatus.NEEDS_DECISION,
                reason=RunTerminalReason.RECOVERY_UNSAFE,
            )
            raise RunStoreError("Worker checkpoint identity does not match durable run state.")

        manager = WorktreeManager(root)
        expected_worktree = manager.path_for(record.worktree_id)
        actual_worktree = Path(record.worktree_path).resolve()
        if actual_worktree != expected_worktree or not actual_worktree.exists():
            _mark_start_failure(
                store,
                run_id,
                expected=RunStatus.RUNNING,
                status=RunStatus.NEEDS_DECISION,
                reason=RunTerminalReason.RECOVERY_UNSAFE,
            )
            raise WorktreeError("Checkpoint worktree is missing or outside the expected run location.")
        if resolve_commit(actual_worktree, "HEAD") != plan.base_commit:
            _mark_start_failure(
                store,
                run_id,
                expected=RunStatus.RUNNING,
                status=RunStatus.FAILED,
                reason=RunTerminalReason.UNEXPECTED_GIT_HISTORY,
            )
            raise WorkerError("Checkpointed worker changed Git history; resume is unsafe.")
        if (
            not checkpoint.workspace_digest
            or _worktree_state_digest(actual_worktree) != checkpoint.workspace_digest
        ):
            _mark_start_failure(
                store,
                run_id,
                expected=RunStatus.RUNNING,
                status=RunStatus.NEEDS_DECISION,
                reason=RunTerminalReason.RECOVERY_UNSAFE,
            )
            raise WorktreeError(
                "Checkpointed workspace changed after the durable checkpoint; resume is unsafe."
            )

        context_manifest = _load_json_model(
            run_dir / "context-manifest.json", ContextManifest
        )
        request = _load_json_model(run_dir / "worker-request.json", WorkerRequest)
        if (
            digest(context_manifest) != checkpoint.context_manifest_digest
            or digest(request) != checkpoint.worker_request_digest
            or request.context_manifest_digest != checkpoint.context_manifest_digest
            or request.run_id != run_id
            or request.task_id != record.task_id
        ):
            _mark_start_failure(
                store,
                run_id,
                expected=RunStatus.RUNNING,
                status=RunStatus.NEEDS_DECISION,
                reason=RunTerminalReason.CONTEXT_INVALID,
            )
            raise RunStoreError("Checkpoint context no longer matches the original WorkerRequest.")

        current_task = task_store_for_project(root).get(plan.task_id)
        config = load_project_config(root)
        quota = read_current_quota(config.quota.account)
        manager_quota = QuotaManager(config.quota)
        quota_state = manager_quota.state(quota, now=utc_now())
        if quota_state.stale or not manager_quota.eligible_for_resource(
            current_task.resource_class, quota_state
        ):
            store.append_event(
                run_id,
                "worker.resume_deferred",
                {
                    "checkpoint_ref": record.checkpoint_ref,
                    "quota_mode": quota_state.mode.value,
                    "quota_stale": quota_state.stale,
                    "quota_snapshot_digest": digest(quota),
                },
            )
            raise QuotaError(
                "Checkpoint resume deferred because current quota is stale or "
                "insufficient for this task resource class."
            )

        adapter = _adapter_for_provider(plan.worker.provider)
        live_capabilities = adapter.probe()
        if effective_capability_digest(live_capabilities) != plan.capability_snapshot_digest:
            _atomic_json(run_dir / "worker-capabilities-live.json", live_capabilities)
            _mark_start_failure(
                store,
                run_id,
                expected=RunStatus.RUNNING,
                status=RunStatus.NEEDS_DECISION,
                reason=RunTerminalReason.CAPABILITY_CHANGED,
            )
            raise CapabilityMismatchError(
                "Worker capability surface changed before checkpoint resume."
            )

        live_strategy = negotiate_strategy(
            current_task,
            live_capabilities,
            requested=plan.strategy,
        )
        if not live_strategy.compatible or live_strategy.resolved != plan.strategy:
            _mark_start_failure(
                store,
                run_id,
                expected=RunStatus.RUNNING,
                status=RunStatus.NEEDS_DECISION,
                reason=RunTerminalReason.CAPABILITY_CHANGED,
            )
            raise CapabilityMismatchError(
                "Checkpointed worker strategy is no longer compatible."
            )

        context = ContextBundle(
            task=current_task,
            manifest=context_manifest,
            request=request,
        )
        store.append_event(
            run_id,
            "worker.resumed",
            {
                "checkpoint_ref": record.checkpoint_ref,
                "worker_thread_id": checkpoint.worker_thread_id,
            },
        )

        monitor = _quota_monitor(root, current_task)
        return _run_worker_operation(
            root,
            store=store,
            run_id=run_id,
            run_dir=run_dir,
            actor=actor,
            actual_worktree=actual_worktree,
            context=context,
            operation=lambda: adapter.resume(
                checkpoint,
                request,
                workspace=actual_worktree,
                checkpoint_monitor=monitor,
            ),
        )
    finally:
        if sys.exc_info()[0] is not None:
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
    abortable = record.status in {
        RunStatus.PLANNED,
        RunStatus.PREPARING,
        RunStatus.CLAIMED,
    } or (
        record.status == RunStatus.RUNNING and record.checkpoint_ref is not None
    )
    if not abortable:
        store.release_lease(run_id, owner=actor)
        raise RunStoreError(
            f"Run {run_id} cannot be aborted from status {record.status.value}; "
            "RUNNING is abortable only when a durable checkpoint exists."
        )

    manager = WorktreeManager(root)
    claimer = _claimer(root)

    manager.remove(
        worktree_id=record.worktree_id,
        branch_name=record.branch_name,
        force=True,
    )

    if record.status in {RunStatus.CLAIMED, RunStatus.RUNNING}:
        try:
            claimer.release(record.task_id, actor=actor)
        except Exception as exc:
            store.transition(
                run_id,
                expected={record.status},
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
            clear_checkpoint=True,
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
