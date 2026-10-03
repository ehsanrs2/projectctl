from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from projectctl.application.execution import _actor
from projectctl.core.digest import digest
from projectctl.core.enums import (
    RunStatus,
    RunTerminalReason,
    VerificationCheckStatus,
    WorkerStrategyKind,
)
from projectctl.core.errors import RunStoreError, VerificationError, WorktreeError
from projectctl.core.time import utc_now
from projectctl.git import WorktreeManager, resolve_commit
from projectctl.schemas.evidence import EvidenceManifest
from projectctl.schemas.execution import ExecutionPlan, WorkerResult
from projectctl.schemas.run_store import RunRecord
from projectctl.schemas.verification import (
    VerificationCheckResult,
    VerificationManifest,
    VerificationProfile,
)
from projectctl.storage.runs import RunStore
from projectctl.verification import (
    committed_diff_digest,
    inspect_workspace,
    resolve_verification_profile,
    run_verification_commands,
)


@dataclass(frozen=True)
class VerifiedRun:
    record: RunRecord
    verification: VerificationManifest
    evidence: EvidenceManifest


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


def _synthetic_check(
    check_id: str,
    *,
    passed: bool,
    duration_ms: int = 0,
) -> VerificationCheckResult:
    return VerificationCheckResult(
        id=check_id,
        argv=["projectctl", "internal", check_id],
        status=(
            VerificationCheckStatus.PASSED
            if passed
            else VerificationCheckStatus.FAILED
        ),
        exit_code=0 if passed else 1,
        duration_ms=duration_ms,
    )


def _skipped_check(command) -> VerificationCheckResult:
    return VerificationCheckResult(
        id=command.id,
        argv=command.argv,
        status=VerificationCheckStatus.SKIPPED,
        exit_code=None,
        duration_ms=0,
    )


def _required_commands_passed(
    profile: VerificationProfile,
    checks: list[VerificationCheckResult],
) -> bool:
    by_id = {check.id: check for check in checks}
    for command in profile.commands:
        if not command.required:
            continue
        result = by_id.get(command.id)
        if result is None or result.status != VerificationCheckStatus.PASSED:
            return False
    return True


def _git(
    worktree: Path,
    *args: str,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["git", "-C", str(worktree), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    if check and result.returncode != 0:
        message = (result.stderr or result.stdout or "git error").strip()
        raise VerificationError(f"git {' '.join(args)} failed: {message}")
    return result


def _create_candidate_commit(
    worktree: Path,
    *,
    base_commit: str,
    task_id: str,
    run_id: str,
) -> str:
    _git(worktree, "add", "-A", "--")
    staged = _git(worktree, "diff", "--cached", "--quiet", base_commit, "--", check=False)
    if staged.returncode == 0:
        raise VerificationError("No staged change exists for candidate commit.")
    if staged.returncode not in (0, 1):
        raise VerificationError(
            (staged.stderr or staged.stdout or "git diff --cached failed").strip()
        )

    message = f"projectctl: candidate {task_id} [{run_id}]"
    _git(
        worktree,
        "-c",
        "user.name=ProjectCTL",
        "-c",
        "user.email=projectctl@localhost",
        "-c",
        "commit.gpgSign=false",
        "commit",
        "--no-verify",
        "-m",
        message,
    )
    candidate = resolve_commit(worktree, "HEAD")
    parents = _git(worktree, "rev-list", "--parents", "-n", "1", candidate).stdout.split()
    if len(parents) != 2 or parents[1] != base_commit:
        raise VerificationError(
            "Candidate commit is not a single-parent commit directly on the run base."
        )
    if _git(worktree, "status", "--porcelain").stdout.strip():
        raise VerificationError("Worktree is not clean after candidate commit creation.")
    return candidate


def _write_failure_evidence(
    run_dir: Path,
    *,
    run_id: str,
    task_id: str,
    base_commit: str,
    inspection,
    worker_result: WorkerResult,
    verification: VerificationManifest,
    profile_digest: str,
) -> EvidenceManifest:
    evidence = EvidenceManifest(
        run_id=run_id,
        task_id=task_id,
        base_commit=base_commit,
        candidate_commit=None,
        diff_digest=inspection.diff_digest,
        workspace_state_digest=inspection.state_digest,
        worker_result_digest=digest(worker_result),
        verification_manifest_digest=digest(verification),
        verification_profile_digest=profile_digest,
        changed_paths=inspection.changed_paths,
        overall_pass=False,
        generated_at=utc_now(),
    )
    _atomic_json(run_dir / "evidence-manifest.json", evidence)
    return evidence


def verify_run(project_root: Path, run_id: str) -> VerifiedRun:
    root = project_root.resolve()
    actor = _actor()
    store = RunStore(root)
    record = store.acquire_lease(run_id, owner=actor)
    run_dir = root / ".projectctl" / "runs" / run_id
    evidence_rel = f".projectctl/runs/{run_id}/evidence-manifest.json"

    try:
        if record.status != RunStatus.VERIFYING:
            raise RunStoreError(
                f"Run {run_id} cannot verify from status {record.status.value}; expected verifying."
            )

        plan = _load_json_model(run_dir / "execution-plan.json", ExecutionPlan)
        worker_result = _load_json_model(run_dir / "worker-result.json", WorkerResult)
        if worker_result.run_id != run_id or worker_result.task_id != plan.task_id:
            raise RunStoreError("WorkerResult identity does not match the run.")
        if digest(plan) != record.execution_plan_digest:
            raise RunStoreError("ExecutionPlan digest no longer matches the run record.")

        manager = WorktreeManager(root)
        expected_worktree = manager.path_for(record.worktree_id)
        worktree = Path(record.worktree_path).resolve()
        if worktree != expected_worktree or not worktree.exists():
            raise WorktreeError("Verification worktree is missing or outside expected storage.")
        if resolve_commit(worktree, "HEAD") != plan.base_commit:
            raise VerificationError(
                "Verification requires worker HEAD to remain at the execution base."
            )

        resolved = resolve_verification_profile(root, plan.verification_profile)
        _atomic_json(
            run_dir / "verification-profile.json",
            {
                "source": resolved.source,
                "profile_digest": resolved.profile_digest,
                "profile": resolved.profile.model_dump(mode="json"),
            },
        )

        started_at = utc_now()
        policy_start = time.monotonic()
        before = inspect_workspace(
            worktree,
            policy=resolved.profile.diff_policy,
            strategy=plan.strategy,
        )
        policy_ms = max(0, int((time.monotonic() - policy_start) * 1000))
        checks: list[VerificationCheckResult] = [
            _synthetic_check(
                "diff-policy",
                passed=not before.violations,
                duration_ms=policy_ms,
            )
        ]

        if before.violations:
            checks.extend(_skipped_check(command) for command in resolved.profile.commands)
            verification = VerificationManifest(
                run_id=run_id,
                task_id=plan.task_id,
                base_commit=plan.base_commit,
                workspace_state_digest=before.state_digest,
                profile=resolved.profile.id,
                profile_digest=resolved.profile_digest,
                changed_paths=before.changed_paths,
                policy_violations=before.violations,
                started_at=started_at,
                completed_at=utc_now(),
                checks=checks,
                overall_pass=False,
            )
            _atomic_json(run_dir / "verification-manifest.json", verification)
            evidence = _write_failure_evidence(
                run_dir,
                run_id=run_id,
                task_id=plan.task_id,
                base_commit=plan.base_commit,
                inspection=before,
                worker_result=worker_result,
                verification=verification,
                profile_digest=resolved.profile_digest,
            )
            store.append_event(
                run_id,
                "verification.policy_blocked",
                {
                    "violations": before.violations,
                    "verification_manifest_digest": digest(verification),
                    "evidence_manifest_digest": digest(evidence),
                },
            )
            final = store.transition(
                run_id,
                expected={RunStatus.VERIFYING},
                status=RunStatus.BLOCKED_POLICY,
                terminal_reason=RunTerminalReason.POLICY_BLOCKED,
                evidence_manifest=evidence_rel,
            )
            return VerifiedRun(final, verification, evidence)

        checks.extend(
            run_verification_commands(
                worktree,
                run_dir=run_dir,
                run_id=run_id,
                profile=resolved.profile,
            )
        )

        after = inspect_workspace(
            worktree,
            policy=resolved.profile.diff_policy,
            strategy=plan.strategy,
        )
        stable = (
            before.state_digest == after.state_digest
            and before.changed_paths == after.changed_paths
            and resolve_commit(worktree, "HEAD") == plan.base_commit
        )
        checks.append(_synthetic_check("workspace-stability", passed=stable))

        command_pass = _required_commands_passed(resolved.profile, checks)
        overall = stable and command_pass and not after.violations

        verification = VerificationManifest(
            run_id=run_id,
            task_id=plan.task_id,
            base_commit=plan.base_commit,
            workspace_state_digest=after.state_digest,
            profile=resolved.profile.id,
            profile_digest=resolved.profile_digest,
            changed_paths=after.changed_paths,
            policy_violations=after.violations,
            started_at=started_at,
            completed_at=utc_now(),
            checks=checks,
            overall_pass=overall,
        )
        _atomic_json(run_dir / "verification-manifest.json", verification)

        if not overall:
            evidence = _write_failure_evidence(
                run_dir,
                run_id=run_id,
                task_id=plan.task_id,
                base_commit=plan.base_commit,
                inspection=after,
                worker_result=worker_result,
                verification=verification,
                profile_digest=resolved.profile_digest,
            )
            store.append_event(
                run_id,
                "verification.failed",
                {
                    "verification_manifest_digest": digest(verification),
                    "evidence_manifest_digest": digest(evidence),
                },
            )
            final = store.transition(
                run_id,
                expected={RunStatus.VERIFYING},
                status=RunStatus.FAILED,
                terminal_reason=RunTerminalReason.VERIFICATION_FAILED,
                evidence_manifest=evidence_rel,
            )
            return VerifiedRun(final, verification, evidence)

        if plan.strategy == WorkerStrategyKind.REVIEW:
            candidate = plan.base_commit
            diff_digest = after.diff_digest
        else:
            try:
                candidate = _create_candidate_commit(
                    worktree,
                    base_commit=plan.base_commit,
                    task_id=plan.task_id,
                    run_id=run_id,
                )
            except Exception:
                evidence = _write_failure_evidence(
                    run_dir,
                    run_id=run_id,
                    task_id=plan.task_id,
                    base_commit=plan.base_commit,
                    inspection=after,
                    worker_result=worker_result,
                    verification=verification,
                    profile_digest=resolved.profile_digest,
                )
                store.transition(
                    run_id,
                    expected={RunStatus.VERIFYING},
                    status=RunStatus.FAILED,
                    terminal_reason=RunTerminalReason.INFRASTRUCTURE_ERROR,
                    evidence_manifest=evidence_rel,
                )
                raise
            diff_digest = committed_diff_digest(
                worktree,
                plan.base_commit,
                candidate,
            )

        evidence = EvidenceManifest(
            run_id=run_id,
            task_id=plan.task_id,
            base_commit=plan.base_commit,
            candidate_commit=candidate,
            diff_digest=diff_digest,
            workspace_state_digest=after.state_digest,
            worker_result_digest=digest(worker_result),
            verification_manifest_digest=digest(verification),
            verification_profile_digest=resolved.profile_digest,
            changed_paths=after.changed_paths,
            overall_pass=True,
            generated_at=utc_now(),
        )
        _atomic_json(run_dir / "evidence-manifest.json", evidence)
        store.append_event(
            run_id,
            "verification.passed",
            {
                "candidate_commit": candidate,
                "verification_manifest_digest": digest(verification),
                "evidence_manifest_digest": digest(evidence),
            },
        )

        target_status = (
            RunStatus.PASSED
            if plan.strategy == WorkerStrategyKind.REVIEW
            else RunStatus.READY_TO_INTEGRATE
        )
        final = store.transition(
            run_id,
            expected={RunStatus.VERIFYING},
            status=target_status,
            candidate_commit=candidate,
            evidence_manifest=evidence_rel,
        )
        return VerifiedRun(final, verification, evidence)
    finally:
        try:
            store.release_lease(run_id, owner=actor)
        except Exception:
            pass
