"""Read-only lifecycle evidence inspection, without lifecycle dispatch.

The output is an observation, never a verification seal or authorization.
Unsupported live-WAL sources fail closed before SQLite connects.
"""
from __future__ import annotations

import json
from pathlib import Path
from datetime import datetime

from projectctl.core.digest import digest
from projectctl.schemas.execution import parse_execution_plan, parse_worker_checkpoint
from projectctl.trace.snapshot import (
    TraceSnapshotError, read_run_artifact, read_run_db_snapshot, _valid_run_id,
    read_checkpoint_artifact,
)
from projectctl.trace.validate import inspect_artifact_snapshot, _PARSERS, _object_no_duplicates

KINDS = (
    "execution_plan", "worker_result", "verification_manifest",
    "evidence_manifest", "integration_manifest", "publication_manifest",
)


def _finding(state, reason, **metadata):
    return {"state": state, "reason": reason, **metadata}


def _unbound_artifacts(root, run_id):
    """Report file observations even when RunStore cannot be safely opened.

    Parsing files cannot establish their binding to the actual RunStore row.
    Hence existing artifacts stay unknown rather than becoming observed Runs.
    """
    checks = {}
    for kind in KINDS:
        try:
            source = read_run_artifact(root, run_id, kind)
            checks[kind] = (_finding("missing", "artifact_missing") if source is None else
                            _finding("unknown", "runstore_binding_unavailable",
                                     sha256=source.content_sha256))
        except TraceSnapshotError as exc:
            checks[kind] = _finding("unknown", exc.reason_code)
    return checks


def assemble_audit(db, files, *, project_root=None):
    """Cross-check bounded snapshots; optional read-only Git observations."""
    record = db.record
    checks = {}
    models = {}
    plan = None
    source = files.get("execution_plan")
    if source is not None:
        try:
            raw = json.loads(source.raw_bytes, object_pairs_hook=_object_no_duplicates)
            plan = parse_execution_plan(raw)
            if plan.task_id != db.task_id or digest(plan) != record["execution_plan_digest"]:
                raise ValueError
            if plan.base_commit != record["base_commit"]:
                raise ValueError
            models["execution_plan"] = plan
            checks["execution_plan"] = _finding("observed", "schema_identity_digest_match",
                                                  sha256=source.content_sha256)
        except (ValueError, TypeError, KeyError):
            plan = None
            checks["execution_plan"] = _finding("inconsistent", "plan_binding_mismatch")
    else:
        checks["execution_plan"] = _finding("missing", "artifact_missing")
    for name in ("base_commit", "candidate_commit", "execution_plan_digest", "worktree_id"):
        if name in db.manifest:
            checks["run_manifest_" + name] = _finding(
                "observed" if db.manifest[name] == record.get(name) else "inconsistent",
                "run_record_manifest_cross_check")
    for kind in KINDS[1:]:
        source = files.get(kind)
        if source is None:
            checks[kind] = _finding("missing", "artifact_missing")
            continue
        if plan is None:
            checks[kind] = _finding("unknown", "execution_plan_identity_unavailable",
                                    sha256=source.content_sha256)
            continue
        descriptor = inspect_artifact_snapshot(
            source, source_kind=kind, run_id=db.run_id, task_id=db.task_id,
            project_id=plan.project_id,
        )
        if descriptor.validation_state != "present":
            checks[kind] = _finding("unknown" if descriptor.validation_state == "unsupported"
                                    else "inconsistent", descriptor.reason_code,
                                    sha256=source.content_sha256)
            continue
        raw = json.loads(source.raw_bytes)
        models[kind] = _PARSERS[kind][raw.get("schema_version", 1)].model_validate(raw)
        checks[kind] = _finding("observed", "schema_identity_match",
                                sha256=source.content_sha256)
    # Compare model digests, not file-byte hashes, as the writers do.
    evidence = models.get("evidence_manifest")
    verification = models.get("verification_manifest")
    integration = models.get("integration_manifest")
    if evidence:
        for field, kind in (("worker_result_digest", "worker_result"),
                            ("verification_manifest_digest", "verification_manifest")):
            model = models.get(kind)
            checks[field] = _finding(
                "unknown" if model is None else
                "observed" if digest(model) == getattr(evidence, field) else "inconsistent",
                "parent_digest_cross_check",
            )
        candidate_matches = evidence.candidate_commit == record.get("candidate_commit")
        checks["candidate_binding"] = _finding(
            "observed" if candidate_matches else "inconsistent", "run_evidence_candidate_cross_check")
        checks["evidence_base"] = _finding(
            "observed" if evidence.base_commit == record["base_commit"] else "inconsistent",
            "run_evidence_base_cross_check")
        if verification:
            for evidence_field, verification_field in (
                ("workspace_state_digest", "workspace_state_digest"),
                ("verification_profile_digest", "profile_digest"),
                ("overall_pass", "overall_pass"),
            ):
                if hasattr(evidence, evidence_field) and hasattr(verification, verification_field):
                    checks[evidence_field] = _finding(
                        "observed" if getattr(evidence, evidence_field) ==
                        getattr(verification, verification_field) else "inconsistent",
                        "verification_evidence_cross_check")
    if verification:
        checks["verification_timestamps"] = _finding(
            "observed" if verification.completed_at >= verification.started_at else "inconsistent",
            "wall_clock_order_only_not_monotonic_duration")
    if integration:
        matches = (integration.candidate_commit == record.get("candidate_commit")
                   and integration.base_commit == record["base_commit"])
        checks["integration_binding"] = _finding(
            "observed" if matches else "inconsistent", "run_integration_cross_check")
        checks["integration_evidence_digest"] = _finding(
            "unknown" if evidence is None else
            "observed" if digest(evidence) == integration.evidence_digest else "inconsistent",
            "parent_digest_cross_check")
        checks["worktree_cleanup"] = _finding(
            "observed" if integration.worktree_cleaned else "unknown",
            "recorded_cleanup_expected" if integration.worktree_cleaned else "cleanup_not_proven")
        if not getattr(integration, "publication_required", False):
            if files.get("publication_manifest") is None:
                checks["publication_manifest"] = _finding("not_applicable", "local_integration")
        else:
            publication = models.get("publication_manifest")
            checks["publication_binding"] = _finding(
                "unknown" if publication is None else "observed" if
                digest(publication) == integration.publication_digest else "inconsistent",
                "publication_parent_digest_cross_check")
            if publication:
                checks["publication_candidate"] = _finding(
                    "observed" if publication.candidate_commit == record.get("candidate_commit")
                    and publication.base_commit == record["base_commit"] else "inconsistent",
                    "publication_run_candidate_cross_check")
    # Events are evidence of attempts, never consent or proof of success.
    event_types = [item["event_type"] for item in db.stage_events]
    dispatch = any(item in {"worker.started", "worker.resumed"} for item in event_types)
    checks["worker_dispatch"] = _finding(
        "observed" if dispatch else "unknown",
        "dispatch_attempt_recorded" if dispatch else "absence_does_not_prove_no_dispatch")
    checks["event_payload_integrity"] = _finding(
        "unknown", "no_authenticated_event_log_baseline")
    previous_time = None
    for event in db.stage_events:
        try:
            payload = json.loads(event["payload_json"], object_pairs_hook=_object_no_duplicates)
            if not isinstance(payload, dict):
                raise ValueError
            at = datetime.fromisoformat(event["created_at"])
            if at.tzinfo is None or (previous_time is not None and at < previous_time):
                raise ValueError
            previous_time = at
            for field, kind in (("verification_manifest_digest", "verification_manifest"),
                                ("evidence_digest", "evidence_manifest"),
                                ("evidence_manifest_digest", "evidence_manifest")):
                if field in payload and kind in models and payload[field] != digest(models[kind]):
                    raise ValueError
        except (ValueError, TypeError):
            checks["event_payload_integrity"] = _finding("inconsistent", "event_content_mismatch")
    status = db.observed_status.value
    if status in {"ready_to_integrate", "integrating", "passed", "awaiting_review"}:
        checks["verification_success"] = _finding(
            "unknown" if not evidence or not verification else "observed" if
            evidence.overall_pass and verification.overall_pass else "inconsistent",
            "terminal_or_candidate_verification_cross_check")
    checkpoint = None
    if record.get("checkpoint_ref"):
        source = files.get("worker_checkpoint")
        if source is None:
            checks["worker_checkpoint"] = _finding("missing", "checkpoint_artifact_missing")
        else:
            try:
                checkpoint = parse_worker_checkpoint(json.loads(
                    source.raw_bytes, object_pairs_hook=_object_no_duplicates))
                if (checkpoint.run_id != db.run_id or checkpoint.task_id != db.task_id
                        or checkpoint.base_commit != record["base_commit"]
                        or checkpoint.worktree_id != record["worktree_id"]
                        or checkpoint.branch_name != record["branch_name"]):
                    raise ValueError
                matching = [json.loads(e["payload_json"]) for e in db.stage_events
                            if e["event_type"] == "worker.checkpointed"
                            and json.loads(e["payload_json"]).get("checkpoint_ref") == record["checkpoint_ref"]]
                if not matching or matching[-1].get("checkpoint_digest") != digest(checkpoint):
                    raise ValueError
                if checkpoint.schema_version == 2 and digest(checkpoint.quota_snapshot) != checkpoint.quota_snapshot_digest:
                    raise ValueError
                checks["worker_checkpoint"] = _finding("observed", "checkpoint_event_digest_match")
            except (ValueError, TypeError, KeyError, AttributeError):
                checkpoint = None
                checks["worker_checkpoint"] = _finding("inconsistent", "checkpoint_binding_mismatch")
    if project_root is not None:
        from projectctl.application.lifecycle_git import inspect_git
        checks.update(inspect_git(project_root, db, plan, evidence, integration, checkpoint))
    proposed = {"claimed": "start", "checkpointed": "resume", "verifying": "verify",
                "ready_to_integrate": "integrate"}.get(status)
    checkpointed = status == "running" and bool(record.get("checkpoint_ref"))
    if checkpointed and checkpoint is not None and checkpoint.schema_version == 2:
        proposed = "resume"
    reasons = ["separate_owner_authorization_required", "current_inputs_require_revalidation"]
    required = {"start": ("execution_plan",), "resume": ("execution_plan",),
                "verify": ("execution_plan", "worker_result"),
                "integrate": ("execution_plan", "worker_result", "verification_manifest", "evidence_manifest")}
    if proposed and any(checks[k]["state"] != "observed" for k in required[proposed]):
        reasons.append("required_evidence_unavailable")
        proposed = None
    if record.get("lease_owner") or record.get("lease_expires_at"):
        reasons.append("lease_present_do_not_steal")
        proposed = None
    if any(check["state"] == "inconsistent" for check in checks.values()):
        reasons.append("inconsistent_evidence")
        proposed = None
    required_git = ("worktree_path", "worktree", "target_ref")
    if proposed == "start":
        required_git += ("worktree_head", "worktree_clean")
    elif proposed == "resume":
        required_git += ("worktree_head", "checkpoint_workspace")
    elif proposed == "verify":
        required_git += ("worktree_head",)
    elif proposed == "integrate":
        required_git += ("worktree_head", "worktree_clean", "candidate_diff")
    if proposed is not None and (any(
        checks.get(key, {}).get("state") != "observed"
        for key in required_git
    ) or checks.get("git_observation", {}).get("state") == "unknown"):
        proposed = None
        reasons.append("git_inputs_unproven")
    if (status in {"running", "integrating", "preparing"} and not checkpointed) or (status == "claimed" and dispatch):
        reasons.append("possibly_dispatched_reconcile_only")
        proposed = None
    if checkpointed:
        checkpoint_index = max((i for i, kind in enumerate(event_types)
                                if kind == "worker.checkpointed"), default=-1)
        if checkpoint is None or any(kind == "worker.resumed" for kind in event_types[checkpoint_index + 1:]):
            proposed = None
            reasons.append("checkpoint_resume_uncertain_reconcile_only")
    if ((status == "claimed" and files.get("worker_result") is not None)
            or (status == "verifying" and files.get("verification_manifest") is not None)
            or (status == "ready_to_integrate" and files.get("integration_manifest") is not None)):
        proposed = None
        reasons.append("previous_stage_artifact_reconcile_only")
    return {
        "schema_kind": "projectctl.lifecycle_audit", "schema_version": 1,
        "run_id": db.run_id, "observed_status": status,
        "authority": "derived_non_authoritative",
        "consistency": "independent_source_observations_not_atomic_snapshot",
        "checks": dict(sorted(checks.items())),
        "sources": {"run_record_sha256": db.run_record_sha256,
                    "run_manifest_sha256": db.run_manifest_sha256,
                    "event_metadata_sha256": db.event_stream_sha256},
        "event_count": len(db.stage_events),
        "checkpointed": checkpointed,
        "timing": _finding("unknown", "no_bound_measurement_artifact"),
        "task_authority": _finding("unknown", "task_provider_not_contacted"),
        "handoff": {"proposed_stage": proposed, "permitted_action": "inspect",
                    "dispatch_authorized": False, "implicit_retry_allowed": False,
                    "guards": reasons},
    }


def audit_run(project_root: Path, run_id: str, *, measurements: Path | None = None) -> dict:
    """Never constructs RunStore, contacts providers, acquires leases or writes."""
    _valid_run_id(run_id)
    root = Path(project_root)
    try:
        db = read_run_db_snapshot(root, run_id, details=True)
        files = {kind: read_run_artifact(root, run_id, kind) for kind in KINDS}
        if db.record.get("checkpoint_ref"):
            files["worker_checkpoint"] = read_checkpoint_artifact(
                root, run_id, db.record["checkpoint_ref"])
        after = read_run_db_snapshot(root, run_id, details=True)
        if db != after:
            raise TraceSnapshotError("source_changed")
        for kind, source in files.items():
            repeated = (read_checkpoint_artifact(root, run_id, db.record["checkpoint_ref"])
                        if kind == "worker_checkpoint" else read_run_artifact(root, run_id, kind))
            if source != repeated:
                raise TraceSnapshotError("source_changed")
        report = assemble_audit(db, files, project_root=root)
        from projectctl.telemetry.lifecycle_reader import inspect_measurements
        report["timing"] = inspect_measurements(measurements, run_id)
        if report["timing"]["state"] == "inconsistent":
            report["handoff"]["proposed_stage"] = None
            report["handoff"]["guards"].append("measurement_provenance_invalid")
        if report["timing"].get("command_outcome") in {"pending", "interrupted_or_error"}:
            report["handoff"]["proposed_stage"] = None
            report["handoff"]["guards"].append("measurement_operation_uncertain_reconcile_only")
        return report
    except TraceSnapshotError as exc:
        from projectctl.telemetry.lifecycle_reader import inspect_measurements
        return {
            "schema_kind": "projectctl.lifecycle_audit", "schema_version": 1,
            "run_id": run_id, "authority": "derived_non_authoritative",
            "observed_status": None,
            "source": _finding("unknown", exc.reason_code),
            "checks": _unbound_artifacts(root, run_id),
            "timing": inspect_measurements(measurements, run_id),
            "handoff": {"proposed_stage": None, "permitted_action": "inspect",
                        "dispatch_authorized": False, "implicit_retry_allowed": False,
                        "guards": ["source_unproven_reconcile_only"]},
        }
