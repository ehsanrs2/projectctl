#!/usr/bin/env python3
"""D2 Attempt-2 OFFLINE qualification, before separate owner authorization.

Only --replay-attempt1 and --preview-attempt2 are supported.
No Codex App Server calls, quota refresh, scheduler resampling, Beads claim,
ProjectCTL run prepare/start, evidence writes, retries, source copies, or
integration. Git/Beads *read* checks in readiness may update caches.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys

from projectctl.core.digest import digest
from projectctl.core.errors import ProviderUnavailableError, QuotaError
from projectctl.quota.resolver import unknown_quota_snapshot
from projectctl.schemas.quota import QuotaSnapshot

from experiments.dogfooding.d2 import d2_ctl_readiness as readiness
from experiments.dogfooding.d2.d2_no_inference_preflight import (
    BASE, POLICY_HEAD, ROOT, TASK, VENV,
)

ATTEMPT1 = ROOT / "observations/ctl-prepare-attempt-1"
ATTEMPT2 = ROOT / "observations/ctl-prepare-attempt-2"
REQUIRED = (
    "prepare-summary.json",
    "quota-before-prepare.json",
    "scheduler-before-prepare.json",
)
EXPECTED_ERROR = "Scheduler did not select sole D2 task"
EXPECTED_STATE = "D2_CTL_PREPARE_PRECLAIM_BLOCKED__NO_RETRY"


def read_evidence(root: Path, filename: str) -> tuple[dict, str]:
    path = root / filename
    if (not root.is_dir() or root.is_symlink()
            or not path.is_file() or path.is_symlink()):
        raise ValueError(f"Missing or symlinked historical D2 evidence: {filename}")
    if path.stat().st_size > 512 * 1024:
        raise ValueError(f"Historical D2 evidence file unexpectedly large: {filename}")
    raw = path.read_bytes()
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError(f"Historical D2 evidence is not an object: {filename}")
    return value, hashlib.sha256(raw).hexdigest()


def safe_historical_replay(folder: Path = ATTEMPT1) -> dict:
    """Reconcile only immutable historical JSON; never ask provider/scheduler.

    A digest match proves *which* quota object the scheduler recorded, NOT
    the exact exception class or RPC error that produced the fallback.
    """
    documents = {name: read_evidence(folder, name) for name in REQUIRED}
    summary, quota, scheduler = (documents[name][0] for name in REQUIRED)
    if (summary.get("decision") != EXPECTED_STATE
            or summary.get("reason") != EXPECTED_ERROR
            or summary.get("attempt") != 1
            or summary.get("retries") != 0
            or summary.get("worker_started") is not False
            or (summary.get("prepare_dispatched") is not None
                and summary.get("prepare_dispatched") is not False)
            or summary.get("run_id") is not None
            or "prepare_dispatch_utc" in summary
            or "prepare_exit_code" in summary):
        raise ValueError("Attempt-1 was not a proven pre-dispatch scheduler stop")
    if any((folder / name).exists() or (folder / name).is_symlink()
           for name in ("prepare.json", "prepare.stdout.json")):
        raise ValueError("Attempt-1 contains post-dispatch preparation evidence")
    first = quota.get("snapshot")
    if not isinstance(first, dict):
        raise ValueError("Missing official first quota Snapshot")
    official = QuotaSnapshot.model_validate(first)
    if (quota.get("mode") != "normal" or quota.get("stale") is not False
            or official.provider != "codex_app_server"
            or official.selected_limit_id != "codex"
            or official.ordinary_usage_allowed is not True
            or official.five_hour.source.value != "official"
            or official.weekly.source.value != "official"
            or official.five_hour.confidence.value != "high"
            or official.weekly.confidence.value != "high"):
        raise ValueError("First official quota evidence has unexpected authority")
    eff = quota.get("effective") or {}
    if (not isinstance(eff.get("five_hour"), (float, int))
            or not isinstance(eff.get("weekly"), (float, int))
            or isinstance(eff["five_hour"], bool)
            or isinstance(eff["weekly"], bool)
            or eff["five_hour"] < .18 or eff["weekly"] < .08):
        raise ValueError("First historical quota does not meet frozen MEDIUM admission")
    evaluated = datetime.fromisoformat(
        scheduler["evaluated_at"].replace("Z", "+00:00"))
    if (evaluated.tzinfo is None
            or official.observed_at > evaluated
            or (evaluated - official.observed_at).total_seconds() > 120):
        raise ValueError("Historical quota/Scheduler time sequence inconsistent")
    if (scheduler.get("quota_mode") != "conservation"
            or scheduler.get("selected_task_id") is not None):
        raise ValueError("Historical Scheduler was not blocked by unknown quota")
    candidates = scheduler.get("candidates")
    if (not isinstance(candidates, list) or len(candidates) != 1
            or candidates[0].get("task_id") != TASK
            or candidates[0].get("model") is not None
            or candidates[0].get("eligibility") != {
                "task_id": TASK, "eligible": False,
                "reasons": ["quota_unknown"],
            }):
        raise ValueError("Historical Scheduler candidate does not show quota_unknown")
    unknown = unknown_quota_snapshot(official.account, official.provider)
    scheduler_digest = scheduler.get("quota_snapshot_digest")
    official_digest = digest(official)
    unknown_digest = digest(unknown)
    if scheduler_digest != unknown_digest or scheduler_digest == official_digest:
        raise ValueError("Scheduler digest is not the canonical fail-closed unknown Snapshot")
    return {
        "decision": "D2_ATTEMPT1_FALLBACK_REPLAY_PASS__NO_PROVIDER_CALLS",
        "attempt_1": EXPECTED_STATE,
        "first_quota_mode": "normal",
        "scheduler_quota_mode": "conservation",
        "scheduler_equals_official": False,
        "scheduler_equals_canonical_unknown": True,
        "provider_exception_class": "NOT_RECORDED",
        "prepare_dispatched": False,
        "claim_recorded": False,
        "paid_worker_started": False,
        "source_sha256": {name: documents[name][1] for name in REQUIRED},
        "attempt_2_status": "NOT_STARTED_NOT_AUTHORIZED",
    }


def classify_provider_error(exc: Exception) -> dict:
    """Small pure R&D classifier; never log provider message or credentials."""
    if not isinstance(exc, (QuotaError, ProviderUnavailableError)):
        return {"error_family": "unexpected", "exception_type": type(exc).__name__,
                "fail_closed": True}
    return {"error_family": "quota_provider", "exception_type": type(exc).__name__,
            "fail_closed": True}


def preview_attempt2() -> dict:
    if os.environ.get("PROJECTCTL_HOME") != str(ROOT / "ctl-home"):
        raise ValueError("Wrong D2 projectctl home")
    if os.environ.get("BD_ACTOR") != "d2-dogfood-owner":
        raise ValueError("Wrong D2 Beads actor")
    if Path(sys.executable).resolve() != (VENV / "bin/python").resolve():
        raise ValueError("D2 pinned isolated venv required")
    if ATTEMPT2.exists() or ATTEMPT2.is_symlink():
        raise ValueError("Attempt-2 evidence identity already exists: do not reuse")
    history = safe_historical_replay()
    current = readiness.audit()  # offline/read-only: no provider quota polling
    if (current.get("decision") !=
            "D2_CTL_READ_ONLY_PREPARE_GATE_PASS__CLAIM_NOT_AUTHORIZED"
            or current.get("ctl_run_count") != 0
            or current.get("ctl_worktree_clean") is not True
            or current.get("beads_task") != "open_unclaimed"
            or current.get("policy_head") != POLICY_HEAD
            or current.get("direct_base") != BASE):
        raise ValueError("D2 frozen CTL/Direct fixtures are not available for another Prepare")
    if history["attempt_1"] != EXPECTED_STATE:
        raise ValueError("Attempt-1 provenance is not bound")
    return {
        "decision": "D2_ATTEMPT2_OFFLINE_PREVIEW_PASS__NO_CLAIM_NO_INFERENCE",
        "historical_replay": history["decision"],
        "attempt2_evidence_path_reserved_for_future": str(ATTEMPT2),
        "attempt2_evidence_directory_created": False,
        "ctl_runs": 0,
        "beads_task": "open_unclaimed",
        "readiness": current["decision"],
        "policy_head": POLICY_HEAD,
        "direct_base": BASE,
        "next_gate": "NEW_OWNER_APPROVAL_FOR_ONE_ATTEMPT2_PREPARE_REQUIRED",
        "live_quota_checked": False,
        "run_prepare_called": False,
        "worker_started": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--replay-attempt1", action="store_true")
    mode.add_argument("--preview-attempt2", action="store_true")
    args = parser.parse_args()
    try:
        output = (safe_historical_replay() if args.replay_attempt1
                  else preview_attempt2())
    except Exception as exc:
        print(json.dumps({
            "decision": "D2_ATTEMPT2_OFFLINE_QUALIFICATION_BLOCKED",
            "error_type": type(exc).__name__,
            "reason": str(exc)[:300],
            "no_model_calls": True, "no_claims": True,
        }, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps(output, sort_keys=True, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
