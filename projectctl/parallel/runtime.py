from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import uuid
from datetime import datetime
from pathlib import Path

from projectctl.application.execution import (
    PreparedRun,
    _actor,
    prepare_next_run,
    resume_checkpointed_run,
    start_prepared_run,
)
from projectctl.application.execution_inputs import (
    derive_reapplied_execution_input,
    execution_input_semantic_digest,
    load_claim_transition,
    load_execution_input,
    persist_execution_input,
    validate_admitted_execution_input,
)
from projectctl.application.integration import (
    _integrate_run_locked,
    _load_json_model,
    _repository_clean,
    _validate_verified_candidate,
)
from projectctl.application.recovery import recover_run
from projectctl.application.scheduling import collect_scheduling_bundle
from projectctl.application.task_lifecycle import reconcile_terminal_task
from projectctl.application.tasks import capture_task_snapshot
from projectctl.application.verification import verify_run
from projectctl.core.digest import digest
from projectctl.core.enums import RunStatus, RunTerminalReason
from projectctl.core.errors import (
    ConfigurationError,
    IntegrationError,
    ProjectCtlError,
    RecoveryError,
    StaleSnapshotError,
)
from projectctl.core.time import utc_now
from projectctl.git import WorktreeManager, current_branch, resolve_commit
from projectctl.parallel.catalog import task_parallel_scope
from projectctl.parallel.service import (
    _atomic_json,
    _input_scope_digest,
    _path_scopes_overlap,
    assess_parallel_safety,
    build_parallel_plan,
)
from projectctl.project.loader import load_project_config
from projectctl.project.locking import project_lock
from projectctl.project.state import load_project_state, semantic_project_state_digest
from projectctl.scheduler.digests import semantic_task_scope_digest
from projectctl.schemas.capabilities import StrategyFallbackPolicy
from projectctl.schemas.evidence import EvidenceManifest
from projectctl.schemas.execution import ExecutionPlan, ExecutionPlanLineage
from projectctl.schemas.parallel import (
    ParallelBatchResult,
    ParallelInputEvidence,
    ParallelIntegrationQueue,
    ParallelPlan,
    ParallelQueueEntry,
    ParallelReapplicationManifest,
    ParallelReapplicationRequest,
    ParallelRunBinding,
    parse_parallel_reapplication_request,
    parse_parallel_run_binding,
)
from projectctl.storage.runs import RunStore


_ACTIVE = {
    RunStatus.PLANNED,
    RunStatus.PREPARING,
    RunStatus.CLAIMED,
    RunStatus.RUNNING,
    RunStatus.VERIFYING,
    RunStatus.READY_TO_INTEGRATE,
    RunStatus.INTEGRATING,
    RunStatus.AWAITING_REVIEW,
}

_QUEUE_ACTIVE = {
    RunStatus.PLANNED,
    RunStatus.PREPARING,
    RunStatus.CLAIMED,
    RunStatus.RUNNING,
    RunStatus.VERIFYING,
    RunStatus.READY_TO_INTEGRATE,
    RunStatus.INTEGRATING,
    RunStatus.AWAITING_REVIEW,
}


def _binding_path(root: Path, run_id: str) -> Path:
    return root / ".projectctl" / "runs" / run_id / "parallel-binding.json"


def load_parallel_run_binding(
    project_root: Path,
    run_id: str,
    *,
    allow_missing: bool = False,
) -> ParallelRunBinding | None:
    path = _binding_path(project_root.resolve(), run_id)
    if not path.exists():
        if allow_missing:
            return None
        raise ConfigurationError(
            f"Run {run_id} has no M4.1b parallel binding; it cannot participate "
            "in same-project concurrency."
        )
    try:
        return parse_parallel_run_binding(
            json.loads(path.read_text(encoding="utf-8"))
        )
    except Exception as exc:
        raise ConfigurationError(
            f"Invalid parallel binding for run {run_id}: {exc}"
        ) from exc


def _active_records(root: Path) -> list:
    return [
        item
        for item in RunStore(root).list(limit=1000)
        if item.status in _ACTIVE
    ]


def _active_bindings(root: Path) -> list[tuple[object, ParallelRunBinding]]:
    result: list[tuple[object, ParallelRunBinding]] = []
    for record in sorted(
        _active_records(root),
        key=lambda item: (item.created_at, item.run_id),
    ):
        binding = load_parallel_run_binding(root, record.run_id, allow_missing=True)
        if binding is None:
            raise ConfigurationError(
                f"Active run {record.run_id} predates or bypasses the parallel runtime. "
                "ProjectCTL will not add another active run until it is completed/recovered."
            )
        result.append((record, binding))
    return result


def _postclaim_parallel_plan(
    root: Path,
    preclaim: ParallelPlan,
    *,
    run_id: str,
) -> ParallelPlan:
    run_dir = root / ".projectctl" / "runs" / run_id
    execution_input = load_execution_input(
        run_dir / "execution-input-manifest.json"
    )
    transition = load_claim_transition(run_dir / "claim-transition.json")
    validate_admitted_execution_input(
        root,
        execution_input,
        transition,
        require_target_at_base=True,
    )
    input_digest = execution_input_semantic_digest(execution_input)
    if (
        getattr(preclaim, "execution_input_digest", None) is not None
        and preclaim.execution_input_digest != input_digest
    ):
        raise StaleSnapshotError(
            "Prepared run execution input differs from pre-claim parallel proof."
        )
    return preclaim.model_copy(
        update={
            "plan_id": f"parallel-admitted-{uuid.uuid4().hex}",
            "execution_input_digest": input_digest,
            "scoped_task_digest": transition.postclaim_task_scope_digest,
            "scoped_task_ids": transition.postclaim_task_scope_ids,
            "created_at": utc_now(),
        }
    )


def prepare_parallel_run(
    project_root: Path,
    *,
    max_parallel_runs: int,
    requested_strategy=None,
    fallback: StrategyFallbackPolicy | None = None,
) -> PreparedRun:
    if max_parallel_runs < 2 or max_parallel_runs > 8:
        raise ValueError("max_parallel_runs must be between 2 and 8.")

    root = project_root.resolve()
    with project_lock(root, "parallel-admission"):
        active = _active_bindings(root)
        if len(active) >= max_parallel_runs:
            raise ConfigurationError(
                f"Parallel run capacity reached: {len(active)}/{max_parallel_runs}."
            )

        scheduling = collect_scheduling_bundle(root)
        task_id = scheduling.decision.selected_task_id
        if task_id is None:
            raise ConfigurationError(
                "Project-local scheduler selected no task for another parallel slot."
            )

        preclaim = build_parallel_plan(
            root,
            task_id,
            integration_target_ref=current_branch(root),
            persist=True,
        )

        decisions = []
        for _, binding in active:
            decision = assess_parallel_safety(
                preclaim,
                binding.admitted_plan,
                persist_root=root,
            )
            decisions.append(decision)
            if not decision.independent:
                reasons = ", ".join(
                    sorted({item.reason for item in decision.conflicts})
                )
                raise ConfigurationError(
                    f"Task {task_id!r} is not independent from active run "
                    f"{binding.run_id}: {reasons}."
                )

        prepared = prepare_next_run(
            root,
            integration_target_ref=preclaim.integration_target_ref,
            requested_strategy=requested_strategy,
            fallback=fallback,
            expected_task_id=task_id,
            expected_task_snapshot_digest=scheduling.decision.task_snapshot_digest,
            expected_project_state_digest=scheduling.decision.project_state_digest,
        )

        if prepared.plan.base_commit != preclaim.base_commit:
            raise StaleSnapshotError(
                "Prepared execution base differs from the admitted parallel proof."
            )

        admitted = _postclaim_parallel_plan(
            root,
            preclaim,
            run_id=prepared.record.run_id,
        )
        run_dir = root / ".projectctl" / "runs" / prepared.record.run_id
        execution_input = load_execution_input(
            run_dir / "execution-input-manifest.json"
        )
        claim_transition = load_claim_transition(
            run_dir / "claim-transition.json"
        )
        binding = ParallelRunBinding(
            run_id=prepared.record.run_id,
            task_id=prepared.record.task_id,
            preclaim_plan_digest=digest(preclaim),
            admitted_plan=admitted,
            execution_input_digest=execution_input_semantic_digest(execution_input),
            claim_transition_digest=digest(claim_transition),
            peer_plan_digests=[
                digest(item.admitted_plan) for _, item in active
            ],
            peer_decision_digests=[digest(item) for item in decisions],
            bound_at=utc_now(),
        )
        _atomic_json(
            _binding_path(root, prepared.record.run_id),
            binding,
        )
        store = RunStore(root)
        store.append_event(
            prepared.record.run_id,
            "parallel.admitted",
            {
                "binding_digest": digest(binding),
                "preclaim_plan_digest": digest(preclaim),
                "peer_plan_digests": binding.peer_plan_digests,
                "peer_decision_digests": binding.peer_decision_digests,
                "max_parallel_runs": max_parallel_runs,
            },
        )
        return prepared


def _queue_filename(target_ref: str) -> str:
    token = hashlib.sha256(target_ref.encode("utf-8")).hexdigest()[:16]
    return f"integration-queue-{token}.json"


def build_parallel_integration_queue(
    project_root: Path,
    *,
    target_ref: str | None = None,
    persist: bool = True,
) -> ParallelIntegrationQueue:
    root = project_root.resolve()
    config = load_project_config(root)
    target = target_ref or current_branch(root)
    records = []
    for record in RunStore(root).list(limit=1000):
        if record.status not in _QUEUE_ACTIVE:
            continue
        binding = load_parallel_run_binding(root, record.run_id, allow_missing=True)
        if binding is None:
            continue
        if binding.admitted_plan.integration_target_ref != target:
            continue
        records.append((record, binding))

    records.sort(key=lambda item: (item[0].created_at, item[0].run_id))
    queue = ParallelIntegrationQueue(
        generated_at=utc_now(),
        project_id=config.project.id,
        target_ref=target,
        entries=[
            ParallelQueueEntry(
                position=index + 1,
                run_id=record.run_id,
                task_id=record.task_id,
                status=record.status,
                created_at=record.created_at,
                base_commit=binding.admitted_plan.base_commit,
                target_ref=binding.admitted_plan.integration_target_ref,
            )
            for index, (record, binding) in enumerate(records)
        ],
    )
    if persist:
        _atomic_json(
            root / ".projectctl" / "parallel" / _queue_filename(target),
            queue,
        )
    return queue


def _scope_contains(scope, path: str) -> bool:
    if scope.kind == "exact":
        return scope.path == path
    prefix = scope.path.rstrip("/") + "/"
    return path == scope.path or path.startswith(prefix)


def _changed_paths_within_declared_writes(
    binding: ParallelRunBinding,
    evidence: EvidenceManifest,
) -> tuple[bool, list[str]]:
    outside = [
        path
        for path in evidence.changed_paths
        if not any(
            _scope_contains(scope, path)
            for scope in binding.admitted_plan.writes
        )
    ]
    return not outside, outside


def _block_scope_violation(
    root: Path,
    run_id: str,
    outside: list[str],
) -> None:
    store = RunStore(root)
    record = store.get(run_id)
    store.append_event(
        run_id,
        "parallel.write_scope_violation",
        {"changed_paths_outside_scope": outside},
    )
    if record.status == RunStatus.READY_TO_INTEGRATE:
        final = store.transition(
            run_id,
            expected={RunStatus.READY_TO_INTEGRATE},
            status=RunStatus.NEEDS_DECISION,
            terminal_reason=RunTerminalReason.POLICY_BLOCKED,
        )
        try:
            reconcile_terminal_task(
                root,
                store=store,
                run_id=final.run_id,
                actor=_actor(),
            )
        except Exception as exc:
            store.append_event(
                run_id,
                "parallel.scope_reconcile_failed",
                {"error": str(exc)},
            )


def validate_parallel_candidate_scope(
    project_root: Path,
    run_id: str,
) -> None:
    root = project_root.resolve()
    binding = load_parallel_run_binding(root, run_id)
    assert binding is not None
    record = RunStore(root).get(run_id)
    if record.status != RunStatus.READY_TO_INTEGRATE:
        raise ConfigurationError(
            f"Parallel scope validation requires ready_to_integrate, found "
            f"{record.status.value}."
        )
    evidence = _load_json_model(
        root / ".projectctl" / "runs" / run_id / "evidence-manifest.json",
        EvidenceManifest,
    )
    ok, outside = _changed_paths_within_declared_writes(binding, evidence)
    if not ok:
        _block_scope_violation(root, run_id, outside)
        raise IntegrationError(
            "Verified candidate changed paths outside its declared parallel write scope: "
            + ", ".join(outside)
        )


def _git(
    root: Path,
    *args: str,
    check: bool = True,
    text: bool = True,
    input_bytes: bytes | None = None,
):
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=text,
        input=(None if text else input_bytes),
        check=False,
    )
    if check and result.returncode != 0:
        stderr = result.stderr
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", errors="replace")
        stdout = result.stdout
        if isinstance(stdout, bytes):
            stdout = stdout.decode("utf-8", errors="replace")
        raise IntegrationError(
            (stderr or stdout or f"git {' '.join(args)} failed").strip()
        )
    return result


def _target_advance_paths(root: Path, old_base: str, new_base: str) -> list[str]:
    ancestor = _git(
        root,
        "merge-base",
        "--is-ancestor",
        old_base,
        new_base,
        check=False,
    )
    if ancestor.returncode != 0:
        raise IntegrationError(
            "Parallel reapplication requires the recorded base to remain an ancestor "
            "of the current integration target."
        )
    result = _git(
        root,
        "diff",
        "--name-only",
        "--diff-filter=ACDMRTUXB",
        old_base,
        new_base,
        "--",
    )
    return sorted({line.strip() for line in result.stdout.splitlines() if line.strip()})


def _advance_conflicts_with_plan(
    plan: ParallelPlan,
    changed_paths: list[str],
) -> list[str]:
    conflicts: list[str] = []
    input_scopes = [item.scope for item in plan.inputs]
    for path in changed_paths:
        synthetic = type(plan.writes[0])(path=path, kind="exact")
        if any(_path_scopes_overlap(scope, synthetic) for scope in plan.writes):
            conflicts.append(path)
            continue
        if any(_path_scopes_overlap(scope, synthetic) for scope in input_scopes):
            conflicts.append(path)
    return sorted(set(conflicts))


def _assert_runtime_inputs_stable(
    root: Path,
    binding: ParallelRunBinding,
    *,
    new_base: str,
) -> None:
    plan = binding.admitted_plan
    if getattr(binding, "execution_input_digest", None):
        run_dir = root / ".projectctl" / "runs" / binding.run_id
        execution_input = load_execution_input(
            run_dir / "execution-input-manifest.json"
        )
        transition = load_claim_transition(
            run_dir / "claim-transition.json"
        )
        if (
            execution_input_semantic_digest(execution_input)
            != binding.execution_input_digest
        ):
            raise StaleSnapshotError(
                "Parallel binding execution-input identity changed."
            )
        if (
            getattr(binding, "claim_transition_digest", None) is not None
            and digest(transition) != binding.claim_transition_digest
        ):
            raise StaleSnapshotError(
                "Parallel binding claim-transition identity changed."
            )
        validate_admitted_execution_input(
            root,
            execution_input,
            transition,
            require_target_at_base=False,
        )

    config = load_project_config(root)
    if config.project.id != plan.project_id:
        raise StaleSnapshotError("Parallel run project identity changed.")

    state = load_project_state(root, allow_missing=True)
    if semantic_project_state_digest(state) != plan.project_state_digest:
        raise StaleSnapshotError("Parallel run project-state input changed.")

    snapshot = capture_task_snapshot(
        root,
        state="all",
        read_cache_max_age_seconds=0,
    )
    scoped_digest, scoped_ids = semantic_task_scope_digest(snapshot, plan.task_id)
    if scoped_digest != plan.scoped_task_digest or scoped_ids != plan.scoped_task_ids:
        raise StaleSnapshotError(
            "Parallel run task/dependency authority changed after admission."
        )

    scope = task_parallel_scope(root, plan.task_id)
    if digest(scope) != plan.scope_digest:
        raise StaleSnapshotError("Parallel run scope declaration changed.")

    new_inputs = [
        ParallelInputEvidence(
            scope=item.scope,
            digest=_input_scope_digest(root, new_base, item.scope),
        )
        for item in plan.inputs
    ]
    if new_inputs != plan.inputs:
        raise StaleSnapshotError(
            "Current target changed one or more declared parallel inputs."
        )


def _patch_bytes(
    worktree: Path,
    old_base: str,
    candidate: str,
) -> bytes:
    result = _git(
        worktree,
        "diff",
        "--binary",
        old_base,
        candidate,
        "--",
        text=False,
    )
    patch = bytes(result.stdout)
    if not patch:
        raise IntegrationError("Verified candidate produced an empty reapplication patch.")
    return patch


def _preflight_patch(
    root: Path,
    *,
    target_base: str,
    patch: bytes,
) -> None:
    with tempfile.TemporaryDirectory(prefix="projectctl-reapply-check-") as tmp:
        check_root = Path(tmp) / "worktree"
        _git(root, "worktree", "add", "--detach", str(check_root), target_base)
        try:
            result = subprocess.run(
                ["git", "-C", str(check_root), "apply", "--check", "--whitespace=nowarn", "-"],
                input=patch,
                capture_output=True,
                check=False,
            )
            if result.returncode != 0:
                raise IntegrationError(
                    "Parallel patch cannot be applied cleanly to the advanced target: "
                    + result.stderr.decode("utf-8", errors="replace").strip()
                )
        finally:
            _git(root, "worktree", "remove", "--force", str(check_root), check=False)


def _latest_reapplication_request(run_dir: Path):
    root = run_dir / "reapplications"
    if not root.exists():
        return None
    candidates = []
    for path in root.glob("*/request.json"):
        try:
            request = parse_parallel_reapplication_request(
                json.loads(path.read_text(encoding="utf-8"))
            )
        except Exception as exc:
            raise RecoveryError(
                f"Invalid parallel reapplication request {path}: {exc}"
            ) from exc
        candidates.append((request.requested_at, request.reapplication_id, path, request))
    if not candidates:
        return None
    _, _, path, request = max(candidates, key=lambda item: (item[0], item[1]))
    return path.parent, request


def _reapply_locked(root: Path, run_id: str) -> ParallelReapplicationManifest:
    store = RunStore(root)
    actor = _actor()
    record = store.acquire_lease(run_id, owner=actor)
    run_dir = root / ".projectctl" / "runs" / run_id
    try:
        if record.status != RunStatus.READY_TO_INTEGRATE:
            raise IntegrationError(
                f"Parallel reapplication requires ready_to_integrate, found "
                f"{record.status.value}."
            )

        binding = load_parallel_run_binding(root, run_id)
        assert binding is not None
        plan = _load_json_model(run_dir / "execution-plan.json", ExecutionPlan)
        evidence = _load_json_model(run_dir / "evidence-manifest.json", EvidenceManifest)
        source_execution_input = None
        source_execution_input_digest = getattr(plan, "execution_input_digest", None)
        source_input_path = run_dir / "execution-input-manifest.json"
        if source_execution_input_digest is not None:
            if not source_input_path.exists():
                raise IntegrationError(
                    "M4.2a reapplication requires the source ExecutionInputManifest."
                )
            source_execution_input = load_execution_input(source_input_path)
            if (
                execution_input_semantic_digest(source_execution_input)
                != source_execution_input_digest
            ):
                raise IntegrationError(
                    "Source ExecutionInputManifest no longer matches ExecutionPlan."
                )
        worktree = _validate_verified_candidate(
            root,
            record,
            plan,
            evidence,
            run_dir=run_dir,
        )
        ok, outside = _changed_paths_within_declared_writes(binding, evidence)
        if not ok:
            _block_scope_violation(root, run_id, outside)
            raise IntegrationError(
                "Cannot reapply candidate outside declared write scope: "
                + ", ".join(outside)
            )

        target_base = resolve_commit(root, plan.integration_target_ref)
        if target_base == plan.base_commit:
            raise IntegrationError("Reapplication requested although target has not advanced.")

        changed_paths = _target_advance_paths(root, plan.base_commit, target_base)
        conflicts = _advance_conflicts_with_plan(binding.admitted_plan, changed_paths)
        if conflicts:
            raise IntegrationError(
                "Target advancement overlaps this run's input/write scope: "
                + ", ".join(conflicts)
            )
        _assert_runtime_inputs_stable(root, binding, new_base=target_base)

        patch = _patch_bytes(worktree, plan.base_commit, record.candidate_commit)
        patch_digest = "sha256:" + hashlib.sha256(patch).hexdigest()
        _preflight_patch(root, target_base=target_base, patch=patch)

        reapplication_id = f"reapply-{uuid.uuid4().hex}"
        reapply_dir = run_dir / "reapplications" / reapplication_id
        patch_rel = (
            f".projectctl/runs/{run_id}/reapplications/"
            f"{reapplication_id}/candidate.patch"
        )
        request = ParallelReapplicationRequest(
            reapplication_id=reapplication_id,
            run_id=run_id,
            task_id=record.task_id,
            source_base_commit=plan.base_commit,
            source_candidate_commit=record.candidate_commit,
            source_execution_plan_digest=digest(plan),
            source_execution_input_digest=source_execution_input_digest,
            source_evidence_digest=digest(evidence),
            target_base_commit=target_base,
            target_advance_changed_paths=changed_paths,
            patch_digest=patch_digest,
            patch_artifact=patch_rel,
            requested_at=utc_now(),
        )
        _atomic_json(reapply_dir / "request.json", request)
        reapply_dir.mkdir(parents=True, exist_ok=True)
        (reapply_dir / "candidate.patch").write_bytes(patch)
        shutil.copy2(run_dir / "execution-plan.json", reapply_dir / "source-execution-plan.json")
        if source_input_path.exists():
            shutil.copy2(
                source_input_path,
                reapply_dir / "source-execution-input-manifest.json",
            )
        transition_path = run_dir / "claim-transition.json"
        if transition_path.exists():
            shutil.copy2(
                transition_path,
                reapply_dir / "source-claim-transition.json",
            )
        shutil.copy2(run_dir / "evidence-manifest.json", reapply_dir / "source-evidence-manifest.json")
        verification_path = run_dir / "verification-manifest.json"
        if verification_path.exists():
            shutil.copy2(
                verification_path,
                reapply_dir / "source-verification-manifest.json",
            )

        _git(worktree, "reset", "--hard", target_base)
        apply_result = subprocess.run(
            ["git", "-C", str(worktree), "apply", "--whitespace=nowarn", "-"],
            input=patch,
            capture_output=True,
            check=False,
        )
        if apply_result.returncode != 0:
            raise IntegrationError(
                "Preflight succeeded but applying the parallel patch failed: "
                + apply_result.stderr.decode("utf-8", errors="replace").strip()
            )
        if resolve_commit(worktree, "HEAD") != target_base:
            raise IntegrationError("Reapplied worktree HEAD does not equal the new target base.")

        updated_execution_input_digest = source_execution_input_digest
        if source_execution_input is not None:
            updated_execution_input = derive_reapplied_execution_input(
                source_execution_input,
                target_base_commit=target_base,
                reapplication_id=reapplication_id,
            )
            # The target-advance checks above prove these code-input digests are
            # unchanged on the new base. Persist a derived input artifact with
            # explicit lineage rather than pretending the old base is current.
            persist_execution_input(source_input_path, updated_execution_input)
            updated_execution_input_digest = execution_input_semantic_digest(
                updated_execution_input
            )

        lineage = None
        if source_execution_input_digest is not None:
            lineage = ExecutionPlanLineage(
                transformation="parallel_reapplication",
                source_execution_plan_digest=digest(plan),
                source_execution_input_digest=source_execution_input_digest,
                source_base_commit=plan.base_commit,
                source_candidate_commit=record.candidate_commit,
                reapplication_id=reapplication_id,
            )
        new_plan = plan.model_copy(
            update={
                "base_commit": target_base,
                "execution_input_digest": updated_execution_input_digest,
                "lineage": lineage,
                "created_at": utc_now(),
            }
        )
        new_plan_digest = digest(new_plan)
        _atomic_json(run_dir / "execution-plan.json", new_plan)
        for stale_name in ("verification-manifest.json", "evidence-manifest.json"):
            stale_path = run_dir / stale_name
            if stale_path.exists():
                stale_path.unlink()

        store.rebind_for_reverification(
            run_id,
            expected={RunStatus.READY_TO_INTEGRATE},
            execution_plan_digest=new_plan_digest,
            base_commit=target_base,
        )
        manifest = ParallelReapplicationManifest(
            reapplication_id=reapplication_id,
            run_id=run_id,
            task_id=record.task_id,
            source_base_commit=request.source_base_commit,
            source_candidate_commit=request.source_candidate_commit,
            source_execution_plan_digest=request.source_execution_plan_digest,
            source_execution_input_digest=request.source_execution_input_digest,
            source_evidence_digest=request.source_evidence_digest,
            target_base_commit=target_base,
            target_advance_changed_paths=changed_paths,
            patch_digest=patch_digest,
            updated_execution_plan_digest=new_plan_digest,
            updated_execution_input_digest=updated_execution_input_digest,
            reapplied_at=utc_now(),
        )
        _atomic_json(reapply_dir / "manifest.json", manifest)
        store.append_event(
            run_id,
            "parallel.reapplied",
            {
                "reapplication_id": reapplication_id,
                "manifest_digest": digest(manifest),
                "source_candidate_commit": request.source_candidate_commit,
                "target_base_commit": target_base,
                "updated_execution_input_digest": updated_execution_input_digest,
                "fresh_verification_required": True,
            },
        )
        return manifest
    finally:
        try:
            store.release_lease(run_id, owner=actor)
        except Exception:
            pass


def recover_parallel_reapplication(
    project_root: Path,
    run_id: str,
) -> str | None:
    root = project_root.resolve()
    run_dir = root / ".projectctl" / "runs" / run_id
    latest = _latest_reapplication_request(run_dir)
    if latest is None:
        return None
    reapply_dir, request = latest
    manifest_path = reapply_dir / "manifest.json"
    if manifest_path.exists():
        return "complete"

    store = RunStore(root)
    record = store.get(run_id)
    plan_path = run_dir / "execution-plan.json"
    worktree = Path(record.worktree_path).resolve()
    if not worktree.exists():
        raise RecoveryError("Reapplication recovery cannot find the run worktree.")

    head = resolve_commit(worktree, "HEAD")
    if record.status == RunStatus.READY_TO_INTEGRATE and head == request.source_candidate_commit:
        return "retry_safe"

    if head == request.target_base_commit:
        plan = _load_json_model(plan_path, ExecutionPlan)
        if plan.base_commit == request.target_base_commit and record.status == RunStatus.VERIFYING:
            return "reverification_required"

    store.append_event(
        run_id,
        "parallel.reapplication_ambiguous",
        {
            "reapplication_id": request.reapplication_id,
            "source_candidate_commit": request.source_candidate_commit,
            "target_base_commit": request.target_base_commit,
            "observed_head": head,
            "status": record.status.value,
        },
    )
    if record.status in {
        RunStatus.READY_TO_INTEGRATE,
        RunStatus.VERIFYING,
        RunStatus.INTEGRATING,
    }:
        final = store.transition(
            run_id,
            expected={record.status},
            status=RunStatus.NEEDS_DECISION,
            terminal_reason=RunTerminalReason.RECOVERY_UNSAFE,
        )
        try:
            reconcile_terminal_task(
                root,
                store=store,
                run_id=final.run_id,
                actor=_actor(),
            )
        except Exception as exc:
            store.append_event(
                run_id,
                "parallel.reapplication_reconcile_failed",
                {"error": str(exc)},
            )
    raise RecoveryError(
        "Parallel reapplication is in an ambiguous crash state; "
        "run persisted as needs_decision when lifecycle allowed."
    )


def integrate_parallel_run(
    project_root: Path,
    run_id: str,
):
    root = project_root.resolve()
    with project_lock(root, "integration"):
        binding = load_parallel_run_binding(root, run_id)
        assert binding is not None
        queue = build_parallel_integration_queue(
            root,
            target_ref=binding.admitted_plan.integration_target_ref,
            persist=True,
        )
        if not queue.entries or queue.entries[0].run_id != run_id:
            head = queue.entries[0].run_id if queue.entries else None
            raise IntegrationError(
                f"Run {run_id} is not the deterministic integration-queue head; "
                f"current head is {head!r}."
            )

        record = RunStore(root).get(run_id)
        if record.status != RunStatus.READY_TO_INTEGRATE:
            raise IntegrationError(
                f"Integration-queue head {run_id} is {record.status.value}; "
                "later runs must wait."
            )

        validate_parallel_candidate_scope(root, run_id)
        run_dir = root / ".projectctl" / "runs" / run_id
        plan = _load_json_model(run_dir / "execution-plan.json", ExecutionPlan)
        target = resolve_commit(root, plan.integration_target_ref)
        if target != plan.base_commit:
            _reapply_locked(root, run_id)
            verified = verify_run(root, run_id)
            if verified.record.status != RunStatus.READY_TO_INTEGRATE:
                raise IntegrationError(
                    "Fresh verification after parallel reapplication did not produce "
                    "ready_to_integrate."
                )
            validate_parallel_candidate_scope(root, run_id)

        return _integrate_run_locked(root, run_id)


def recover_parallel_project(project_root: Path) -> list[str]:
    root = project_root.resolve()
    details: list[str] = []
    with project_lock(root, "parallel-recovery"):
        active = _active_bindings(root)
        plans = [binding.admitted_plan for _, binding in active]
        for index, left in enumerate(plans):
            for right in plans[index + 1 :]:
                decision = assess_parallel_safety(left, right)
                if not decision.independent:
                    raise RecoveryError(
                        "Active parallel run set no longer has a valid pairwise independence proof."
                    )

        for record, _ in active:
            reapply = recover_parallel_reapplication(root, record.run_id)
            if reapply is not None:
                details.append(f"{record.run_id}:reapplication:{reapply}")
            current = RunStore(root).get(record.run_id)
            if (
                current.lease_owner is not None
                and current.lease_expires_at is not None
                and current.lease_expires_at > utc_now()
            ):
                details.append(f"{record.run_id}:live_lease")
                continue
            action = recover_run(root, record.run_id)
            details.append(
                f"{record.run_id}:{action.action}:{action.resolved_status}"
            )
    return details


def _advance_parallel_run(root: Path, run_id: str):
    store = RunStore(root)
    record = store.get(run_id)

    if record.status in {RunStatus.PREPARING, RunStatus.INTEGRATING, RunStatus.AWAITING_REVIEW}:
        recover_run(root, run_id)
        record = store.get(run_id)

    if record.status == RunStatus.RUNNING:
        if record.checkpoint_ref:
            resume_checkpointed_run(root, run_id)
        else:
            recover_run(root, run_id)
        record = store.get(run_id)

    if record.status == RunStatus.CLAIMED:
        start_prepared_run(root, run_id)
        record = store.get(run_id)

    if record.status == RunStatus.VERIFYING:
        verify_run(root, run_id)
        record = store.get(run_id)
        if record.status == RunStatus.READY_TO_INTEGRATE:
            validate_parallel_candidate_scope(root, run_id)

    return store.get(run_id)


def run_parallel_batch(
    project_root: Path,
    *,
    max_parallel_runs: int = 2,
    requested_strategy=None,
    fallback: StrategyFallbackPolicy | None = None,
) -> ParallelBatchResult:
    if max_parallel_runs < 2 or max_parallel_runs > 8:
        raise ValueError("max_parallel_runs must be between 2 and 8.")

    root = project_root.resolve()
    started_at = utc_now()
    prepared_ids: list[str] = []
    completed_ids: list[str] = []
    details: list[str] = []

    recover_parallel_project(root)

    while len(_active_records(root)) < max_parallel_runs:
        try:
            prepared = prepare_parallel_run(
                root,
                max_parallel_runs=max_parallel_runs,
                requested_strategy=requested_strategy,
                fallback=fallback,
            )
        except ConfigurationError as exc:
            details.append(f"fill_stopped:{exc}")
            break
        prepared_ids.append(prepared.record.run_id)

    active = _active_bindings(root)
    for record, _ in active:
        try:
            _advance_parallel_run(root, record.run_id)
        except ProjectCtlError as exc:
            details.append(f"{record.run_id}:advance_stopped:{exc}")

    while True:
        queue = build_parallel_integration_queue(root, persist=True)
        if not queue.entries:
            break
        head = queue.entries[0]
        current = RunStore(root).get(head.run_id)

        if current.status == RunStatus.READY_TO_INTEGRATE:
            try:
                integrated = integrate_parallel_run(root, head.run_id)
            except ProjectCtlError as exc:
                details.append(f"{head.run_id}:integration_stopped:{exc}")
                break
            if integrated.record.status == RunStatus.PASSED:
                completed_ids.append(head.run_id)
                continue
            details.append(
                f"{head.run_id}:integration_wait:{integrated.record.status.value}"
            )
            break

        if current.status in {RunStatus.INTEGRATING, RunStatus.AWAITING_REVIEW}:
            try:
                action = recover_run(root, head.run_id)
                details.append(
                    f"{head.run_id}:recover:{action.action}:{action.resolved_status}"
                )
            except ProjectCtlError as exc:
                details.append(f"{head.run_id}:recover_stopped:{exc}")
                break
            if RunStore(root).get(head.run_id).status == RunStatus.PASSED:
                completed_ids.append(head.run_id)
                continue
            break

        try:
            _advance_parallel_run(root, head.run_id)
        except ProjectCtlError as exc:
            details.append(f"{head.run_id}:advance_stopped:{exc}")
            break
        current = RunStore(root).get(head.run_id)
        if current.status not in {RunStatus.READY_TO_INTEGRATE, RunStatus.PASSED}:
            details.append(f"{head.run_id}:waiting:{current.status.value}")
            break

    remaining = [
        record.run_id
        for record in _active_records(root)
    ]
    return ParallelBatchResult(
        started_at=started_at,
        completed_at=utc_now(),
        max_parallel_runs=max_parallel_runs,
        prepared_run_ids=prepared_ids,
        completed_run_ids=completed_ids,
        remaining_run_ids=remaining,
        details=details,
    )
