from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

from projectctl.application.claims import (
    claim_ref,
    load_durable_claim,
    load_durable_claim_request,
    persist_claim,
)
from projectctl.application.execution import (
    _actor,
    _checkpoint_event_matches,
    _worktree_state_digest,
)
from projectctl.application.integration import (
    _cleanup_verified_worktree,
    _finalize_delivery,
    _load_json_model,
)
from projectctl.application.task_lifecycle import reconcile_terminal_task
from projectctl.core.digest import digest
from projectctl.core.enums import RunStatus, RunTerminalReason, WorkerResultStatus
from projectctl.core.errors import RecoveryError, RunLeaseError
from projectctl.core.time import utc_now
from projectctl.git import WorktreeManager, current_branch, resolve_commit
from projectctl.integrations.execution_ownership import resolve_execution_ownership
from projectctl.schemas.evidence import EvidenceManifest
from projectctl.schemas.execution import (
    EvidenceReference,
    ExecutionPlan,
    WorkerCheckpoint,
    WorkerRequest,
    WorkerResult,
    parse_worker_checkpoint,
)
from projectctl.schemas.integration import IntegrationManifest, RecoveryAction
from projectctl.schemas.run import ContextManifest
from projectctl.storage.runs import RunStore


def _active_lease(record) -> bool:
    return (
        record.lease_owner is not None
        and record.lease_expires_at is not None
        and record.lease_expires_at > utc_now()
    )


def _prepare_worktree_is_safe(
    root: Path,
    *,
    record,
    plan: ExecutionPlan,
) -> bool:
    manager = WorktreeManager(root)
    expected = manager.path_for(record.worktree_id)
    actual = Path(record.worktree_path).resolve()
    if actual != expected or not actual.exists():
        return False
    try:
        if current_branch(actual) != record.branch_name:
            return False
        if resolve_commit(actual, "HEAD") != plan.base_commit:
            return False
    except Exception:
        return False
    status = subprocess.run(
        ["git", "-C", str(actual), "status", "--porcelain"],
        capture_output=True,
        text=True,
        check=False,
    )
    return status.returncode == 0 and not status.stdout.strip()


def _recover_preparing(
    root: Path,
    *,
    store: RunStore,
    record,
    previous: RunStatus,
    actor: str,
    run_dir: Path,
) -> RecoveryAction:
    details: list[str] = []
    request = load_durable_claim_request(
        root,
        store=store,
        run_id=record.run_id,
        allow_missing=True,
    )
    if request is None:
        details.append(
            "No durable TaskClaimRequest exists; ownership cannot be reconstructed "
            "without guessing whether this is a legacy partial prepare."
        )
        return RecoveryAction(
            run_id=record.run_id,
            previous_status=previous.value,
            resolved_status=record.status.value,
            action="prepare_recovery_required",
            details=details,
        )

    plan = _load_json_model(run_dir / "execution-plan.json", ExecutionPlan)
    if (
        request.task_id != record.task_id
        or request.base_commit != record.base_commit
        or request.base_commit != plan.base_commit
        or request.integration_target_ref != plan.integration_target_ref
    ):
        final = store.transition(
            record.run_id,
            expected={RunStatus.PREPARING},
            status=RunStatus.NEEDS_DECISION,
            terminal_reason=RunTerminalReason.RECOVERY_UNSAFE,
        )
        details.append("Task claim request does not match durable run/execution plan identity.")
        return RecoveryAction(
            run_id=record.run_id,
            previous_status=previous.value,
            resolved_status=final.status.value,
            action="escalated_prepare_recovery",
            details=details,
        )

    claim_path = root / claim_ref(record.run_id)
    if claim_path.exists():
        durable = load_durable_claim(
            root,
            store=store,
            run_id=record.run_id,
            require_acquired=False,
        )
        assert durable is not None
        _, claim = durable
    else:
        claimer = resolve_execution_ownership(root).claimer
        claim = claimer.reconcile(request)
        if claim is None:
            final = store.transition(
                record.run_id,
                expected={RunStatus.PREPARING},
                status=RunStatus.NEEDS_DECISION,
                terminal_reason=RunTerminalReason.RECOVERY_UNSAFE,
            )
            details.append(
                "Configured task authority cannot prove ownership from the durable claim request."
            )
            return RecoveryAction(
                run_id=record.run_id,
                previous_status=previous.value,
                resolved_status=final.status.value,
                action="escalated_prepare_recovery",
                details=details,
            )
        persist_claim(
            root,
            store=store,
            request=request,
            claim=claim,
        )
        details.append("Missing TaskClaim result was reconstructed by non-mutating provider observation.")

    if not claim.acquired:
        final = store.transition(
            record.run_id,
            expected={RunStatus.PREPARING},
            status=RunStatus.FAILED,
            terminal_reason=RunTerminalReason.CLAIM_LOST,
        )
        details.append(claim.reason or "Durable claim request does not own the remote task claim.")
        return RecoveryAction(
            run_id=record.run_id,
            previous_status=previous.value,
            resolved_status=final.status.value,
            action="prepare_claim_lost",
            details=details,
        )

    claimer = resolve_execution_ownership(root).claimer
    if not claimer.validate(claim):
        final = store.transition(
            record.run_id,
            expected={RunStatus.PREPARING},
            status=RunStatus.FAILED,
            terminal_reason=RunTerminalReason.CLAIM_LOST,
        )
        details.append("Durable claim exists but current provider ownership no longer matches.")
        return RecoveryAction(
            run_id=record.run_id,
            previous_status=previous.value,
            resolved_status=final.status.value,
            action="prepare_claim_lost",
            details=details,
        )

    manager = WorktreeManager(root)
    expected = manager.path_for(record.worktree_id)
    if expected.exists():
        if not _prepare_worktree_is_safe(root, record=record, plan=plan):
            final = store.transition(
                record.run_id,
                expected={RunStatus.PREPARING},
                status=RunStatus.NEEDS_DECISION,
                terminal_reason=RunTerminalReason.RECOVERY_UNSAFE,
            )
            details.append("Existing partial prepare worktree cannot be proven clean/base-aligned.")
            return RecoveryAction(
                run_id=record.run_id,
                previous_status=previous.value,
                resolved_status=final.status.value,
                action="escalated_prepare_recovery",
                details=details,
            )
        details.append("Existing isolated worktree is clean and base-aligned.")
    else:
        try:
            manager.create(
                worktree_id=record.worktree_id,
                branch_name=record.branch_name,
                base_commit=plan.base_commit,
            )
        except Exception as exc:
            final = store.transition(
                record.run_id,
                expected={RunStatus.PREPARING},
                status=RunStatus.NEEDS_DECISION,
                terminal_reason=RunTerminalReason.RECOVERY_UNSAFE,
            )
            details.append(f"Claim is owned but worktree reconstruction is unsafe: {exc}")
            return RecoveryAction(
                run_id=record.run_id,
                previous_status=previous.value,
                resolved_status=final.status.value,
                action="escalated_prepare_recovery",
                details=details,
            )
        details.append("Missing isolated worktree was reconstructed from the exact execution base.")

    final = store.transition(
        record.run_id,
        expected={RunStatus.PREPARING},
        status=RunStatus.CLAIMED,
    )
    details.append("Durable claim and isolated worktree reconciled to CLAIMED.")
    return RecoveryAction(
        run_id=record.run_id,
        previous_status=previous.value,
        resolved_status=final.status.value,
        action="reconciled_prepare",
        details=details,
    )


def recover_run(project_root: Path, run_id: str) -> RecoveryAction:
    root = project_root.resolve()
    store = RunStore(root)
    before = store.get(run_id)
    previous = before.status

    if _active_lease(before):
        raise RunLeaseError(
            f"Run {run_id} still has an active lease owned by {before.lease_owner}."
        )

    actor = _actor()
    record = store.acquire_lease(run_id, owner=actor)
    run_dir = root / ".projectctl" / "runs" / run_id
    details: list[str] = []

    try:
        if record.status == RunStatus.PREPARING:
            return _recover_preparing(
                root,
                store=store,
                record=record,
                previous=previous,
                actor=actor,
                run_dir=run_dir,
            )

        if record.status == RunStatus.CLAIMED:
            plan = _load_json_model(run_dir / "execution-plan.json", ExecutionPlan)
            durable = load_durable_claim(
                root,
                store=store,
                run_id=run_id,
                allow_legacy_missing=True,
            )
            if durable is not None:
                _, claim = durable
                claimer = resolve_execution_ownership(root).claimer
                if not claimer.validate(claim):
                    final = store.transition(
                        run_id,
                        expected={RunStatus.CLAIMED},
                        status=RunStatus.FAILED,
                        terminal_reason=RunTerminalReason.CLAIM_LOST,
                    )
                    details.append("Durable task claim ownership was lost before worker start.")
                    return RecoveryAction(
                        run_id=run_id,
                        previous_status=previous.value,
                        resolved_status=final.status.value,
                        action="claimed_ownership_lost",
                        details=details,
                    )

                expected = WorktreeManager(root).path_for(record.worktree_id)
                if not expected.exists():
                    try:
                        WorktreeManager(root).create(
                            worktree_id=record.worktree_id,
                            branch_name=record.branch_name,
                            base_commit=plan.base_commit,
                        )
                    except Exception as exc:
                        final = store.transition(
                            run_id,
                            expected={RunStatus.CLAIMED},
                            status=RunStatus.NEEDS_DECISION,
                            terminal_reason=RunTerminalReason.RECOVERY_UNSAFE,
                        )
                        details.append(f"Owned claim has no safe worktree and reconstruction failed: {exc}")
                        return RecoveryAction(
                            run_id=run_id,
                            previous_status=previous.value,
                            resolved_status=final.status.value,
                            action="escalated_claimed_recovery",
                            details=details,
                        )
                    details.append("Missing claimed worktree was reconstructed from the exact base.")

                if not _prepare_worktree_is_safe(root, record=record, plan=plan):
                    final = store.transition(
                        run_id,
                        expected={RunStatus.CLAIMED},
                        status=RunStatus.NEEDS_DECISION,
                        terminal_reason=RunTerminalReason.RECOVERY_UNSAFE,
                    )
                    details.append("Claimed worktree is not clean/base-aligned.")
                    return RecoveryAction(
                        run_id=run_id,
                        previous_status=previous.value,
                        resolved_status=final.status.value,
                        action="escalated_claimed_recovery",
                        details=details,
                    )

            details.append("CLAIMED run ownership/worktree state is ready for worker start.")
            return RecoveryAction(
                run_id=run_id,
                previous_status=previous.value,
                resolved_status=record.status.value,
                action="claimed_ready",
                details=details,
            )

        if record.status == RunStatus.RUNNING:
            if record.checkpoint_ref:
                checkpoint_path = (root / record.checkpoint_ref).resolve()
                if not checkpoint_path.is_relative_to(root) or not checkpoint_path.exists():
                    final = store.transition(
                        run_id,
                        expected={RunStatus.RUNNING},
                        status=RunStatus.NEEDS_DECISION,
                        terminal_reason=RunTerminalReason.RECOVERY_UNSAFE,
                    )
                    final = reconcile_terminal_task(
                        root,
                        store=store,
                        run_id=run_id,
                        actor=actor,
                    )
                    details.append("Durable checkpoint reference is missing or unsafe.")
                    return RecoveryAction(
                        run_id=run_id,
                        previous_status=previous.value,
                        resolved_status=final.status.value,
                        action="escalated_checkpoint_recovery",
                        details=details,
                    )

                try:
                    raw = json.loads(checkpoint_path.read_text(encoding="utf-8"))
                    checkpoint = parse_worker_checkpoint(raw)
                except Exception as exc:
                    raise RecoveryError(
                        f"Checkpoint artifact cannot be read safely: {exc}"
                    ) from exc

                plan = _load_json_model(run_dir / "execution-plan.json", ExecutionPlan)
                request = _load_json_model(run_dir / "worker-request.json", WorkerRequest)
                context = _load_json_model(run_dir / "context-manifest.json", ContextManifest)
                worktree = Path(record.worktree_path)
                resumable = (
                    isinstance(checkpoint, WorkerCheckpoint)
                    and _checkpoint_event_matches(
                        store, run_id, record.checkpoint_ref, checkpoint
                    )
                    and checkpoint.run_id == record.run_id
                    and checkpoint.task_id == record.task_id
                    and checkpoint.worktree_id == record.worktree_id
                    and checkpoint.base_commit == record.base_commit
                    and checkpoint.branch_name == record.branch_name
                    and checkpoint.worker_thread_id == record.worker_thread_id
                    and digest(checkpoint.quota_snapshot) == checkpoint.quota_snapshot_digest
                    and digest(request) == checkpoint.worker_request_digest
                    and digest(context) == checkpoint.context_manifest_digest
                    and request.context_manifest_digest == checkpoint.context_manifest_digest
                    and checkpoint.workspace_digest is not None
                    and worktree.exists()
                    and resolve_commit(worktree, "HEAD") == plan.base_commit
                    and _worktree_state_digest(worktree) == checkpoint.workspace_digest
                )
                if resumable:
                    details.append(
                        "Durable M2.2 quota checkpoint is intact; worker resume is safe when quota permits."
                    )
                    return RecoveryAction(
                        run_id=run_id,
                        previous_status=previous.value,
                        resolved_status=record.status.value,
                        action="checkpoint_resume_ready",
                        details=details,
                    )

                final = store.transition(
                    run_id,
                    expected={RunStatus.RUNNING},
                    status=RunStatus.NEEDS_DECISION,
                    terminal_reason=RunTerminalReason.RECOVERY_UNSAFE,
                )
                final = reconcile_terminal_task(
                    root,
                    store=store,
                    run_id=run_id,
                    actor=actor,
                )
                details.append("Checkpoint identity, worktree, or Git history cannot be reconciled safely.")
                return RecoveryAction(
                    run_id=run_id,
                    previous_status=previous.value,
                    resolved_status=final.status.value,
                    action="escalated_checkpoint_recovery",
                    details=details,
                )

            result_path = run_dir / "worker-result.json"
            if not result_path.exists():
                final = store.transition(
                    run_id,
                    expected={RunStatus.RUNNING},
                    status=RunStatus.NEEDS_DECISION,
                    terminal_reason=RunTerminalReason.RECOVERY_UNSAFE,
                )
                final = reconcile_terminal_task(
                    root,
                    store=store,
                    run_id=run_id,
                    actor=actor,
                )
                details.append("No durable WorkerResult exists; automatic worker resume is unsafe.")
                return RecoveryAction(
                    run_id=run_id,
                    previous_status=previous.value,
                    resolved_status=final.status.value,
                    action="escalated_worker_recovery",
                    details=details,
                )
            result = _load_json_model(result_path, WorkerResult)
            plan = _load_json_model(run_dir / "execution-plan.json", ExecutionPlan)
            worktree = Path(record.worktree_path)
            if (
                result.status == WorkerResultStatus.IMPLEMENTED
                and worktree.exists()
                and resolve_commit(worktree, "HEAD") == plan.base_commit
            ):
                final = store.transition(
                    run_id,
                    expected={RunStatus.RUNNING},
                    status=RunStatus.VERIFYING,
                    worker_thread_id=result.worker_thread_id,
                )
                details.append("Durable implemented WorkerResult reconciled to VERIFYING.")
                return RecoveryAction(
                    run_id=run_id,
                    previous_status=previous.value,
                    resolved_status=final.status.value,
                    action="reconciled_worker_result",
                    details=details,
                )
            final = store.transition(
                run_id,
                expected={RunStatus.RUNNING},
                status=RunStatus.NEEDS_DECISION,
                terminal_reason=RunTerminalReason.RECOVERY_UNSAFE,
            )
            final = reconcile_terminal_task(
                root,
                store=store,
                run_id=run_id,
                actor=actor,
            )
            details.append("WorkerResult/worktree state cannot be reconciled safely.")
            return RecoveryAction(
                run_id=run_id,
                previous_status=previous.value,
                resolved_status=final.status.value,
                action="escalated_worker_recovery",
                details=details,
            )

        if record.status == RunStatus.VERIFYING:
            evidence_path = run_dir / "evidence-manifest.json"
            if evidence_path.exists():
                evidence = _load_json_model(evidence_path, EvidenceManifest)
                worktree = Path(record.worktree_path)
                if (
                    evidence.overall_pass
                    and evidence.candidate_commit
                    and worktree.exists()
                    and resolve_commit(worktree, "HEAD") == evidence.candidate_commit
                ):
                    final = store.transition(
                        run_id,
                        expected={RunStatus.VERIFYING},
                        status=RunStatus.READY_TO_INTEGRATE,
                        candidate_commit=evidence.candidate_commit,
                        evidence_manifest=f".projectctl/runs/{run_id}/evidence-manifest.json",
                    )
                    details.append("Passing evidence reconciled to READY_TO_INTEGRATE.")
                    return RecoveryAction(
                        run_id=run_id,
                        previous_status=previous.value,
                        resolved_status=final.status.value,
                        action="reconciled_verification",
                        details=details,
                    )
            details.append("Verification can be safely retried with projectctl run verify.")
            return RecoveryAction(
                run_id=run_id,
                previous_status=previous.value,
                resolved_status=record.status.value,
                action="verification_retryable",
                details=details,
            )

        if record.status == RunStatus.INTEGRATING:
            plan = _load_json_model(run_dir / "execution-plan.json", ExecutionPlan)
            evidence = _load_json_model(run_dir / "evidence-manifest.json", EvidenceManifest)
            target = resolve_commit(root, plan.integration_target_ref)

            if target == plan.base_commit:
                final = store.transition(
                    run_id,
                    expected={RunStatus.INTEGRATING},
                    status=RunStatus.READY_TO_INTEGRATE,
                    candidate_commit=record.candidate_commit,
                )
                details.append("Target is still at verified base; integration can be retried.")
                return RecoveryAction(
                    run_id=run_id,
                    previous_status=previous.value,
                    resolved_status=final.status.value,
                    action="integration_retryable",
                    details=details,
                )

            if target == record.candidate_commit:
                integrated = _finalize_delivery(
                    root,
                    store=store,
                    record=record,
                    plan=plan,
                    evidence=evidence,
                    target_before=plan.base_commit,
                    actor=actor,
                )
                details.append(
                    "Integrated Git state reconciled; publication/task completion "
                    "requirements and cleanup were finalized."
                )
                return RecoveryAction(
                    run_id=run_id,
                    previous_status=previous.value,
                    resolved_status=integrated.record.status.value,
                    action="finalized_delivery",
                    details=details,
                )

            final = store.transition(
                run_id,
                expected={RunStatus.INTEGRATING},
                status=RunStatus.NEEDS_DECISION,
                terminal_reason=RunTerminalReason.STALE_BASE,
            )
            final = reconcile_terminal_task(
                root,
                store=store,
                run_id=run_id,
                actor=actor,
            )
            details.append("Integration target differs from both base and candidate.")
            return RecoveryAction(
                run_id=run_id,
                previous_status=previous.value,
                resolved_status=final.status.value,
                action="integration_diverged",
                details=details,
            )

        if record.status == RunStatus.PASSED:
            worktree = WorktreeManager(root).path_for(record.worktree_id)
            if worktree.exists():
                cleaned = _cleanup_verified_worktree(root, record=record, store=store)
                details.append(
                    "Residual worktree cleanup succeeded."
                    if cleaned
                    else "Residual worktree cleanup still requires attention."
                )
            else:
                details.append("No residual worktree exists.")
            return RecoveryAction(
                run_id=run_id,
                previous_status=previous.value,
                resolved_status=record.status.value,
                action="cleanup_checked",
                details=details,
            )

        if record.status in {
            RunStatus.PLANNED,
            RunStatus.READY_TO_INTEGRATE,
        }:
            details.append("Run is in a deterministic retryable state; expired lease was reclaimed.")
            return RecoveryAction(
                run_id=run_id,
                previous_status=previous.value,
                resolved_status=record.status.value,
                action="lease_reclaimed",
                details=details,
            )

        reconciled = reconcile_terminal_task(
            root,
            store=store,
            run_id=run_id,
            actor=actor,
        )
        if reconciled.status != record.status or reconciled.status in {
            RunStatus.FAILED,
            RunStatus.CANCELLED,
            RunStatus.ABANDONED,
            RunStatus.NEEDS_DECISION,
            RunStatus.BLOCKED_POLICY,
        }:
            details.append("Canonical task state was reconciled with the terminal run.")
            return RecoveryAction(
                run_id=run_id,
                previous_status=previous.value,
                resolved_status=reconciled.status.value,
                action="task_reconciled",
                details=details,
            )

        details.append("Run is terminal or requires an explicit human decision; no mutation performed.")
        return RecoveryAction(
            run_id=run_id,
            previous_status=previous.value,
            resolved_status=record.status.value,
            action="no_action",
            details=details,
        )
    except Exception as exc:
        if isinstance(exc, (RecoveryError, RunLeaseError)):
            raise
        raise RecoveryError(f"Recovery failed for {run_id}: {exc}") from exc
    finally:
        try:
            store.release_lease(run_id, owner=actor)
        except Exception:
            pass
