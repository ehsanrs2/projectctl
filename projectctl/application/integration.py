from __future__ import annotations

import json
import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from projectctl.application.execution import _actor
from projectctl.core.digest import digest
from projectctl.core.enums import RunStatus, RunTerminalReason
from projectctl.core.errors import (
    IntegrationError,
    ProjectCtlError,
    RunStoreError,
    WorktreeError,
)
from projectctl.core.time import utc_now
from projectctl.git import WorktreeManager, current_branch, resolve_commit
from projectctl.integrations.task_authority import resolve_task_authority
from projectctl.project.locking import project_lock
from projectctl.schemas.evidence import EvidenceManifest
from projectctl.schemas.execution import EvidenceReference, ExecutionPlan
from projectctl.schemas.integration import IntegrationManifest
from projectctl.schemas.run_store import RunRecord
from projectctl.schemas.verification import VerificationManifest
from projectctl.schemas.execution import WorkerResult
from projectctl.storage.runs import RunStore
from projectctl.verification.diff import committed_diff_digest


@dataclass(frozen=True)
class IntegratedRun:
    record: RunRecord
    manifest: IntegrationManifest


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
        return model.model_validate(json.loads(path.read_text(encoding="utf-8")))
    except Exception as exc:
        raise RunStoreError(f"Invalid run artifact {path.name}: {exc}") from exc


def _git(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    if check and result.returncode != 0:
        message = (result.stderr or result.stdout or "git error").strip()
        raise IntegrationError(f"git {' '.join(args)} failed: {message}")
    return result


def _repository_clean(root: Path) -> bool:
    return not _git(root, "status", "--porcelain").stdout.strip()


def _completion_writer(project_root: Path):
    try:
        return resolve_task_authority(project_root).require_completion_writer()
    except ProjectCtlError as exc:
        raise IntegrationError(
            f"Task completion authority is unavailable: {exc}"
        ) from exc


def _validate_verified_candidate(
    root: Path,
    record: RunRecord,
    plan: ExecutionPlan,
    evidence: EvidenceManifest,
    *,
    run_dir: Path,
) -> Path:
    if not evidence.overall_pass:
        raise IntegrationError("Integration requires passing evidence.")
    if evidence.run_id != record.run_id or evidence.task_id != record.task_id:
        raise IntegrationError("Evidence identity does not match run identity.")
    if evidence.base_commit != plan.base_commit:
        raise IntegrationError("Evidence base commit differs from ExecutionPlan.")
    if not record.candidate_commit or evidence.candidate_commit != record.candidate_commit:
        raise IntegrationError("Evidence candidate does not match durable run state.")

    worker_result = _load_json_model(run_dir / "worker-result.json", WorkerResult)
    verification = _load_json_model(
        run_dir / "verification-manifest.json", VerificationManifest
    )
    if digest(worker_result) != evidence.worker_result_digest:
        raise IntegrationError("WorkerResult digest no longer matches EvidenceManifest.")
    if digest(verification) != evidence.verification_manifest_digest:
        raise IntegrationError(
            "VerificationManifest digest no longer matches EvidenceManifest."
        )
    if not verification.overall_pass:
        raise IntegrationError("VerificationManifest no longer records a passing result.")
    if verification.profile_digest != evidence.verification_profile_digest:
        raise IntegrationError("Verification profile digest chain is inconsistent.")

    manager = WorktreeManager(root)
    expected = manager.path_for(record.worktree_id)
    worktree = Path(record.worktree_path).resolve()
    if worktree != expected or not worktree.exists():
        raise WorktreeError("Verified worktree is missing or outside expected storage.")
    if resolve_commit(worktree, "HEAD") != record.candidate_commit:
        raise IntegrationError("Verified worktree HEAD no longer matches candidate commit.")
    if _git(worktree, "status", "--porcelain").stdout.strip():
        raise IntegrationError("Verified worktree must be clean before integration.")

    parents = _git(
        worktree, "rev-list", "--parents", "-n", "1", record.candidate_commit
    ).stdout.split()
    if len(parents) != 2 or parents[1] != plan.base_commit:
        raise IntegrationError(
            "Candidate is no longer a single-parent commit directly on the verified base."
        )
    actual_diff = committed_diff_digest(
        worktree, plan.base_commit, record.candidate_commit
    )
    if actual_diff != evidence.diff_digest:
        raise IntegrationError("Candidate diff digest no longer matches EvidenceManifest.")
    return worktree


def _mark_stale_target(
    store: RunStore,
    record: RunRecord,
    *,
    current_status: RunStatus,
) -> RunRecord:
    writer = _completion_writer(store.project_root)
    try:
        writer.mark_needs_decision(
            record.task_id,
            reason="Integration target advanced after verification.",
        )
    except Exception:
        pass
    return store.transition(
        record.run_id,
        expected={current_status},
        status=RunStatus.NEEDS_DECISION,
        terminal_reason=RunTerminalReason.STALE_BASE,
    )


def _cleanup_verified_worktree(
    root: Path,
    *,
    record: RunRecord,
    store: RunStore,
) -> bool:
    manager = WorktreeManager(root)
    try:
        manager.remove(
            worktree_id=record.worktree_id,
            branch_name=record.branch_name,
            force=True,
        )
        store.append_event(record.run_id, "integration.cleanup", {"success": True})
        return True
    except Exception as exc:
        store.append_event(
            record.run_id,
            "integration.cleanup",
            {"success": False, "error": str(exc)},
        )
        return False


def _integrate_run_locked(project_root: Path, run_id: str) -> IntegratedRun:
    root = project_root.resolve()
    actor = _actor()
    store = RunStore(root)
    record = store.acquire_lease(run_id, owner=actor)
    run_dir = root / ".projectctl" / "runs" / run_id

    try:
        if record.status != RunStatus.READY_TO_INTEGRATE:
            raise RunStoreError(
                f"Run {run_id} cannot integrate from status {record.status.value}; "
                "expected ready_to_integrate."
            )

        plan = _load_json_model(run_dir / "execution-plan.json", ExecutionPlan)
        evidence = _load_json_model(run_dir / "evidence-manifest.json", EvidenceManifest)
        worktree = _validate_verified_candidate(
            root, record, plan, evidence, run_dir=run_dir
        )

        if current_branch(root) != plan.integration_target_ref:
            raise IntegrationError(
                f"Primary worktree must have integration target "
                f"{plan.integration_target_ref!r} checked out."
            )
        if not _repository_clean(root):
            raise IntegrationError(
                "Primary worktree has uncommitted changes; integration is fail-closed."
            )

        target_before = resolve_commit(root, plan.integration_target_ref)
        if target_before == record.candidate_commit:
            pass
        elif target_before != plan.base_commit:
            _mark_stale_target(
                store,
                record,
                current_status=RunStatus.READY_TO_INTEGRATE,
            )
            raise IntegrationError(
                "Integration target advanced after verification. Re-run on the new base."
            )
        else:
            store.transition(
                run_id,
                expected={RunStatus.READY_TO_INTEGRATE},
                status=RunStatus.INTEGRATING,
            )
            record = store.get(run_id)
            _git(root, "merge", "--ff-only", record.candidate_commit)
            target_after_merge = resolve_commit(root, plan.integration_target_ref)
            if target_after_merge != record.candidate_commit:
                raise IntegrationError(
                    "Fast-forward integration completed without reaching the candidate commit."
                )

        current_record = store.get(run_id)
        if current_record.status == RunStatus.READY_TO_INTEGRATE:
            store.transition(
                run_id,
                expected={RunStatus.READY_TO_INTEGRATE},
                status=RunStatus.INTEGRATING,
            )
            current_record = store.get(run_id)

        target_after = resolve_commit(root, plan.integration_target_ref)
        if target_after != current_record.candidate_commit:
            raise IntegrationError("Integration target does not equal verified candidate.")

        evidence_ref = EvidenceReference(
            path=f".projectctl/runs/{run_id}/evidence-manifest.json",
            digest=digest(evidence),
        )
        _completion_writer(root).complete(current_record.task_id, evidence=evidence_ref)

        manifest = IntegrationManifest(
            run_id=run_id,
            task_id=current_record.task_id,
            target_ref=plan.integration_target_ref,
            base_commit=plan.base_commit,
            candidate_commit=current_record.candidate_commit,
            target_before=target_before,
            target_after=target_after,
            evidence_manifest=evidence_ref.path,
            evidence_digest=evidence_ref.digest,
            task_completed=True,
            worktree_cleaned=False,
            integrated_at=utc_now(),
        )
        _atomic_json(run_dir / "integration-manifest.json", manifest)
        store.append_event(
            run_id,
            "integration.applied",
            {
                "target_ref": plan.integration_target_ref,
                "candidate_commit": current_record.candidate_commit,
                "evidence_digest": evidence_ref.digest,
            },
        )

        final = store.transition(
            run_id,
            expected={RunStatus.INTEGRATING},
            status=RunStatus.PASSED,
            candidate_commit=current_record.candidate_commit,
        )

        cleaned = _cleanup_verified_worktree(root, record=final, store=store)
        if cleaned:
            manifest = manifest.model_copy(update={"worktree_cleaned": True})
            _atomic_json(run_dir / "integration-manifest.json", manifest)
        return IntegratedRun(record=store.get(run_id), manifest=manifest)
    except IntegrationError:
        raise
    except Exception as exc:
        current_record = store.get(run_id)
        if current_record.status == RunStatus.INTEGRATING:
            try:
                plan = _load_json_model(run_dir / "execution-plan.json", ExecutionPlan)
                target = resolve_commit(root, plan.integration_target_ref)
            except Exception:
                target = None
            if target != current_record.candidate_commit:
                try:
                    store.transition(
                        run_id,
                        expected={RunStatus.INTEGRATING},
                        status=RunStatus.NEEDS_DECISION,
                        terminal_reason=RunTerminalReason.INTEGRATION_CONFLICT,
                    )
                except Exception:
                    pass
        raise IntegrationError(f"Integration failed: {exc}") from exc
    finally:
        try:
            store.release_lease(run_id, owner=actor)
        except Exception:
            pass



def integrate_run(project_root: Path, run_id: str) -> IntegratedRun:
    root = project_root.resolve()
    # Git target mutation is project-global, not merely run-local. Serialize all
    # integrations even when they belong to different tasks/runs.
    with project_lock(root, "integration"):
        return _integrate_run_locked(root, run_id)
