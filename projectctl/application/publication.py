from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from projectctl.core.digest import digest
from projectctl.core.errors import RunStoreError
from projectctl.schemas.delivery import PublicationManifest, PublicationRequest
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


def publication_request_ref(run_id: str) -> str:
    return f".projectctl/runs/{run_id}/publication-request.json"


def publication_manifest_ref(run_id: str) -> str:
    return f".projectctl/runs/{run_id}/publication-manifest.json"


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


def persist_publication_request(
    project_root: Path,
    *,
    store: RunStore,
    request: PublicationRequest,
) -> None:
    ref = publication_request_ref(request.run_id)
    request_digest = digest(request)
    _atomic_json(project_root / ref, request)
    store.append_event(
        request.run_id,
        "publication.requested",
        {
            "publication_request_ref": ref,
            "publication_request_digest": request_digest,
            "candidate_commit": request.candidate_commit,
            "target_ref": request.target_ref,
        },
    )


def persist_publication_manifest(
    project_root: Path,
    *,
    store: RunStore,
    request: PublicationRequest,
    manifest: PublicationManifest,
) -> None:
    if manifest.run_id != request.run_id or manifest.task_id != request.task_id:
        raise RunStoreError("Publication manifest identity does not match request.")
    if manifest.request_digest != digest(request):
        raise RunStoreError("Publication manifest request digest does not match.")
    if manifest.candidate_commit != request.candidate_commit:
        raise RunStoreError("Publication candidate does not match durable request.")
    if manifest.evidence_digest != request.evidence_digest:
        raise RunStoreError("Publication evidence digest does not match durable request.")

    ref = publication_manifest_ref(request.run_id)
    manifest_digest = digest(manifest)
    _atomic_json(project_root / ref, manifest)
    store.append_event(
        request.run_id,
        "publication.observed",
        {
            "publication_manifest_ref": ref,
            "publication_manifest_digest": manifest_digest,
            "publication_request_digest": manifest.request_digest,
            "published": manifest.published,
            "remote_before": manifest.remote_before,
            "remote_after": manifest.remote_after,
        },
    )


def load_publication_request(
    project_root: Path,
    *,
    store: RunStore,
    run_id: str,
    allow_missing: bool = False,
) -> PublicationRequest | None:
    ref = publication_request_ref(run_id)
    path = project_root / ref
    if not path.exists():
        if allow_missing:
            return None
        raise RunStoreError(f"Run {run_id} is missing publication request evidence.")
    try:
        request = PublicationRequest.model_validate(
            json.loads(path.read_text(encoding="utf-8"))
        )
    except Exception as exc:
        raise RunStoreError(
            f"Run {run_id} publication request evidence is invalid: {exc}"
        ) from exc
    if request.run_id != run_id:
        raise RunStoreError("Publication request run identity is inconsistent.")
    request_digest = digest(request)
    if not _anchored(
        store,
        run_id,
        event_type="publication.requested",
        ref_key="publication_request_ref",
        ref_value=ref,
        digest_key="publication_request_digest",
        digest_value=request_digest,
    ):
        raise RunStoreError("Publication request is not anchored in durable run events.")
    return request


def load_publication_manifest(
    project_root: Path,
    *,
    store: RunStore,
    run_id: str,
    allow_missing: bool = False,
) -> tuple[PublicationRequest, PublicationManifest] | None:
    request = load_publication_request(
        project_root,
        store=store,
        run_id=run_id,
        allow_missing=allow_missing,
    )
    if request is None:
        return None

    ref = publication_manifest_ref(run_id)
    path = project_root / ref
    if not path.exists():
        if allow_missing:
            return None
        raise RunStoreError(f"Run {run_id} is missing publication manifest evidence.")
    try:
        manifest = PublicationManifest.model_validate(
            json.loads(path.read_text(encoding="utf-8"))
        )
    except Exception as exc:
        raise RunStoreError(
            f"Run {run_id} publication manifest evidence is invalid: {exc}"
        ) from exc

    manifest_digest = digest(manifest)
    if manifest.run_id != run_id or manifest.task_id != request.task_id:
        raise RunStoreError("Publication manifest identity is inconsistent.")
    if manifest.request_digest != digest(request):
        raise RunStoreError("Publication manifest does not match durable request.")
    if not _anchored(
        store,
        run_id,
        event_type="publication.observed",
        ref_key="publication_manifest_ref",
        ref_value=ref,
        digest_key="publication_manifest_digest",
        digest_value=manifest_digest,
    ):
        raise RunStoreError("Publication manifest is not anchored in durable run events.")
    return request, manifest
