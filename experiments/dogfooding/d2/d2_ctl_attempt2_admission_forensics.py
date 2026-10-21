#!/usr/bin/env python3
"""D2 Attempt-2 retained-evidence-only admission forensics: no live calls or writes."""
from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import sys

ROOT = Path.home() / ".local/state/projectctl-dogfood-d2/observations/ctl-prepare-attempt-2"
TASK = "d2ctl-g4q"
NAMES = ("prepare-summary.json", "quota-before-prepare.json",
         "scheduler-before-prepare.json")
EXPECTED = "D2_CTL_ATTEMPT2_PRECLAIM_BLOCKED__NO_RETRY"


def read_json(folder: Path, name: str) -> dict:
    if not folder.is_dir() or folder.is_symlink():
        raise ValueError("Attempt-2 evidence directory missing or symlinked")
    f = folder / name
    if not f.is_file() or f.is_symlink() or f.stat().st_size > 512 * 1024:
        raise ValueError("Missing, symlinked or oversized evidence")
    value = json.loads(f.read_bytes())
    if not isinstance(value, dict):
        raise ValueError("Evidence is not a JSON object")
    return value


def relation(quota: dict, scheduler: dict) -> str:
    """Derive synthetic unknown digest without exposing account or raw payload."""
    from projectctl.core.digest import digest
    from projectctl.quota.resolver import unknown_quota_snapshot
    from projectctl.schemas.quota import QuotaSnapshot

    observed = scheduler.get("quota_snapshot_digest")
    if not isinstance(observed, str) or not observed:
        return "missing"
    try:
        official = QuotaSnapshot.model_validate(quota["snapshot"])
        unknown = unknown_quota_snapshot(official.account, official.provider)
        if digest(unknown) == observed:
            return "canonical_unknown"
        if digest(official) == observed:
            return "same_as_first_official"
    except (KeyError, ValueError, TypeError):
        return "indeterminate"
    return "different_snapshot_or_unclassified"


def valid_ratio(value: object, threshold: float) -> bool:
    return type(value) in (float, int) and value == value and value >= threshold


def analyze(summary: dict, quota: dict, scheduler: dict, identity: str) -> dict:
    if (summary.get("decision") != EXPECTED
            or summary.get("failure_stage") != "admission"
            or summary.get("attempt") != 2
            or summary.get("retries") != 0
            or summary.get("worker_started") is not False
            or summary.get("prepare_dispatched") is not False
            or summary.get("run_id") is not None
            or "prepare_dispatch_intent_utc" in summary):
        raise ValueError("Unexpected Attempt-2 state; manual reconciliation required")
    snap = quota.get("snapshot") or {}
    eff = quota.get("effective") or {}
    if not isinstance(snap, dict) or not isinstance(eff, dict):
        raise ValueError("Malformed saved quota")
    candidates = scheduler.get("candidates")
    item = (candidates[0] if isinstance(candidates, list)
            and len(candidates) == 1
            and isinstance(candidates[0], dict) else {})
    elig = item.get("eligibility") or {}
    if not isinstance(elig, dict):
        elig = {}
    model = item.get("model") or {}
    if not isinstance(model, dict):
        model = {}
    reasons = elig.get("reasons", [])
    if not isinstance(reasons, list):
        reasons = []
    allowed = {"quota_unknown", "quota_insufficient", "quota_stale"}
    codes = sorted(set(r if isinstance(r, str) and r in allowed else "other"
                       for r in reasons))
    checks = {
        "first_quota_official_normal": (
            quota.get("mode") == "normal"
            and quota.get("stale") is False
            and snap.get("provider") == "codex_app_server"
            and snap.get("selected_limit_id") == "codex"
            and snap.get("ordinary_usage_allowed") is True
            and all(isinstance(snap.get(w), dict)
                    and snap[w].get("source") == "official"
                    and snap[w].get("confidence") == "high"
                    for w in ("five_hour", "weekly"))),
        "five_hour_medium_floor": valid_ratio(eff.get("five_hour"), .18),
        "weekly_medium_floor": valid_ratio(eff.get("weekly"), .08),
        "scheduler_normal_selected": (
            scheduler.get("quota_mode") == "normal"
            and scheduler.get("selected_task_id") == TASK),
        "sole_task_eligible": (
            isinstance(candidates, list) and len(candidates) == 1
            and item.get("task_id") == TASK
            and elig.get("eligible") is True and reasons == []),
        "model_profile_medium": (
            model.get("profile") == "balanced"
            and model.get("reasoning") == "medium"),
    }
    try:
        observed = datetime.fromisoformat(
            snap["observed_at"].replace("Z", "+00:00"))
        ended = datetime.fromisoformat(
            summary["finished_utc"].replace("Z", "+00:00"))
        age_at_finish = round((ended - observed).total_seconds(), 2)
    except (KeyError, ValueError, TypeError):
        age_at_finish = None
    return {
        "decision": "D2_CTL_ATTEMPT2_ADMISSION_FORENSICS_COMPLETE__READ_ONLY",
        "attempt": 2, "failure_stage": "admission",
        "prepare_dispatched": False, "worker_started": False,
        "run_id": None,
        "first_quota_mode": quota.get("mode") if quota.get("mode") in
            ("normal", "conservation") else "other_or_missing",
        "scheduler_quota_mode": scheduler.get("quota_mode")
            if scheduler.get("quota_mode") in ("normal", "conservation")
            else "other_or_missing",
        "scheduler_digest_relation_to_first_quota": identity,
        "scheduler_selected_frozen_task": scheduler.get("selected_task_id") == TASK,
        "candidate_count": len(candidates) if isinstance(candidates, list) else None,
        "candidate_reason_codes": codes,
        "checks": checks,
        "failed_checks": [key for key, ok in checks.items() if not ok],
        "quota_age_at_finish_seconds_approximate": age_at_finish,
        "exact_provider_exception": "NOT_RECORDED",
        "no_provider_calls": True, "no_writes": True,
    }


def inspect(folder: Path = ROOT) -> dict:
    data = {name: read_json(folder, name) for name in NAMES}
    if any((folder / name).exists() or (folder / name).is_symlink()
           for name in ("prepare.json", "prepare.stdout.json",
                        "command-metadata.json")):
        raise ValueError("Unexpected dispatch evidence; manual reconciliation")
    return analyze(data[NAMES[0]], data[NAMES[1]], data[NAMES[2]],
                   relation(data[NAMES[1]], data[NAMES[2]]))


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--inspect", action="store_true", required=True)
    p.parse_args()
    try:
        result = inspect()
    except Exception as error:
        print(json.dumps({
            "decision": "D2_CTL_ATTEMPT2_FORENSICS_BLOCKED__NO_RETRY",
            "error_type": type(error).__name__, "no_provider_calls": True,
        }), file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
