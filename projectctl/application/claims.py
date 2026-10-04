from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from projectctl.core.digest import digest
from projectctl.core.errors import RunStoreError
from projectctl.schemas.task_claim import TaskClaim, TaskClaimRequest
from projectctl.storage.runs import RunStore


def _atomic_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(
        value.model_dump(mode="json"),
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


def claim_request_ref(run_id: str) -> str:
    return f".projectctl/runs/{run_id}/task-claim-request.json"


def claim_ref(run_id: str) -> str:
    return f".projectctl/runs/{run_id}/task-claim.json"


def persist_claim_request(
    project_root: Path,
    *,
    store: RunStore,
    request: TaskClaimRequest,
) -> None:
    ref = claim_request_ref(request.run_id)
    request_digest = digest(request)
    _atomic_json(project_root / ref, request)
    store.append_event(
        request.run_id,
        "task.claim.requested",
        {
            "claim_request_ref": ref,
            "claim_request_digest": request_digest,
            "task_id": request.task_id,
        },
    )


def persist_claim(
    project_root: Path,
    *,
    store: RunStore,
    request: TaskClaimRequest,
    claim: TaskClaim,
) -> None:
    if claim.run_id != request.run_id or claim.task_id != request.task_id:
        raise RunStoreError("Task claim identity does not match its request.")
    if claim.request_digest != digest(request):
        raise RunStoreError("Task claim request digest does not match durable request.")

    ref = claim_ref(request.run_id)
    claim_digest = digest(claim)
    _atomic_json(project_root / ref, claim)
    store.append_event(
        request.run_id,
        "task.claim.observed",
        {
            "claim_ref": ref,
            "claim_digest": claim_digest,
            "claim_request_digest": claim.request_digest,
            "acquired": claim.acquired,
            "provider": claim.provider,
            "ownership_ref": claim.ownership_ref,
            "ownership_sha": claim.ownership_sha,
        },
    )


def _anchored(
    store: RunStore,
    run_id: str,
    *,
    event_type: str,
    ref_key: str,
    ref_value: str,
    digest_key: str,
    digest_value: str,
) -> bool:
    for event in reversed(store.events(run_id)):
        if event.event_type != event_type:
            continue
        if event.payload.get(ref_key) != ref_value:
            continue
        return event.payload.get(digest_key) == digest_value
    return False


def load_durable_claim_request(
    project_root: Path,
    *,
    store: RunStore,
    run_id: str,
    allow_missing: bool = False,
) -> TaskClaimRequest | None:
    request_path = project_root / claim_request_ref(run_id)
    if not request_path.exists():
        if allow_missing:
            return None
        raise RunStoreError(
            f"Run {run_id} is missing durable task claim request evidence."
        )
    try:
        request = TaskClaimRequest.model_validate(
            json.loads(request_path.read_text(encoding="utf-8"))
        )
    except Exception as exc:
        raise RunStoreError(
            f"Run {run_id} task claim request evidence is invalid: {exc}"
        ) from exc
    if request.run_id != run_id:
        raise RunStoreError("Task claim request run identity does not match durable run.")
    request_digest = digest(request)
    if not _anchored(
        store,
        run_id,
        event_type="task.claim.requested",
        ref_key="claim_request_ref",
        ref_value=claim_request_ref(run_id),
        digest_key="claim_request_digest",
        digest_value=request_digest,
    ):
        raise RunStoreError("Task claim request is not anchored in durable run events.")
    return request


def load_durable_claim(
    project_root: Path,
    *,
    store: RunStore,
    run_id: str,
    allow_legacy_missing: bool = False,
    require_acquired: bool = True,
) -> tuple[TaskClaimRequest, TaskClaim] | None:
    request_path = project_root / claim_request_ref(run_id)
    claim_path = project_root / claim_ref(run_id)
    request_exists = request_path.exists()
    claim_exists = claim_path.exists()
    if not request_exists and not claim_exists and allow_legacy_missing:
        return None
    if not request_exists or not claim_exists:
        raise RunStoreError(
            f"Run {run_id} has incomplete durable task claim evidence."
        )

    request = load_durable_claim_request(
        project_root,
        store=store,
        run_id=run_id,
    )
    assert request is not None
    try:
        claim = TaskClaim.model_validate(
            json.loads(claim_path.read_text(encoding="utf-8"))
        )
    except Exception as exc:
        raise RunStoreError(
            f"Run {run_id} task claim evidence is invalid: {exc}"
        ) from exc

    if claim.run_id != run_id or claim.task_id != request.task_id:
        raise RunStoreError("Task claim identity does not match durable request/run.")
    claim_digest = digest(claim)
    if claim.request_digest != digest(request):
        raise RunStoreError("Task claim no longer matches its durable request.")
    if not _anchored(
        store,
        run_id,
        event_type="task.claim.observed",
        ref_key="claim_ref",
        ref_value=claim_ref(run_id),
        digest_key="claim_digest",
        digest_value=claim_digest,
    ):
        raise RunStoreError("Task claim is not anchored in durable run events.")
    if require_acquired and not claim.acquired:
        raise RunStoreError("Durable task claim evidence does not record acquisition.")
    return request, claim


def record_claim_release(
    store: RunStore,
    claim: TaskClaim,
) -> None:
    store.append_event(
        claim.run_id,
        "task.claim.released",
        {
            "claim_digest": digest(claim),
            "provider": claim.provider,
            "ownership_ref": claim.ownership_ref,
            "ownership_sha": claim.ownership_sha,
        },
    )
