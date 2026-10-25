#!/usr/bin/env python3
"""D2 Attempt-3 OFFLINE-only policy simulation and read-only preview.

No live quota or Scheduler call, no Claim, Prepare, Worker or Attempt-3
identity allocation. Readiness uses existing read-only Git/Beads/ProjectCTL
probes; some of those may refresh operational caches.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys
from typing import Callable

ROOT = Path.home() / ".local/state/projectctl-dogfood-d2"
RESEARCH = Path.home() / "project/My/projectctl-advisory-lab"
VENV = Path.home() / ".local/share/projectctl-dogfood-d0/venv"
ATTEMPT3 = ROOT / "observations/ctl-prepare-attempt-3"
ATTEMPT2 = ROOT / "observations/ctl-prepare-attempt-2"
TASK = "d2ctl-g4q"
POLICY_HEAD = "3c69dd42497acadadc5d64e7b4abe5d412b309f5"
DIRECT_BASE = "32836ea5633230e50fb9d907dcdba83e357bcfc6"
MEDIUM_FIVE_HOUR = 0.18
MEDIUM_WEEKLY = 0.08
MAX_SAMPLE_AGE = 120
ALLOWED_CLOCK_SKEW = 10
ATTEMPT2_FILES = ("prepare-summary.json", "quota-before-prepare.json",
                  "scheduler-before-prepare.json")
PASS = "D2_ATTEMPT3_OFFLINE_PREVIEW_PASS__NO_LIVE_QUOTA_NO_PREPARE"
GO = "D2_ATTEMPT3_SYNTHETIC_ADMISSION_GO__NO_EXECUTION"


class AdmissionBlocked(ValueError):
    """A sanitized, synthetic or read-only fail-closed admission decision."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _aware_time(value: object) -> datetime:
    if not isinstance(value, str):
        raise AdmissionBlocked("timestamp_missing_or_invalid")
    try:
        when = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise AdmissionBlocked("timestamp_missing_or_invalid") from exc
    if when.tzinfo is None:
        raise AdmissionBlocked("timestamp_missing_or_invalid")
    return when


def _fresh(value: object, now: datetime) -> bool:
    if now.tzinfo is None:
        raise AdmissionBlocked("local_clock_invalid")
    seconds = (now - _aware_time(value)).total_seconds()
    return -ALLOWED_CLOCK_SKEW <= seconds <= MAX_SAMPLE_AGE


def _ratio(value: object, floor: float) -> bool:
    return (type(value) in (int, float) and math.isfinite(value)
            and 0 <= value <= 1 and value >= floor)


def first_quota_gate(quota: dict, *, now: datetime) -> dict:
    """Pure frozen MEDIUM first-snapshot gate; never refresh a provider."""
    if not isinstance(quota, dict):
        raise AdmissionBlocked("quota_missing_or_invalid")
    snap = quota.get("snapshot")
    if not isinstance(snap, dict):
        raise AdmissionBlocked("quota_missing_or_invalid")
    if (quota.get("mode") != "normal" or quota.get("stale") is not False):
        raise AdmissionBlocked("quota_not_normal_or_stale")
    if (snap.get("provider") != "codex_app_server"
            or snap.get("selected_limit_id") != "codex"
            or snap.get("ordinary_usage_allowed") is not True):
        raise AdmissionBlocked("quota_authority_invalid")
    if not _fresh(snap.get("observed_at"), now):
        raise AdmissionBlocked("quota_stale")
    for name in ("five_hour", "weekly"):
        bucket = snap.get(name)
        if (not isinstance(bucket, dict)
                or bucket.get("source") != "official"
                or bucket.get("confidence") != "high"
                or not _ratio(bucket.get("remaining_ratio"), 0)):
            raise AdmissionBlocked("quota_not_official")
    effective = quota.get("effective")
    if not isinstance(effective, dict):
        raise AdmissionBlocked("quota_effective_missing")
    if not _ratio(effective.get("five_hour"), MEDIUM_FIVE_HOUR):
        raise AdmissionBlocked("five_hour_medium_insufficient")
    if not _ratio(effective.get("weekly"), MEDIUM_WEEKLY):
        raise AdmissionBlocked("weekly_medium_insufficient")
    return {"decision": "D2_ATTEMPT3_SYNTHETIC_FIRST_QUOTA_GO",
            "official": True, "normal": True, "medium_floor_met": True}


def scheduler_gate(scheduler: dict, *, now: datetime,
                   canonical_unknown_digest: str) -> dict:
    """Pure second, independent Scheduler gate; digest equality NOT required."""
    if not isinstance(scheduler, dict):
        raise AdmissionBlocked("scheduler_missing_or_invalid")
    if not _fresh(scheduler.get("evaluated_at"), now):
        raise AdmissionBlocked("scheduler_stale")
    digest = scheduler.get("quota_snapshot_digest")
    if (not isinstance(digest, str) or not digest.strip()
            or not isinstance(canonical_unknown_digest, str)
            or not canonical_unknown_digest.strip()
            or digest == canonical_unknown_digest):
        raise AdmissionBlocked("scheduler_unknown_quota")
    if (scheduler.get("quota_mode") != "normal"
            or scheduler.get("selected_task_id") != TASK):
        raise AdmissionBlocked("scheduler_rejected")
    candidates = scheduler.get("candidates")
    if not isinstance(candidates, list) or len(candidates) != 1:
        raise AdmissionBlocked("scheduler_candidate_count")
    candidate = candidates[0]
    if not isinstance(candidate, dict) or candidate.get("task_id") != TASK:
        raise AdmissionBlocked("scheduler_candidate_drift")
    eligible = candidate.get("eligibility")
    if (not isinstance(eligible, dict)
            or eligible.get("task_id") != TASK
            or eligible.get("eligible") is not True
            or eligible.get("reasons") != []):
        raise AdmissionBlocked("scheduler_ineligible")
    model = candidate.get("model")
    if (not isinstance(model, dict) or model.get("profile") != "balanced"
            or model.get("reasoning") != "medium"):
        raise AdmissionBlocked("scheduler_model_drift")
    return {"decision": "D2_ATTEMPT3_SYNTHETIC_SCHEDULER_GO",
            "frozen_task_selected": True, "medium_model": True}


def simulate_ordered_admission(first: dict, next_sample: Callable[[], dict],
                               *, now: datetime, unknown_digest: str) -> dict:
    """Mock-only call boundary: a failed first gate NEVER samples Scheduler."""
    first_quota_gate(first, now=now)
    second = next_sample()
    scheduler_gate(second, now=now, canonical_unknown_digest=unknown_digest)
    return {"decision": GO, "quota_samples_simulated": 2,
            "prepare_dispatched": False, "worker_started": False}


def evidence_hashes(folder: Path) -> dict[str, str]:
    """Att2-only frozen baseline. Does not write a hash file into history."""
    if not folder.is_dir() or folder.is_symlink():
        raise AdmissionBlocked("attempt2_evidence_missing")
    result = {}
    for name in ATTEMPT2_FILES:
        file = folder / name
        if (not file.is_file() or file.is_symlink()
                or file.stat().st_size > 512 * 1024):
            raise AdmissionBlocked("attempt2_evidence_invalid")
        raw = file.read_bytes()
        if not isinstance(json.loads(raw), dict):
            raise AdmissionBlocked("attempt2_evidence_invalid")
        result[name] = hashlib.sha256(raw).hexdigest()
    for forbidden in ("prepare.json", "prepare.stdout.json",
                      "command-metadata.json"):
        if (folder / forbidden).exists() or (folder / forbidden).is_symlink():
            raise AdmissionBlocked("attempt2_dispatch_marker_present")
    return result


def historical_gate() -> dict:
    """Bind both previous attempts without importing their obsolete Preview."""
    from experiments.dogfooding.d2 import d2_ctl_attempt2_offline as old
    from experiments.dogfooding.d2 import d2_ctl_attempt2_prepare_once as prepared
    from experiments.dogfooding.d2 import d2_ctl_attempt2_admission_forensics as forensic

    prior = old.safe_historical_replay()
    if (prior.get("decision") !=
            "D2_ATTEMPT1_FALLBACK_REPLAY_PASS__NO_PROVIDER_CALLS"
            or prior.get("prepare_dispatched") is not False):
        raise AdmissionBlocked("attempt1_provenance_invalid")
    if prepared.bound_offline_evidence() != "D2_ATTEMPT2_OFFLINE_QUALIFICATION_BOUND":
        raise AdmissionBlocked("attempt2_qualification_invalid")
    outcome = forensic.inspect()
    if (outcome.get("decision") !=
            "D2_CTL_ATTEMPT2_ADMISSION_FORENSICS_COMPLETE__READ_ONLY"
            or outcome.get("failure_stage") != "admission"
            or outcome.get("prepare_dispatched") is not False
            or outcome.get("worker_started") is not False
            or outcome.get("candidate_reason_codes") != ["quota_insufficient"]):
        raise AdmissionBlocked("attempt2_history_invalid")
    return {"attempt1_replay": "pass",
            "attempt2_forensics": "pass",
            "attempt2_source_sha256": evidence_hashes(ATTEMPT2)}


def preview(*, expected_head: str) -> dict:
    """Read-only real D2 source and retained history gate. Never live quota."""
    if not isinstance(expected_head, str) or not re.fullmatch(
            r"[0-9a-f]{40}", expected_head):
        raise AdmissionBlocked("research_head_invalid")
    if ATTEMPT3.exists() or ATTEMPT3.is_symlink():
        raise AdmissionBlocked("attempt3_identity_already_used")
    if (os.environ.get("PROJECTCTL_HOME") != str(ROOT / "ctl-home")
            or os.environ.get("BD_ACTOR") != "d2-dogfood-owner"
            or Path(sys.executable).resolve() != (VENV / "bin/python").resolve()):
        raise AdmissionBlocked("isolated_environment_mismatch")

    from experiments.dogfooding.d2 import d2_ctl_readiness as ready
    # Git and Beads READ commands in readiness may update operational caches.
    if ready.git(RESEARCH, "branch", "--show-current") != "research/advisory-skills-eval":
        raise AdmissionBlocked("research_branch_drift")
    if ready.git(RESEARCH, "rev-parse", "HEAD") != expected_head:
        raise AdmissionBlocked("research_head_drift")
    if ready.git(RESEARCH, "status", "--porcelain=v1", "--untracked-files=all"):
        raise AdmissionBlocked("research_checkout_dirty")

    history = historical_gate()
    current = ready.audit()
    if (current.get("decision") !=
            "D2_CTL_READ_ONLY_PREPARE_GATE_PASS__CLAIM_NOT_AUTHORIZED"
            or current.get("ctl_run_count") != 0
            or current.get("beads_task") != "open_unclaimed"
            or current.get("ctl_worktree_clean") is not True
            or current.get("policy_head") != POLICY_HEAD
            or current.get("direct_base") != DIRECT_BASE):
        raise AdmissionBlocked("frozen_state_drift")
    return {
        "decision": PASS, "research_head": expected_head,
        "policy_head": POLICY_HEAD, "task": TASK,
        "attempt3_identity_created": False,
        "attempt2_source_sha256": history["attempt2_source_sha256"],
        "attempt1_provenance": history["attempt1_replay"],
        "attempt2_provenance": history["attempt2_forensics"],
        "ctl_run_count": 0, "beads_task": "open_unclaimed",
        "live_quota_checked": False, "scheduler_queried": False,
        "prepare_dispatched": False, "worker_started": False,
        "next_gate": "SEPARATE_OWNER_APPROVAL_FOR_ATTEMPT3_IMPLEMENTATION_AND_PREPARE",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preview", action="store_true", required=True)
    parser.add_argument("--expected-head", required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(preview(expected_head=args.expected_head),
                         indent=2, sort_keys=True))
        return 0
    except Exception as exc:
        print(json.dumps({
            "decision": "D2_ATTEMPT3_OFFLINE_PREVIEW_BLOCKED",
            "error_type": type(exc).__name__,
            "reason_code": (exc.code if isinstance(exc, AdmissionBlocked)
                            else "unexpected_error"),
            "no_provider_calls": True, "no_prepare_dispatch": True,
        }, sort_keys=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
