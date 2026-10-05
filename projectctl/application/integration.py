from __future__ import annotations

import json
import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from projectctl.application.claims import load_durable_claim, record_claim_release
from projectctl.application.execution import _actor
from projectctl.application.publication import (
    load_publication_manifest,
    load_publication_request,
    persist_publication_manifest,
    persist_publication_request,
    publication_manifest_ref,
)
from projectctl.application.review_delivery import (
    load_review_receipt,
    load_review_request,
    persist_review_receipt,
    persist_review_request,
    review_receipt_ref,
    review_request_ref,
)
from projectctl.application.task_lifecycle import (
    reconcile_terminal_task,
    release_task_for_retry,
)
from projectctl.core.digest import digest
from projectctl.core.enums import RunStatus, RunTerminalReason
from projectctl.core.errors import (
    ClaimConflictError,
    IntegrationError,
    ProjectCtlError,
    RunStoreError,
    WorktreeError,
)
from projectctl.core.time import utc_now
from projectctl.git import WorktreeManager, current_branch, resolve_commit
from projectctl.git.review import ReviewGitTransport, review_source_branch
from projectctl.integrations.delivery import (
    code_delivery_policy,
    resolve_code_delivery,
)
from projectctl.integrations.execution_ownership import (
    execution_ownership_policy,
    resolve_execution_ownership,
)
from projectctl.integrations.task_authority import resolve_task_authority
from projectctl.project.loader import load_project_config
from projectctl.project.locking import project_lock
from projectctl.schemas.delivery import (
    PublicationManifest,
    PublicationRequest,
    ReviewReceipt,
    ReviewRequest,
)
from projectctl.schemas.evidence import EvidenceManifest
from projectctl.schemas.execution import EvidenceReference, ExecutionPlan, WorkerResult
from projectctl.schemas.integration import IntegrationManifest
from projectctl.schemas.run_store import RunRecord
from projectctl.schemas.verification import VerificationManifest
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
    actor: str,
    reason: str,
) -> RunRecord:
    final = store.transition(
        record.run_id,
        expected={current_status},
        status=RunStatus.NEEDS_DECISION,
        terminal_reason=RunTerminalReason.STALE_BASE,
    )
    try:
        _completion_writer(store.project_root).mark_needs_decision(
            record.task_id,
            reason=reason,
        )
        ownership = execution_ownership_policy(store.project_root)
        if ownership.strategy != "task_native":
            release_task_for_retry(
                store.project_root,
                store=store,
                run_id=record.run_id,
                actor=actor,
            )
        store.append_event(
            record.run_id,
            "task.reconciled",
            {"action": "blocked", "run_status": final.status.value},
        )
        return store.get(record.run_id)
    except Exception as exc:
        store.append_event(
            record.run_id,
            "task.reconcile_failed",
            {"run_status": final.status.value, "error": str(exc)},
        )
        store.transition(
            record.run_id,
            expected={RunStatus.NEEDS_DECISION},
            status=RunStatus.NEEDS_DECISION,
            terminal_reason=RunTerminalReason.RECOVERY_UNSAFE,
        )
        return store.get(record.run_id)


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


def _completion_event_matches(
    store: RunStore,
    run_id: str,
    *,
    evidence: EvidenceReference,
) -> bool:
    for event in reversed(store.events(run_id)):
        if event.event_type != "task.completion.observed":
            continue
        return (
            event.payload.get("evidence_path") == evidence.path
            and event.payload.get("evidence_digest") == evidence.digest
        )
    return False


def _publication_request(
    root: Path,
    *,
    store: RunStore,
    record: RunRecord,
    plan: ExecutionPlan,
    evidence: EvidenceManifest,
    provider: str,
    remote_name: str,
    repository: str | None,
) -> PublicationRequest:
    existing = load_publication_request(
        root,
        store=store,
        run_id=record.run_id,
        allow_missing=True,
    )
    evidence_path = f".projectctl/runs/{record.run_id}/evidence-manifest.json"
    evidence_digest = digest(evidence)
    if existing is not None:
        expected = {
            "task_id": record.task_id,
            "provider": provider,
            "repository": repository,
            "remote_name": remote_name,
            "target_ref": plan.integration_target_ref,
            "base_commit": plan.base_commit,
            "candidate_commit": record.candidate_commit,
            "evidence_manifest": evidence_path,
            "evidence_digest": evidence_digest,
        }
        for field, value in expected.items():
            if getattr(existing, field) != value:
                raise IntegrationError(
                    f"Durable publication request field {field!r} changed after creation."
                )
        return existing

    request = PublicationRequest(
        run_id=record.run_id,
        task_id=record.task_id,
        provider=provider,
        repository=repository,
        remote_name=remote_name,
        target_ref=plan.integration_target_ref,
        base_commit=plan.base_commit,
        candidate_commit=record.candidate_commit,
        evidence_manifest=evidence_path,
        evidence_digest=evidence_digest,
        requested_at=utc_now(),
    )
    persist_publication_request(root, store=store, request=request)
    return request


def _review_request(
    root: Path,
    *,
    store: RunStore,
    record: RunRecord,
    plan: ExecutionPlan,
    evidence: EvidenceManifest,
    task_provider: str,
    review_provider: str,
    remote_name: str,
    remote_identity: str,
) -> ReviewRequest:
    existing = load_review_request(
        root,
        store=store,
        run_id=record.run_id,
        allow_missing=True,
    )
    evidence_path = f".projectctl/runs/{record.run_id}/evidence-manifest.json"
    evidence_digest = digest(evidence)
    source_ref = review_source_branch(record.run_id, record.candidate_commit)
    title = f"ProjectCTL: {record.task_id}"
    body = (
        "ProjectCTL verified candidate awaiting repository review.\n\n"
        f"- Task: {record.task_id}\n"
        f"- Run: {record.run_id}\n"
        f"- Candidate: {record.candidate_commit}\n"
        f"- Evidence digest: {evidence_digest}\n\n"
        "ProjectCTL will not merge this review automatically."
    )

    if existing is not None:
        expected = {
            "task_id": record.task_id,
            "task_provider": task_provider,
            "review_provider": review_provider,
            "remote_name": remote_name,
            "remote_identity": remote_identity,
            "source_ref": source_ref,
            "target_ref": plan.integration_target_ref,
            "base_commit": plan.base_commit,
            "candidate_commit": record.candidate_commit,
            "evidence_manifest": evidence_path,
            "evidence_digest": evidence_digest,
            "title": title,
            "body": body,
        }
        for field, value in expected.items():
            if getattr(existing, field) != value:
                raise IntegrationError(
                    f"Durable review request field {field!r} changed after creation."
                )
        return existing

    request = ReviewRequest(
        run_id=record.run_id,
        task_id=record.task_id,
        task_provider=task_provider,
        review_provider=review_provider,
        remote_name=remote_name,
        remote_identity=remote_identity,
        source_ref=source_ref,
        target_ref=plan.integration_target_ref,
        base_commit=plan.base_commit,
        candidate_commit=record.candidate_commit,
        evidence_manifest=evidence_path,
        evidence_digest=evidence_digest,
        title=title,
        body=body,
        requested_at=utc_now(),
    )
    persist_review_request(root, store=store, request=request)
    return request


def _ensure_review_delivery(
    root: Path,
    *,
    store: RunStore,
    record: RunRecord,
    plan: ExecutionPlan,
    evidence: EvidenceManifest,
    actor: str,
) -> tuple[ReviewRequest, ReviewReceipt]:
    delivery = resolve_code_delivery(root)
    policy = delivery.policy
    if (
        policy.mode != "review_required"
        or not policy.supported
        or policy.review_provider is None
        or delivery.reviewer is None
    ):
        raise IntegrationError(
            "Review-required delivery has no supported runtime review adapter."
        )
    if not policy.remote_name or not policy.remote_identity:
        raise IntegrationError(
            "Review-required delivery has no pinned Git remote."
        )

    authority = resolve_task_authority(root)
    durable_claim = load_durable_claim(
        root,
        store=store,
        run_id=record.run_id,
    )
    assert durable_claim is not None
    _, claim = durable_claim
    claimer = resolve_execution_ownership(
        root,
        task_authority=authority,
    ).claimer

    completion_already_recorded = any(
        event.event_type == "task.completion.observed"
        for event in store.events(record.run_id)
    )
    if not completion_already_recorded and not claimer.validate(claim):
        final = store.transition(
            record.run_id,
            expected={record.status},
            status=RunStatus.NEEDS_DECISION,
            terminal_reason=RunTerminalReason.CLAIM_LOST,
        )
        reconcile_terminal_task(
            root,
            store=store,
            run_id=final.run_id,
            actor=actor,
        )
        raise IntegrationError(
            "Task claim ownership was lost before review delivery completed."
        )

    request = _review_request(
        root,
        store=store,
        record=record,
        plan=plan,
        evidence=evidence,
        task_provider=authority.provider,
        review_provider=policy.review_provider,
        remote_name=policy.remote_name,
        remote_identity=policy.remote_identity,
    )
    reviewer = delivery.reviewer
    observed = reviewer.reconcile(request)
    if observed.state == "missing":
        observed = reviewer.request_review(request)
    persist_review_receipt(
        root,
        store=store,
        request=request,
        receipt=observed,
    )

    if observed.state == "closed":
        final = store.transition(
            record.run_id,
            expected={record.status},
            status=RunStatus.NEEDS_DECISION,
            terminal_reason=RunTerminalReason.POLICY_BLOCKED,
        )
        reconcile_terminal_task(
            root,
            store=store,
            run_id=final.run_id,
            actor=actor,
        )
        raise IntegrationError(
            observed.reason or "Review was closed without merge."
        )

    if observed.state != "merged":
        return request, observed

    transport = ReviewGitTransport(
        root,
        remote_name=policy.remote_name,
        remote_identity=policy.remote_identity,
    )
    try:
        target_commit = transport.sync_merged_target(request, observed)
    except IntegrationError as exc:
        final = store.transition(
            record.run_id,
            expected={record.status},
            status=RunStatus.NEEDS_DECISION,
            terminal_reason=RunTerminalReason.RECOVERY_UNSAFE,
        )
        reconcile_terminal_task(
            root,
            store=store,
            run_id=final.run_id,
            actor=actor,
        )
        raise IntegrationError(
            "Merged review cannot be proven as an exact-base ancestry-preserving "
            f"delivery: {exc}"
        ) from exc

    completed = observed.model_copy(
        update={
            "target_commit": target_commit,
            "delivery_complete": True,
            "observed_at": utc_now(),
            "reason": None,
        }
    )
    persist_review_receipt(
        root,
        store=store,
        request=request,
        receipt=completed,
    )
    return request, completed


def _ensure_publication(
    root: Path,
    *,
    store: RunStore,
    record: RunRecord,
    plan: ExecutionPlan,
    evidence: EvidenceManifest,
    actor: str,
):
    delivery = resolve_code_delivery(root)
    policy = delivery.policy
    if not policy.publication_required:
        return None
    if not policy.supported or delivery.publisher is None:
        raise IntegrationError(
            f"Code delivery mode {policy.mode!r} has no supported publication adapter."
        )
    authority = resolve_task_authority(root)

    durable_claim = load_durable_claim(
        root,
        store=store,
        run_id=record.run_id,
    )
    assert durable_claim is not None
    _, claim = durable_claim
    claimer = resolve_execution_ownership(
        root,
        task_authority=authority,
    ).claimer

    completion_already_recorded = any(
        event.event_type == "task.completion.observed"
        for event in store.events(record.run_id)
    )
    if not completion_already_recorded and not claimer.validate(claim):
        final = store.transition(
            record.run_id,
            expected={RunStatus.INTEGRATING},
            status=RunStatus.NEEDS_DECISION,
            terminal_reason=RunTerminalReason.CLAIM_LOST,
        )
        reconcile_terminal_task(
            root,
            store=store,
            run_id=final.run_id,
            actor=actor,
        )
        raise IntegrationError(
            "Task claim ownership was lost before remote publication."
        )

    remote_name = policy.remote_name
    if not remote_name or not policy.remote_identity:
        raise IntegrationError(
            "Code delivery requires publication but has no pinned publication remote."
        )
    request = _publication_request(
        root,
        store=store,
        record=record,
        plan=plan,
        evidence=evidence,
        provider=authority.provider,
        remote_name=remote_name,
        repository=claim.repository or policy.remote_identity,
    )
    publisher = delivery.publisher

    durable_publication = load_publication_manifest(
        root,
        store=store,
        run_id=record.run_id,
        allow_missing=True,
    )
    if durable_publication is not None:
        _, previous = durable_publication
        if previous.published and previous.remote_after == record.candidate_commit:
            observed = publisher.reconcile(request)
            if observed.published and observed.remote_after == record.candidate_commit:
                persist_publication_manifest(
                    root,
                    store=store,
                    request=request,
                    manifest=observed,
                )
                return observed

    observed = publisher.reconcile(request)
    if not observed.published:
        if observed.remote_after == plan.base_commit:
            observed = publisher.publish(request)
        elif observed.remote_after != record.candidate_commit:
            final = store.transition(
                record.run_id,
                expected={RunStatus.INTEGRATING},
                status=RunStatus.NEEDS_DECISION,
                terminal_reason=RunTerminalReason.STALE_BASE,
            )
            reconcile_terminal_task(
                root,
                store=store,
                run_id=final.run_id,
                actor=actor,
            )
            raise IntegrationError(
                observed.reason or "Remote publication target diverged."
            )

    persist_publication_manifest(
        root,
        store=store,
        request=request,
        manifest=observed,
    )
    if not observed.published or observed.remote_after != record.candidate_commit:
        raise IntegrationError(
            observed.reason or "Remote publication could not be proven."
        )
    return observed


def _finalize_delivery(
    root: Path,
    *,
    store: RunStore,
    record: RunRecord,
    plan: ExecutionPlan,
    evidence: EvidenceManifest,
    target_before: str,
    actor: str,
) -> IntegratedRun:
    policy = code_delivery_policy(root)
    task_provider = load_project_config(root).task_store.provider
    run_dir = root / ".projectctl" / "runs" / record.run_id

    target_after = resolve_commit(root, plan.integration_target_ref)
    publication = None
    review_request = None
    review_receipt = None

    publication_path = None
    publication_digest = None
    review_request_path = None
    review_request_digest = None
    review_receipt_path = None
    review_receipt_digest = None

    if policy.mode == "review_required":
        durable_review = load_review_receipt(
            root,
            store=store,
            run_id=record.run_id,
            allow_missing=True,
        )
        if target_after != record.candidate_commit:
            if durable_review is None:
                raise IntegrationError(
                    "Local integration target changed before durable review delivery proof existed."
                )
            _, previous_receipt = durable_review
            if (
                not previous_receipt.delivery_complete
                or previous_receipt.target_commit != target_after
            ):
                raise IntegrationError(
                    "Local integration target differs from the verified candidate "
                    "without matching completed review evidence."
                )

        review_request, review_receipt = _ensure_review_delivery(
            root,
            store=store,
            record=record,
            plan=plan,
            evidence=evidence,
            actor=actor,
        )
        review_request_path = review_request_ref(record.run_id)
        review_request_digest = digest(review_request)
        review_receipt_path = review_receipt_ref(record.run_id)
        review_receipt_digest = digest(review_receipt)

        if not review_receipt.delivery_complete:
            if review_receipt.state != "open":
                raise IntegrationError(
                    review_receipt.reason
                    or f"Review delivery is not completable from state {review_receipt.state!r}."
                )
            target_after = resolve_commit(root, plan.integration_target_ref)
            if target_after != record.candidate_commit:
                raise IntegrationError(
                    "Pending review delivery must leave the local target at the exact candidate."
                )

            manifest = IntegrationManifest(
                run_id=record.run_id,
                task_id=record.task_id,
                target_ref=plan.integration_target_ref,
                base_commit=plan.base_commit,
                candidate_commit=record.candidate_commit,
                target_before=target_before,
                target_after=target_after,
                evidence_manifest=f".projectctl/runs/{record.run_id}/evidence-manifest.json",
                evidence_digest=digest(evidence),
                delivery_mode="review_required",
                publication_required=True,
                review_request=review_request_path,
                review_request_digest=review_request_digest,
                review_receipt=review_receipt_path,
                review_receipt_digest=review_receipt_digest,
                review_url=review_receipt.review_url,
                review_state=review_receipt.state,
                task_completed=False,
                claim_released=False,
                worktree_cleaned=False,
                integrated_at=utc_now(),
                completed_at=None,
            )
            _atomic_json(run_dir / "integration-manifest.json", manifest)
            store.append_event(
                record.run_id,
                "integration.awaiting_review",
                {
                    "review_provider": review_receipt.review_provider,
                    "review_id": review_receipt.review_id,
                    "review_url": review_receipt.review_url,
                    "review_request_digest": review_request_digest,
                    "review_receipt_digest": review_receipt_digest,
                    "candidate_commit": record.candidate_commit,
                },
            )
            current = store.get(record.run_id)
            if current.status == RunStatus.INTEGRATING:
                current = store.transition(
                    record.run_id,
                    expected={RunStatus.INTEGRATING},
                    status=RunStatus.AWAITING_REVIEW,
                    candidate_commit=record.candidate_commit,
                )
            elif current.status != RunStatus.AWAITING_REVIEW:
                raise IntegrationError(
                    f"Pending review cannot be recorded from run status {current.status.value!r}."
                )
            return IntegratedRun(record=current, manifest=manifest)

        target_after = resolve_commit(root, plan.integration_target_ref)
        if target_after != review_receipt.target_commit:
            raise IntegrationError(
                "Local target does not match completed review delivery proof."
            )
        completion_evidence = EvidenceReference(
            path=review_receipt_path,
            digest=review_receipt_digest,
        )

    else:
        if target_after != record.candidate_commit:
            raise IntegrationError("Integration target does not equal verified candidate.")

        publication = _ensure_publication(
            root,
            store=store,
            record=record,
            plan=plan,
            evidence=evidence,
            actor=actor,
        )

        if publication is None:
            completion_evidence = EvidenceReference(
                path=f".projectctl/runs/{record.run_id}/evidence-manifest.json",
                digest=digest(evidence),
            )
        else:
            publication_path = publication_manifest_ref(record.run_id)
            publication_digest = digest(publication)
            completion_evidence = EvidenceReference(
                path=publication_path,
                digest=publication_digest,
            )

    if not _completion_event_matches(
        store,
        record.run_id,
        evidence=completion_evidence,
    ):
        _completion_writer(root).complete(
            record.task_id,
            evidence=completion_evidence,
        )
        store.append_event(
            record.run_id,
            "task.completion.observed",
            {
                "evidence_path": completion_evidence.path,
                "evidence_digest": completion_evidence.digest,
                "provider": task_provider,
                "delivery_mode": policy.mode,
            },
        )

    claim_released = False
    ownership_policy = execution_ownership_policy(root)
    if ownership_policy.strategy != "task_native":
        durable_claim = load_durable_claim(
            root,
            store=store,
            run_id=record.run_id,
        )
        assert durable_claim is not None
        _, claim = durable_claim
        try:
            resolve_execution_ownership(
                root,
                task_authority=resolve_task_authority(root),
            ).claimer.release(claim)
            record_claim_release(store, claim)
            claim_released = True
        except ClaimConflictError as exc:
            store.append_event(
                record.run_id,
                "task.claim.ownership_lost_after_completion",
                {
                    "claim_digest": digest(claim),
                    "ownership_ref": claim.ownership_ref,
                    "ownership_sha": claim.ownership_sha,
                    "error": str(exc),
                },
            )
            claim_released = False
        except ProjectCtlError as exc:
            store.append_event(
                record.run_id,
                "task.claim.release_deferred_after_completion",
                {
                    "claim_digest": digest(claim),
                    "ownership_ref": claim.ownership_ref,
                    "ownership_sha": claim.ownership_sha,
                    "error": str(exc),
                },
            )
            raise IntegrationError(
                "Task completion is durable but exact claim release could not be proven."
            ) from exc

    manifest = IntegrationManifest(
        run_id=record.run_id,
        task_id=record.task_id,
        target_ref=plan.integration_target_ref,
        base_commit=plan.base_commit,
        candidate_commit=record.candidate_commit,
        target_before=target_before,
        target_after=target_after,
        evidence_manifest=f".projectctl/runs/{record.run_id}/evidence-manifest.json",
        evidence_digest=digest(evidence),
        delivery_mode=policy.mode,
        publication_required=policy.publication_required,
        publication_manifest=publication_path,
        publication_digest=publication_digest,
        review_request=review_request_path,
        review_request_digest=review_request_digest,
        review_receipt=review_receipt_path,
        review_receipt_digest=review_receipt_digest,
        review_url=review_receipt.review_url if review_receipt is not None else None,
        review_state=review_receipt.state if review_receipt is not None else None,
        task_completed=True,
        claim_released=claim_released,
        worktree_cleaned=False,
        integrated_at=utc_now(),
        completed_at=utc_now(),
    )
    _atomic_json(run_dir / "integration-manifest.json", manifest)
    store.append_event(
        record.run_id,
        "integration.applied",
        {
            "target_ref": plan.integration_target_ref,
            "candidate_commit": record.candidate_commit,
            "target_after": target_after,
            "evidence_digest": digest(evidence),
            "delivery_mode": policy.mode,
            "publication_digest": publication_digest,
            "review_receipt_digest": review_receipt_digest,
            "task_completed": True,
        },
    )

    final = store.transition(
        record.run_id,
        expected={RunStatus.INTEGRATING, RunStatus.AWAITING_REVIEW},
        status=RunStatus.PASSED,
        candidate_commit=record.candidate_commit,
    )

    cleaned = _cleanup_verified_worktree(root, record=final, store=store)
    if cleaned:
        manifest = manifest.model_copy(update={"worktree_cleaned": True})
        _atomic_json(run_dir / "integration-manifest.json", manifest)
    return IntegratedRun(record=store.get(record.run_id), manifest=manifest)


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
        _validate_verified_candidate(
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
                actor=actor,
                reason="Integration target advanced after verification.",
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

        return _finalize_delivery(
            root,
            store=store,
            record=current_record,
            plan=plan,
            evidence=evidence,
            target_before=target_before,
            actor=actor,
        )
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
    with project_lock(root, "integration"):
        return _integrate_run_locked(root, run_id)
