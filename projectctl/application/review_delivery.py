from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from projectctl.core.digest import digest
from projectctl.core.errors import RunStoreError
from projectctl.schemas.delivery import ReviewReceipt, ReviewRequest
from projectctl.storage.runs import RunStore


def _atomic_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(
        value.model_dump(mode="json"),
        indent=2,
        sort_keys=True,
        ensure_ascii=False,
    ) + "\n"
    fd, tmp_name = tempfile.mkstemp(
        prefix=".projectctl-",
        suffix=".json",
        dir=path.parent,
    )
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


def review_request_ref(run_id: str) -> str:
    return f".projectctl/runs/{run_id}/review-request.json"


def review_receipt_ref(run_id: str) -> str:
    return f".projectctl/runs/{run_id}/review-receipt.json"


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


def persist_review_request(
    project_root: Path,
    *,
    store: RunStore,
    request: ReviewRequest,
) -> None:
    ref = review_request_ref(request.run_id)
    request_digest = digest(request)
    path = project_root / ref
    if path.exists():
        try:
            existing = ReviewRequest.model_validate(
                json.loads(path.read_text(encoding="utf-8"))
            )
        except Exception as exc:
            raise RunStoreError(
                f"Existing review request is invalid: {exc}"
            ) from exc
        if digest(existing) != request_digest:
            raise RunStoreError(
                "Review request identity changed after durable persistence."
            )
    else:
        _atomic_json(path, request)

    if not _anchored(
        store,
        request.run_id,
        event_type="review.requested",
        ref_key="review_request_ref",
        ref_value=ref,
        digest_key="review_request_digest",
        digest_value=request_digest,
    ):
        store.append_event(
            request.run_id,
            "review.requested",
            {
                "review_request_ref": ref,
                "review_request_digest": request_digest,
                "candidate_commit": request.candidate_commit,
                "source_ref": request.source_ref,
                "target_ref": request.target_ref,
                "review_provider": request.review_provider,
            },
        )


def persist_review_receipt(
    project_root: Path,
    *,
    store: RunStore,
    request: ReviewRequest,
    receipt: ReviewReceipt,
) -> None:
    if receipt.run_id != request.run_id or receipt.task_id != request.task_id:
        raise RunStoreError("Review receipt identity does not match request.")
    if receipt.request_digest != digest(request):
        raise RunStoreError("Review receipt request digest does not match.")
    if receipt.review_provider != request.review_provider:
        raise RunStoreError("Review receipt provider does not match request.")
    if receipt.source_ref != request.source_ref or receipt.target_ref != request.target_ref:
        raise RunStoreError("Review receipt refs do not match durable request.")
    if receipt.head_commit not in (None, request.candidate_commit):
        raise RunStoreError(
            "Review receipt head commit differs from verified candidate."
        )

    ref = review_receipt_ref(request.run_id)
    receipt_digest = digest(receipt)
    _atomic_json(project_root / ref, receipt)
    store.append_event(
        request.run_id,
        "review.observed",
        {
            "review_receipt_ref": ref,
            "review_receipt_digest": receipt_digest,
            "review_request_digest": receipt.request_digest,
            "review_provider": receipt.review_provider,
            "review_id": receipt.review_id,
            "review_url": receipt.review_url,
            "state": receipt.state,
            "delivery_complete": receipt.delivery_complete,
            "head_commit": receipt.head_commit,
            "target_commit": receipt.target_commit,
        },
    )


def load_review_request(
    project_root: Path,
    *,
    store: RunStore,
    run_id: str,
    allow_missing: bool = False,
) -> ReviewRequest | None:
    ref = review_request_ref(run_id)
    path = project_root / ref
    if not path.exists():
        if allow_missing:
            return None
        raise RunStoreError(f"Run {run_id} is missing review request evidence.")
    try:
        request = ReviewRequest.model_validate(
            json.loads(path.read_text(encoding="utf-8"))
        )
    except Exception as exc:
        raise RunStoreError(
            f"Run {run_id} review request evidence is invalid: {exc}"
        ) from exc
    if request.run_id != run_id:
        raise RunStoreError("Review request run identity is inconsistent.")
    request_digest = digest(request)
    if not _anchored(
        store,
        run_id,
        event_type="review.requested",
        ref_key="review_request_ref",
        ref_value=ref,
        digest_key="review_request_digest",
        digest_value=request_digest,
    ):
        raise RunStoreError("Review request is not anchored in durable run events.")
    return request


def load_review_receipt(
    project_root: Path,
    *,
    store: RunStore,
    run_id: str,
    allow_missing: bool = False,
) -> tuple[ReviewRequest, ReviewReceipt] | None:
    request = load_review_request(
        project_root,
        store=store,
        run_id=run_id,
        allow_missing=allow_missing,
    )
    if request is None:
        return None

    ref = review_receipt_ref(run_id)
    path = project_root / ref
    if not path.exists():
        if allow_missing:
            return None
        raise RunStoreError(f"Run {run_id} is missing review receipt evidence.")
    try:
        receipt = ReviewReceipt.model_validate(
            json.loads(path.read_text(encoding="utf-8"))
        )
    except Exception as exc:
        raise RunStoreError(
            f"Run {run_id} review receipt evidence is invalid: {exc}"
        ) from exc

    receipt_digest = digest(receipt)
    if receipt.run_id != run_id or receipt.task_id != request.task_id:
        raise RunStoreError("Review receipt identity is inconsistent.")
    if receipt.request_digest != digest(request):
        raise RunStoreError("Review receipt does not match durable request.")
    if not _anchored(
        store,
        run_id,
        event_type="review.observed",
        ref_key="review_receipt_ref",
        ref_value=ref,
        digest_key="review_receipt_digest",
        digest_value=receipt_digest,
    ):
        raise RunStoreError("Review receipt is not anchored in durable run events.")
    return request, receipt
