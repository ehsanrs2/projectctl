from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from projectctl.application.execution import _actor
from projectctl.application.integration import (
    _atomic_json,
    _cleanup_verified_worktree,
    _completion_writer,
    _load_json_model,
)
from projectctl.core.digest import digest
from projectctl.core.enums import RunStatus, RunTerminalReason, WorkerResultStatus
from projectctl.core.errors import RecoveryError, RunLeaseError
from projectctl.core.time import utc_now
from projectctl.git import WorktreeManager, resolve_commit
from projectctl.schemas.evidence import EvidenceManifest
from projectctl.schemas.execution import EvidenceReference, ExecutionPlan, WorkerResult
from projectctl.schemas.integration import IntegrationManifest, RecoveryAction
from projectctl.storage.runs import RunStore


def _active_lease(record) -> bool:
    return (
        record.lease_owner is not None
        and record.lease_expires_at is not None
        and record.lease_expires_at > utc_now()
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
        if record.status == RunStatus.RUNNING:
            result_path = run_dir / "worker-result.json"
            if not result_path.exists():
                final = store.transition(
                    run_id,
                    expected={RunStatus.RUNNING},
                    status=RunStatus.NEEDS_DECISION,
                    terminal_reason=RunTerminalReason.RECOVERY_UNSAFE,
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
                evidence_ref = EvidenceReference(
                    path=f".projectctl/runs/{run_id}/evidence-manifest.json",
                    digest=digest(evidence),
                )
                _completion_writer(root).complete(record.task_id, evidence=evidence_ref)
                manifest_path = run_dir / "integration-manifest.json"
                if manifest_path.exists():
                    manifest = _load_json_model(manifest_path, IntegrationManifest)
                else:
                    manifest = IntegrationManifest(
                        run_id=run_id,
                        task_id=record.task_id,
                        target_ref=plan.integration_target_ref,
                        base_commit=plan.base_commit,
                        candidate_commit=record.candidate_commit,
                        target_before=plan.base_commit,
                        target_after=record.candidate_commit,
                        evidence_manifest=evidence_ref.path,
                        evidence_digest=evidence_ref.digest,
                        task_completed=True,
                        worktree_cleaned=False,
                        integrated_at=utc_now(),
                    )
                    _atomic_json(manifest_path, manifest)
                final = store.transition(
                    run_id,
                    expected={RunStatus.INTEGRATING},
                    status=RunStatus.PASSED,
                    candidate_commit=record.candidate_commit,
                )
                cleaned = _cleanup_verified_worktree(root, record=final, store=store)
                if cleaned and not manifest.worktree_cleaned:
                    manifest = manifest.model_copy(update={"worktree_cleaned": True})
                    _atomic_json(manifest_path, manifest)
                details.append("Integrated Git state reconciled; task completion and cleanup finalized.")
                return RecoveryAction(
                    run_id=run_id,
                    previous_status=previous.value,
                    resolved_status=RunStatus.PASSED.value,
                    action="finalized_integration",
                    details=details,
                )

            final = store.transition(
                run_id,
                expected={RunStatus.INTEGRATING},
                status=RunStatus.NEEDS_DECISION,
                terminal_reason=RunTerminalReason.STALE_BASE,
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
            RunStatus.PREPARING,
            RunStatus.CLAIMED,
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
