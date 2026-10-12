from __future__ import annotations

import difflib
import hashlib
import json
import os
import socket
import tempfile
import uuid
from pathlib import Path, PurePosixPath

import yaml

from projectctl.application.tasks import capture_task_snapshot
from projectctl.core.digest import digest
from projectctl.core.enums import RunStatus
from projectctl.core.errors import ConfigurationError, StaleSnapshotError
from projectctl.core.paths import resolve_inside_repo
from projectctl.core.time import utc_now
from projectctl.git import resolve_commit
from projectctl.execution_scope.catalog import (
    EXECUTION_SCOPE_PATH,
    load_execution_scope_catalog,
    resolve_execution_scope_catalog,
)
from projectctl.execution_scope.migration import assert_no_pending_scope_migration
from projectctl.project.loader import load_project_config
from projectctl.project.locking import execution_authority_gated, project_lock
from projectctl.scheduler.digests import semantic_task_digest
from projectctl.schemas.context_adoption import (
    ContextScopeAdoptionReceipt,
    ContextScopeAdoptionRequest,
    ContextScopeReview,
    parse_context_scope_review,
    parse_context_scope_adoption_request,
    parse_context_scope_adoption_receipt,
)
from projectctl.schemas.context_discovery import (
    ContextDiscoveryReport,
    ContextScopeSuggestion,
)
from projectctl.schemas.execution_input import ExecutionPathScope
from projectctl.schemas.execution_scope import ExecutionScopeCatalog, ExecutionTaskScope
from projectctl.storage.runs import RunStore


_ABSENT_DIGEST = "absent"
_ACTIVE_RUN_STATUSES = {
    RunStatus.PLANNED,
    RunStatus.PREPARING,
    RunStatus.CLAIMED,
    RunStatus.RUNNING,
    RunStatus.VERIFYING,
    RunStatus.READY_TO_INTEGRATE,
    RunStatus.INTEGRATING,
    RunStatus.AWAITING_REVIEW,
    RunStatus.NEEDS_DECISION,
}


def _actor() -> str:
    return f"projectctl:{socket.gethostname()}:{os.getpid()}"


def _sha256_bytes(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _atomic_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=".projectctl-context-adopt-",
        suffix=".tmp",
        dir=path.parent,
    )
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    finally:
        try:
            Path(tmp_name).unlink()
        except FileNotFoundError:
            pass


def _atomic_json(path: Path, value) -> None:
    payload = (
        json.dumps(
            value.model_dump(mode="json"),
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
        )
        + "\n"
    ).encode("utf-8")
    _atomic_bytes(path, payload)


def _catalog_state(
    root: Path,
) -> tuple[Path, bytes | None, str, ExecutionScopeCatalog]:
    assert_no_pending_scope_migration(root)
    snapshot = resolve_execution_scope_catalog(root)
    if snapshot.source == "legacy":
        raise ConfigurationError(
            "Legacy-only scope authority requires 'projectctl scope migrate --apply' "
            "and a committed policy change before canonical review/adoption."
        )
    path = snapshot.path or resolve_inside_repo(root, EXECUTION_SCOPE_PATH, must_exist=False)
    if snapshot.catalog is None:
        return path, None, _ABSENT_DIGEST, ExecutionScopeCatalog()
    raw = snapshot.raw_bytes
    assert raw is not None
    return path, raw, _sha256_bytes(raw), snapshot.catalog


def _render_catalog(catalog: ExecutionScopeCatalog) -> str:
    payload = catalog.model_dump(mode="json")
    return yaml.safe_dump(
        payload,
        sort_keys=False,
        allow_unicode=True,
    ).rstrip() + "\n"


def _scope_key(scope) -> tuple[str, str]:
    return scope.path, scope.kind


def _scope_covers(existing: ExecutionPathScope, candidate: ExecutionPathScope) -> bool:
    if existing.kind == "exact":
        return candidate.kind == "exact" and existing.path == candidate.path
    base = PurePosixPath(existing.path)
    target = PurePosixPath(candidate.path)
    try:
        target.relative_to(base)
        return True
    except ValueError:
        return False


def _merge_scopes(existing, selected) -> list[ExecutionPathScope]:
    merged: list[ExecutionPathScope] = [
        ExecutionPathScope(path=item.path, kind=item.kind) for item in existing
    ]
    for item in selected:
        candidate = ExecutionPathScope(path=item.path, kind=item.kind)
        if any(_scope_covers(current, candidate) for current in merged):
            continue
        merged.append(candidate)
    unique = {_scope_key(item): item for item in merged}
    return sorted(unique.values(), key=lambda item: (item.path, item.kind))


def _load_suggestion(path: Path) -> ContextScopeSuggestion:
    try:
        return ContextScopeSuggestion.model_validate(
            json.loads(path.read_text(encoding="utf-8"))
        )
    except Exception as exc:
        raise ConfigurationError(f"Invalid context scope suggestion {path}: {exc}") from exc


def _suggestion_path(root: Path, task_id: str, suggestion_id: str) -> Path:
    return (
        root
        / ".projectctl"
        / "context"
        / "suggestions"
        / task_id
        / f"{suggestion_id}.json"
    )


def _load_review(path: Path) -> ContextScopeReview:
    try:
        return parse_context_scope_review(
            json.loads(path.read_text(encoding="utf-8"))
        )
    except Exception as exc:
        raise ConfigurationError(f"Invalid context scope review {path}: {exc}") from exc


def _review_path(root: Path, task_id: str, review_id: str) -> Path:
    return (
        root
        / ".projectctl"
        / "context"
        / "reviews"
        / task_id
        / f"{review_id}.json"
    )


def _find_discovery(
    root: Path,
    task_id: str,
    expected_digest: str,
) -> ContextDiscoveryReport:
    directory = root / ".projectctl" / "context" / "discovery" / task_id
    if not directory.exists():
        raise ConfigurationError(
            f"Missing discovery artifact for task {task_id!r}; regenerate the M5.0 suggestion."
        )
    matches: list[ContextDiscoveryReport] = []
    for path in sorted(directory.glob("*.json")):
        try:
            report = ContextDiscoveryReport.model_validate(
                json.loads(path.read_text(encoding="utf-8"))
            )
        except Exception:
            continue
        if digest(report) == expected_digest:
            matches.append(report)
    if len(matches) != 1:
        raise ConfigurationError(
            "Could not resolve exactly one discovery artifact for the suggestion digest."
        )
    return matches[0]


def _validate_selection(
    suggestion_scopes,
    selected_paths: list[str] | None,
    *,
    label: str,
):
    by_path = {item.path: item for item in suggestion_scopes}
    if selected_paths is None:
        return list(suggestion_scopes)
    if len(selected_paths) != len(set(selected_paths)):
        raise ConfigurationError(f"Duplicate {label} path in review selection.")
    unknown = sorted(set(selected_paths) - set(by_path))
    if unknown:
        raise ConfigurationError(
            f"Review selected {label} paths outside the suggestion: {', '.join(unknown)}"
        )
    return [by_path[path] for path in selected_paths]


def _current_task_digest(root: Path, task_id: str) -> str:
    snapshot = capture_task_snapshot(
        root,
        state="all",
        read_cache_max_age_seconds=0,
    )
    task = next((item for item in snapshot.tasks if item.id == task_id), None)
    if task is None:
        raise StaleSnapshotError(f"Reviewed task {task_id!r} is no longer present.")
    return semantic_task_digest(task)


def create_scope_review(
    project_root: Path,
    task_id: str,
    *,
    suggestion_id: str,
    input_paths: list[str] | None = None,
    write_paths: list[str] | None = None,
    resources: list[str] | None = None,
) -> ContextScopeReview:
    root = project_root.resolve()
    config = load_project_config(root)
    suggestion_path = _suggestion_path(root, task_id, suggestion_id)
    if not suggestion_path.exists():
        raise ConfigurationError(
            f"Unknown scope suggestion {suggestion_id!r} for task {task_id!r}."
        )
    suggestion = _load_suggestion(suggestion_path)
    if suggestion.task_id != task_id:
        raise ConfigurationError("Suggestion task identity does not match review task.")

    suggestion_digest = digest(suggestion)
    discovery = _find_discovery(root, task_id, suggestion.discovery_digest)
    if discovery.task_id != task_id or discovery.project_id != config.project.id:
        raise ConfigurationError("Discovery artifact project/task identity mismatch.")
    if discovery.base_commit != suggestion.base_commit:
        raise ConfigurationError("Suggestion and discovery base commits do not match.")
    if resolve_commit(root, discovery.integration_target_ref) != discovery.base_commit:
        raise StaleSnapshotError(
            "Discovery integration target advanced; regenerate discovery before review."
        )
    if _current_task_digest(root, task_id) != discovery.task_digest:
        raise StaleSnapshotError(
            "Task authority changed since discovery; regenerate suggestion before review."
        )

    selected_inputs = _validate_selection(
        suggestion.input_scopes,
        input_paths,
        label="input",
    )
    selected_writes = _validate_selection(
        suggestion.write_scopes,
        write_paths,
        label="write",
    )
    raw_resources = list(resources or [])
    if any(not item.strip() for item in raw_resources):
        raise ConfigurationError("Review resource keys must be non-empty.")
    resource_additions = sorted({item.strip() for item in raw_resources})

    path, raw, before_digest, catalog = _catalog_state(root)
    existing = catalog.tasks.get(task_id)
    existing_inputs = list(existing.inputs) if existing is not None else []
    existing_writes = list(existing.writes) if existing is not None else []
    existing_resources = list(existing.resources) if existing is not None else []

    proposed_inputs = _merge_scopes(existing_inputs, selected_inputs)
    proposed_writes = _merge_scopes(existing_writes, selected_writes)
    proposed_resources = sorted(set(existing_resources) | set(resource_additions))
    if not proposed_inputs:
        raise ConfigurationError(
            "Reviewed adoption would leave the task without input scope."
        )
    if not proposed_writes:
        raise ConfigurationError(
            "Reviewed adoption would leave the task without write scope; "
            "M5.1 will not invent a write authority."
        )

    proposed_scope = ExecutionTaskScope(
        task_id=task_id,
        inputs=proposed_inputs,
        writes=proposed_writes,
        resources=proposed_resources,
    )
    tasks = dict(catalog.tasks)
    tasks[task_id] = proposed_scope
    proposed_catalog = ExecutionScopeCatalog(tasks=tasks)
    proposed_yaml = _render_catalog(proposed_catalog)
    proposed_digest = _sha256_bytes(proposed_yaml.encode("utf-8"))

    existing_input_keys = {_scope_key(item) for item in existing_inputs}
    existing_write_keys = {_scope_key(item) for item in existing_writes}
    added_inputs = [
        item.path
        for item in proposed_inputs
        if _scope_key(item) not in existing_input_keys
    ]
    added_writes = [
        item.path
        for item in proposed_writes
        if _scope_key(item) not in existing_write_keys
    ]
    added_resources = sorted(set(proposed_resources) - set(existing_resources))
    if not added_inputs and not added_writes and not added_resources:
        raise ConfigurationError(
            "Selected discovery evidence adds nothing to the existing human-managed scope."
        )

    warnings: list[str] = []
    if raw is not None:
        canonical_before = _render_catalog(catalog)
        if canonical_before.encode("utf-8") != raw:
            warnings.append(
                "Applying this review will normalize YAML formatting/comments in "
                "projectctl.scope.yaml; inspect the rendered diff before approval."
            )

    review = ContextScopeReview(
        review_id=f"context-review-{uuid.uuid4().hex}",
        created_at=utc_now(),
        project_id=config.project.id,
        task_id=task_id,
        integration_target_ref=discovery.integration_target_ref,
        base_commit=discovery.base_commit,
        task_digest=discovery.task_digest,
        discovery_digest=suggestion.discovery_digest,
        suggestion_id=suggestion.suggestion_id,
        suggestion_digest=suggestion_digest,
        suggestion_artifact=suggestion_path.relative_to(root).as_posix(),
        catalog_before_present=raw is not None,
        catalog_before_digest=before_digest,
        catalog_before_yaml=raw.decode("utf-8") if raw is not None else None,
        scope_before_digest=digest(existing) if existing is not None else None,
        proposed_scope=proposed_scope,
        proposed_catalog_digest=proposed_digest,
        proposed_catalog_yaml=proposed_yaml,
        selected_suggestion_inputs=[item.path for item in selected_inputs],
        selected_suggestion_writes=[item.path for item in selected_writes],
        added_inputs=added_inputs,
        added_writes=added_writes,
        added_resources=added_resources,
        warnings=warnings,
    )
    _atomic_json(_review_path(root, task_id, review.review_id), review)
    return review


def render_review_diff(review: ContextScopeReview) -> str:
    before = review.catalog_before_yaml or ""
    lines = difflib.unified_diff(
        before.splitlines(),
        review.proposed_catalog_yaml.splitlines(),
        fromfile=f"a/{review.catalog_path}",
        tofile=f"b/{review.catalog_path}",
        lineterm="",
    )
    return "\n".join(lines)


def _adoption_root(root: Path, task_id: str) -> Path:
    return root / ".projectctl" / "context" / "adoptions" / task_id


def _load_request(path: Path) -> ContextScopeAdoptionRequest:
    return parse_context_scope_adoption_request(
        json.loads(path.read_text(encoding="utf-8"))
    )


def _load_receipt(path: Path) -> ContextScopeAdoptionReceipt:
    return parse_context_scope_adoption_receipt(
        json.loads(path.read_text(encoding="utf-8"))
    )


def _existing_adoption(
    root: Path,
    review: ContextScopeReview,
    review_digest: str,
):
    directory = _adoption_root(root, review.task_id)
    if not directory.exists():
        return None, None, None
    pending = []
    receipts = []
    for child in sorted(directory.iterdir()):
        if not child.is_dir():
            continue
        request_path = child / "request.json"
        receipt_path = child / "receipt.json"
        if not request_path.exists():
            continue
        try:
            request = _load_request(request_path)
        except Exception as exc:
            raise ConfigurationError(
                f"Invalid context adoption request {request_path}: {exc}"
            ) from exc
        if request.review_digest != review_digest:
            continue
        if receipt_path.exists():
            try:
                receipt = _load_receipt(receipt_path)
            except Exception as exc:
                raise ConfigurationError(
                    f"Invalid context adoption receipt {receipt_path}: {exc}"
                ) from exc
            receipts.append((child, request, receipt))
        else:
            pending.append((child, request))
    if len(receipts) > 1 or len(pending) > 1 or (receipts and pending):
        raise ConfigurationError(
            "Multiple adoption histories exist for one review digest; manual audit required."
        )
    if receipts:
        child, request, receipt = receipts[0]
        return child, request, receipt
    if pending:
        child, request = pending[0]
        return child, request, None
    return None, None, None


def _assert_no_active_runs(root: Path) -> None:
    db_path = root / ".projectctl" / "state.sqlite"
    if not db_path.exists():
        return
    active = [
        item
        for item in RunStore(root).list(limit=100000)
        if item.status in _ACTIVE_RUN_STATUSES
    ]
    if active:
        rendered = ", ".join(
            f"{item.run_id}:{item.status.value}" for item in active[:12]
        )
        raise ConfigurationError(
            "Scope authority cannot change while project runs are active: " + rendered
        )


def _validate_review_before_apply(
    root: Path,
    review: ContextScopeReview,
) -> tuple[Path, bytes | None, str, ExecutionScopeCatalog]:
    if review.schema_version != 2 or review.catalog_path != EXECUTION_SCOPE_PATH:
        raise ConfigurationError("Non-canonical scope review cannot be applied.")
    config = load_project_config(root)
    if config.project.id != review.project_id:
        raise StaleSnapshotError("Review project identity changed.")
    if resolve_commit(root, review.integration_target_ref) != review.base_commit:
        raise StaleSnapshotError(
            "Review base is stale because the integration target advanced."
        )
    if _current_task_digest(root, review.task_id) != review.task_digest:
        raise StaleSnapshotError("Task authority changed after scope review.")

    suggestion_path = resolve_inside_repo(
        root,
        review.suggestion_artifact,
        must_exist=True,
    )
    suggestion = _load_suggestion(suggestion_path)
    if digest(suggestion) != review.suggestion_digest:
        raise StaleSnapshotError("Reviewed scope suggestion artifact changed.")
    if suggestion.discovery_digest != review.discovery_digest:
        raise StaleSnapshotError("Reviewed discovery identity changed.")
    if suggestion.base_commit != review.base_commit:
        raise StaleSnapshotError("Reviewed suggestion base identity changed.")

    state = _catalog_state(root)
    if state[2] != review.catalog_before_digest:
        raise StaleSnapshotError(
            "Human-managed scope catalog changed after review; create a fresh review."
        )
    _assert_no_active_runs(root)

    current_catalog = state[3]
    tasks = dict(current_catalog.tasks)
    tasks[review.task_id] = review.proposed_scope
    recomputed_yaml = _render_catalog(ExecutionScopeCatalog(tasks=tasks))
    if recomputed_yaml != review.proposed_catalog_yaml:
        raise StaleSnapshotError(
            "Reviewed proposed catalog no longer reconstructs from the current before-state."
        )
    if _sha256_bytes(recomputed_yaml.encode("utf-8")) != review.proposed_catalog_digest:
        raise StaleSnapshotError("Reviewed proposed catalog digest changed.")
    return state


def _validate_request_against_review(
    request: ContextScopeAdoptionRequest,
    review: ContextScopeReview,
    review_digest: str,
    approval_digest: str,
) -> None:
    expected = {
        "project_id": review.project_id,
        "task_id": review.task_id,
        "review_id": review.review_id,
        "review_digest": review_digest,
        "approval_digest": approval_digest,
        "base_commit": review.base_commit,
        "task_digest": review.task_digest,
        "catalog_path": review.catalog_path,
        "catalog_before_digest": review.catalog_before_digest,
        "proposed_catalog_digest": review.proposed_catalog_digest,
        "proposed_scope_digest": digest(review.proposed_scope),
    }
    for field, value in expected.items():
        if getattr(request, field) != value:
            raise ConfigurationError(
                f"Adoption request field {field!r} no longer matches the reviewed proposal."
            )


def _make_receipt(
    *,
    request: ContextScopeAdoptionRequest,
    review: ContextScopeReview,
) -> ContextScopeAdoptionReceipt:
    return ContextScopeAdoptionReceipt(
        adoption_id=request.adoption_id,
        adopted_at=utc_now(),
        actor=request.actor,
        project_id=request.project_id,
        task_id=request.task_id,
        review_id=request.review_id,
        review_digest=request.review_digest,
        request_digest=digest(request),
        approval_digest=request.approval_digest,
        base_commit=request.base_commit,
        task_digest=request.task_digest,
        catalog_path=request.catalog_path,
        catalog_before_digest=request.catalog_before_digest,
        catalog_after_digest=request.proposed_catalog_digest,
        scope_before_digest=review.scope_before_digest,
        scope_after_digest=digest(review.proposed_scope),
        adopted_scope=review.proposed_scope,
    )


@execution_authority_gated
def adopt_scope_review(
    project_root: Path,
    task_id: str,
    *,
    review_id: str,
    approval_digest: str,
) -> ContextScopeAdoptionReceipt:
    root = project_root.resolve()
    review_path = _review_path(root, task_id, review_id)
    if not review_path.exists():
        raise ConfigurationError(
            f"Unknown context scope review {review_id!r} for task {task_id!r}."
        )
    review = _load_review(review_path)
    if review.task_id != task_id:
        raise ConfigurationError("Review task identity does not match adoption task.")
    if review.schema_version != 2 or review.catalog_path != EXECUTION_SCOPE_PATH:
        raise ConfigurationError(
            "Historical scope reviews are audit-only. Regenerate a canonical "
            "review for projectctl.scope.yaml; old approval digests are not transferable."
        )
    review_digest = digest(review)
    if approval_digest != review_digest:
        raise ConfigurationError(
            "Approval digest does not match the exact durable review artifact."
        )

    with project_lock(root, "context-scope-adoption"):
        adoption_dir, request, receipt = _existing_adoption(
            root,
            review,
            review_digest,
        )
        if receipt is not None:
            _validate_request_against_review(
                request,
                review,
                review_digest,
                approval_digest,
            )
            if (
                receipt.approval_digest != approval_digest
                or receipt.review_digest != review_digest
                or receipt.request_digest != digest(request)
                or receipt.adoption_id != request.adoption_id
            ):
                raise ConfigurationError(
                    "Existing adoption receipt does not match its durable request/review."
                )
            return receipt

        path, raw, current_digest, catalog = _catalog_state(root)

        if request is not None:
            _validate_request_against_review(
                request,
                review,
                review_digest,
                approval_digest,
            )
            if current_digest == request.proposed_catalog_digest:
                adopted = load_execution_scope_catalog(root)
                scope = adopted.tasks.get(task_id) if adopted is not None else None
                if scope is None or digest(scope) != request.proposed_scope_digest:
                    raise ConfigurationError(
                        "Catalog matches adoption bytes but reviewed scope is missing; "
                        "manual audit required."
                    )
                receipt = _make_receipt(request=request, review=review)
                _atomic_json(adoption_dir / "receipt.json", receipt)
                return receipt
            if current_digest != request.catalog_before_digest:
                raise ConfigurationError(
                    "Pending adoption is in an ambiguous catalog state; "
                    "manual audit is required."
                )
        else:
            _validate_review_before_apply(root, review)
            adoption_id = f"context-adoption-{uuid.uuid4().hex}"
            adoption_dir = _adoption_root(root, task_id) / adoption_id
            request = ContextScopeAdoptionRequest(
                adoption_id=adoption_id,
                requested_at=utc_now(),
                actor=_actor(),
                project_id=review.project_id,
                task_id=task_id,
                review_id=review.review_id,
                review_digest=review_digest,
                approval_digest=approval_digest,
                base_commit=review.base_commit,
                task_digest=review.task_digest,
                catalog_path=review.catalog_path,
                catalog_before_digest=review.catalog_before_digest,
                proposed_catalog_digest=review.proposed_catalog_digest,
                proposed_scope_digest=digest(review.proposed_scope),
            )
            _atomic_json(adoption_dir / "request.json", request)

        # Revalidate immediately before the authoritative write. This also
        # covers retry of a durable request that remained in before-state.
        validated_path, before_bytes, validated_digest, _ = (
            _validate_review_before_apply(root, review)
        )
        if validated_path != path or validated_digest != request.catalog_before_digest:
            raise StaleSnapshotError(
                "Scope catalog changed between adoption validation snapshots."
            )
        try:
            _atomic_bytes(path, review.proposed_catalog_yaml.encode("utf-8"))
            adopted = load_execution_scope_catalog(root)
            adopted_scope = adopted.tasks.get(task_id) if adopted is not None else None
            if adopted_scope is None or digest(adopted_scope) != digest(review.proposed_scope):
                raise ConfigurationError(
                    "Post-write scope validation does not match the reviewed proposal."
                )
            after_digest = _sha256_bytes(path.read_bytes())
            if after_digest != review.proposed_catalog_digest:
                raise ConfigurationError(
                    "Post-write catalog bytes do not match the reviewed proposal."
                )
        except Exception:
            if before_bytes is None:
                try:
                    path.unlink()
                except FileNotFoundError:
                    pass
            else:
                _atomic_bytes(path, before_bytes)
            raise

        receipt = _make_receipt(request=request, review=review)
        _atomic_json(adoption_dir / "receipt.json", receipt)
        return receipt
