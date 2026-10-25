#!/usr/bin/env python3
"""D2 Attempt-3 isolated one-shot Prepare candidate. NOT LIVE-AUTHORIZED.

Preview is read-only (Git/Beads reads can update operational caches).
Only separately owner-authorized --prepare may sample live quota/Scheduler
and, after both independently qualify, create one Run/Claim/Worktree.
There is NO worker execution path and NO automatic retry.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

import yaml

from experiments.dogfooding.d2 import d2_ctl_attempt3_offline as offline
from experiments.dogfooding.d2 import d2_ctl_prepare_once as old
from experiments.dogfooding.d2.d2_no_inference_preflight import (
    ROOT, RESEARCH, CTL, DIRECT, VENV, POLICY_HEAD, TASK, validate_strategy,
)
from projectctl.core.digest import digest
from projectctl.project.loader import load_project_config
from projectctl.quota.resolver import unknown_quota_snapshot
from projectctl.schemas.quota import QuotaSnapshot

OUT = offline.ATTEMPT3
OFFLINE = ROOT / "observations/ctl-attempt3-offline-qualification"
QUALIFIED_SHA = "c9cafddd1b0973b3e6fbb83ca1caa760928edd38"
ACK = "D2_ATTEMPT3_ONE_PREPARE_NO_WORKER"
BLOCKED = "D2_CTL_ATTEMPT3_PRECLAIM_BLOCKED__NO_RETRY"
AMBIGUOUS = "D2_CTL_ATTEMPT3_DISPATCHED_NEEDS_RECONCILIATION__NO_RETRY"
PASS = "D2_CTL_ATTEMPT3_PREPARE_PASS__WORKER_NOT_STARTED"


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_bytes(path: Path, *, limit: int = 2_000_000) -> bytes:
    if (path.is_symlink() or not path.is_file()
            or path.stat().st_size > limit):
        raise ValueError("Missing, symlinked, or unbounded evidence")
    return path.read_bytes()


def offline_bound() -> dict:
    """Verify one-time qualification including its content SHA manifest."""
    if OFFLINE.is_symlink() or not OFFLINE.is_dir():
        raise ValueError("Attempt-3 qualification evidence missing")
    record = dict(line.split("=", 1)
                  for line in read_bytes(OFFLINE / "result.txt").decode().splitlines()
                  if "=" in line)
    expected = {
        "decision": "D2_ATTEMPT3_OFFLINE_QUALIFIED__PREPARE_NOT_AUTHORIZED",
        "last_step": "complete", "exit_code": "0",
        "research_commit": QUALIFIED_SHA,
        "attempt3_prepare_dispatched": "false", "paid_worker_started": "false",
    }
    if any(record.get(k) != v for k, v in expected.items()):
        raise ValueError("Offline Attempt-3 qualification result drift")
    lines = read_bytes(OFFLINE / "FILE_SHA256.txt").decode().splitlines()
    if not 7 <= len(lines) <= 24:
        raise ValueError("Invalid qualification manifest size")
    verified = set()
    for line in lines:
        match = re.fullmatch(r"([0-9a-f]{64})  \./([A-Za-z0-9_.-]+)", line)
        if (not match or match[2] in verified or
                match[2] == "FILE_SHA256.txt"):
            raise ValueError("Invalid qualification manifest entry")
        if hashlib.sha256(read_bytes(OFFLINE / match[2])).hexdigest() != match[1]:
            raise ValueError("Qualification evidence hash changed")
        verified.add(match[2])
    required = {"result.txt", "preview.json", "tests.stderr.log",
                "attempt1-before.sha256", "attempt2-before.sha256"}
    if not required.issubset(verified):
        raise ValueError("Required qualification files unbound")
    tests = read_bytes(OFFLINE / "tests.stderr.log").decode()
    if not re.search(r"^Ran 36 tests? in ", tests, re.MULTILINE) or not re.search(
            r"^OK$", tests, re.MULTILINE):
        raise ValueError("Qualification synthetic tests not proven")
    previous_preview = json.loads(read_bytes(OFFLINE / "preview.json"))
    if (previous_preview.get("decision") != offline.PASS
            or previous_preview.get("research_head") != QUALIFIED_SHA
            or previous_preview.get("prepare_dispatched") is not False
            or previous_preview.get("live_quota_checked") is not False
            or previous_preview.get("worker_started") is not False):
        raise ValueError("Qualification preview invalid")
    for attempt in (1, 2):
        manifest = read_bytes(OFFLINE / f"attempt{attempt}-before.sha256").decode()
        lines = manifest.splitlines()
        if len(lines) != 3:
            raise ValueError("Historical attempt manifest incomplete")
        names = set()
        folder = ROOT / f"observations/ctl-prepare-attempt-{attempt}"
        if not folder.is_dir() or folder.is_symlink():
            raise ValueError("Historical attempt directory unavailable")
        for line in lines:
            match = re.fullmatch(r"([0-9a-f]{64})  ([A-Za-z0-9_.-]+)", line)
            if not match or match[2] in names:
                raise ValueError("Invalid historical attempt manifest")
            if hashlib.sha256(read_bytes(folder / match[2])).hexdigest() != match[1]:
                raise ValueError("Historical attempt evidence changed")
            names.add(match[2])
        if names != set(offline.ATTEMPT2_FILES):
            raise ValueError("Historical attempt input set drift")
    if previous_preview.get("attempt2_source_sha256") != offline.evidence_hashes(
            offline.ATTEMPT2):
        raise ValueError("Historical Attempt-2 preview hashes changed")
    return {"qualification": "D2_ATTEMPT3_OFFLINE_EVIDENCE_BOUND",
            "qualified_source_sha": QUALIFIED_SHA}


def preview(expected_head: str) -> dict:
    if (not isinstance(expected_head, str)
            or not re.fullmatch(r"[0-9a-f]{40}", expected_head)):
        raise ValueError("Exact reviewed research SHA required")
    if OUT.exists() or OUT.is_symlink():
        raise ValueError("Attempt-3 live evidence identity already used: NO RETRY")
    qualified = offline_bound()
    source = offline.preview(expected_head=expected_head)
    if (source.get("decision") != offline.PASS
            or source.get("ctl_run_count") != 0
            or source.get("beads_task") != "open_unclaimed"):
        raise ValueError("Frozen CTL readiness rejected Attempt 3")
    target = old.git(CTL, "branch", "--show-current")
    if (not target or target == "HEAD"
            or old.git(CTL, "rev-parse", target) != POLICY_HEAD):
        raise ValueError("Frozen integration target drift")
    return {
        "decision": "D2_ATTEMPT3_PREPARE_PREVIEW_PASS__NO_CLAIM_NO_INFERENCE",
        "research_head": expected_head, "target": target,
        "task": TASK, **qualified,
        "live_quota_checked": False, "prepare_dispatched": False,
        "worker_started": False, "claim_created": False,
    }


def first_admission(quota: dict, now: datetime) -> dict:
    """Validate real snapshot schema, then apply the frozen five-hour-first gate."""
    if not isinstance(quota, dict):
        raise offline.AdmissionBlocked("quota_missing_or_invalid")
    try:
        snapshot = QuotaSnapshot.model_validate(quota["snapshot"])
    except (ValueError, TypeError, KeyError) as exc:
        raise offline.AdmissionBlocked("quota_schema_invalid") from exc
    offline.first_quota_gate(quota, now=now)
    # Effective numbers must match account/project quota policy, not fake JSON.
    config = load_project_config(CTL)
    for name in ("five_hour", "weekly"):
        observed = getattr(snapshot, name).remaining_ratio
        reserve = getattr(config.quota.reserve, name)
        expected = max(0.0, float(observed) - float(reserve))
        effective = quota["effective"][name]
        if abs(float(effective) - expected) > 1e-7:
            raise offline.AdmissionBlocked("quota_effective_policy_mismatch")
    return {"snapshot": snapshot, "validated": True}


def second_admission(scheduler: dict, snap: QuotaSnapshot, *,
                     now: datetime) -> None:
    unknown = digest(unknown_quota_snapshot(snap.account, snap.provider))
    offline.scheduler_gate(scheduler, now=now,
                           canonical_unknown_digest=unknown)
    config = load_project_config(CTL)
    if (scheduler.get("project_id") != config.project.id
            or scheduler.get("config_digest") != digest(config)):
        raise offline.AdmissionBlocked("scheduler_project_or_policy_drift")


def store(name: str, obj: object) -> None:
    (OUT / name).write_text(
        json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def preflight_again(initial: dict) -> None:
    from experiments.dogfooding.d2 import d2_ctl_readiness as readiness
    audit = readiness.audit()
    if (audit.get("decision") !=
            "D2_CTL_READ_ONLY_PREPARE_GATE_PASS__CLAIM_NOT_AUTHORIZED"
            or audit.get("ctl_run_count") != 0
            or audit.get("beads_task") != "open_unclaimed"
            or old.git(RESEARCH, "rev-parse", "HEAD") != initial["research_head"]
            or old.git(CTL, "branch", "--show-current") != initial["target"]
            or old.git(CTL, "rev-parse", initial["target"]) != POLICY_HEAD
            or old.git(RESEARCH, "status", "--porcelain=v1", "--untracked-files=all")):
        raise ValueError("Readiness changed before one Prepare dispatch")


def postflight(stdout: str, initial: dict) -> dict:
    payload = json.loads(stdout)
    if not isinstance(payload, dict) or not all(
            isinstance(payload.get(k), dict) for k in ("plan", "run", "worktree")):
        raise ValueError("Malformed Prepare result")
    store("prepare.json", payload)
    run_id = payload["run"].get("run_id")
    if isinstance(run_id, str) and run_id.startswith("run-"):
        store("run-id.json", {"run_id": run_id})
    checked = old.check_preparation(payload["plan"], payload["run"],
                                    payload["worktree"], target=initial["target"])
    show = json.loads(old.run_read([
        str(VENV / "bin/projectctl"), "run", "show", checked["run_id"],
        "--project", str(CTL), "--json"]))
    store("run-show-after-prepare.json", show)
    if (show.get("run", {}).get("run_id") != checked["run_id"]
            or show["run"].get("status") != "claimed"):
        raise ValueError("RunStore postflight invalid")
    runs = json.loads(old.run_read([
        str(VENV / "bin/projectctl"), "runs", "--project", str(CTL), "--json"]))
    store("runs-after-prepare.json", runs)
    if (not isinstance(runs, list) or len(runs) != 1
            or runs[0].get("run_id") != checked["run_id"]):
        raise ValueError("Unexpected RunStore inventory")
    task = old.parse_task(json.loads(old.run_read([
        "bd", "-C", str(CTL), "show", TASK, "--json"])))
    store("task-after-prepare.json", task)
    if task.get("status") != "in_progress" or not task.get("assignee"):
        raise ValueError("Task not exclusively claimed")
    direct_status = (
        ROOT / "observations/direct-attempt-1/direct-git-status.txt"
    ).read_text(encoding="utf-8").rstrip("\n")
    if old.git(DIRECT, "status", "--short", "--untracked-files=all") != direct_status:
        raise ValueError("Direct arm status changed")
    offline_bound()
    return checked


def prepare_once(initial: dict) -> dict:
    """One fresh official quota, at most one independent Scheduler, one Prepare."""
    os.umask(0o077)
    OUT.mkdir(mode=0o700)  # exclusive, permanently consumes Attempt-3 identity
    began = time.monotonic_ns()
    stage = "initial"
    dispatched = False
    result = {
        "decision": "D2_CTL_ATTEMPT3_IN_PROGRESS",
        "attempt": 3, "retries": 0, "prepare_dispatched": False,
        "worker_started": False, "run_id": None,
        "started_utc": utc(), "preview": initial,
    }
    store("prepare-summary.json", result)
    try:
        stage = "first_quota"
        raw = json.loads(old.run_read([
            str(VENV / "bin/projectctl"), "quota", "--project", str(CTL),
            "--json"]))
        store("quota-before-prepare.json", raw)
        validated = first_admission(raw, datetime.now(timezone.utc))

        # A blocked FIRST quota must not trigger a SECOND provider request.
        stage = "scheduler"
        scheduler = json.loads(old.run_read([
            str(VENV / "bin/projectctl"), "next", "--project", str(CTL),
            "--json"]))
        store("scheduler-before-prepare.json", scheduler)
        second_admission(scheduler, validated["snapshot"],
                         now=datetime.now(timezone.utc))
        stage = "capabilities"
        capabilities = json.loads(old.run_read([
            str(VENV / "bin/projectctl"), "worker", "capabilities",
            "--provider", "codex", "--json"]))
        strategy = json.loads(old.run_read([
            str(VENV / "bin/projectctl"), "worker", "strategy", TASK,
            "--project", str(CTL), "--provider", "codex", "--requested",
            "direct", "--json"]))
        validate_strategy(capabilities, strategy)
        store("capabilities-before-prepare.json", capabilities)
        store("strategy-before-prepare.json", strategy)

        stage = "final_gates"
        preflight_again(initial)
        first_admission(raw, datetime.now(timezone.utc))
        second_admission(scheduler, validated["snapshot"],
                         now=datetime.now(timezone.utc))
        command = [
            str(VENV / "bin/projectctl"), "run", "prepare",
            "--strategy", "direct", "--target", initial["target"],
            "--project", str(CTL), "--json",
        ]
        store("command-metadata.json", {
            "command_kind": "one_prepare", "task": TASK,
            "strategy": "direct", "worker_execution": "FORBIDDEN",
        })

        # Persist conservative single-use intent BEFORE any subprocess.
        stage = "dispatch_intent"
        result["prepare_dispatched"] = True
        result["prepare_dispatch_intent_utc"] = utc()
        store("prepare-summary.json", result)
        dispatched = True
        stage = "prepare_command"
        tick = time.monotonic_ns()
        try:
            proc = subprocess.run(command, cwd=RESEARCH, capture_output=True,
                                  text=True, timeout=180, check=False)
            stdout, stderr, code = proc.stdout, proc.stderr, proc.returncode
        except subprocess.TimeoutExpired:
            result["timed_out"] = True
            stdout, stderr, code = "", "", 124
        result["prepare_exit_code"] = code
        result["prepare_wall_monotonic_seconds"] = (
            time.monotonic_ns() - tick) / 1e9
        (OUT / "prepare.stdout.json").write_text(stdout, encoding="utf-8")
        (OUT / "prepare.stderr.log").write_text(stderr, encoding="utf-8")
        if code != 0:
            raise ValueError("One Prepare failed or timed out: NO RETRY")

        stage = "postflight"
        checked = postflight(stdout, initial)
        result["run_id"] = checked["run_id"]
        result["prepared"] = checked
        result["decision"] = PASS
    except Exception as exc:
        result["decision"] = AMBIGUOUS if dispatched else BLOCKED
        result["error_type"] = type(exc).__name__
        result["failure_stage"] = stage
        result["reason_code"] = (
            exc.code if isinstance(exc, offline.AdmissionBlocked)
            else "redacted")
    finally:
        result["finished_utc"] = utc()
        result["total_wall_monotonic_seconds"] = (
            time.monotonic_ns() - began) / 1e9
        store("prepare-summary.json", result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--preview", action="store_true")
    mode.add_argument("--prepare", action="store_true")
    parser.add_argument("--expected-head", required=True)
    parser.add_argument("--ack-claim", action="store_true")
    parser.add_argument("--approval-phrase")
    args = parser.parse_args()
    if args.prepare and (not args.ack_claim or args.approval_phrase != ACK):
        parser.error("Separate owner approval and both acknowledgements required")
    if args.preview and (args.ack_claim or args.approval_phrase):
        parser.error("Preview does not accept Prepare acknowledgement")
    try:
        initial = preview(args.expected_head)
        if args.preview:
            print(json.dumps(initial, indent=2, sort_keys=True))
            return 0
        output = prepare_once(initial)
        print(json.dumps({
            "decision": output["decision"],
            "attempt": 3, "run_id": output.get("run_id"),
            "failure_stage": output.get("failure_stage"),
            "reason_code": output.get("reason_code"),
            "prepare_dispatched": output["prepare_dispatched"],
            "worker_started": False,
        }, sort_keys=True, indent=2))
        return 0 if output["decision"] == PASS else 2
    except Exception as exc:
        print(json.dumps({
            "decision": "D2_ATTEMPT3_PREVIEW_BLOCKED__NO_DISPATCH",
            "error_type": type(exc).__name__,
            "attempt3_identity_exists": OUT.exists() or OUT.is_symlink(),
            "worker_started": False,
        }, sort_keys=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
