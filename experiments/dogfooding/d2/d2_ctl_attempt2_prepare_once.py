#!/usr/bin/env python3
"""D2 Attempt-2 one-shot Prepare harness. Source presence is NOT execution approval."""
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

from experiments.dogfooding.d2 import d2_ctl_attempt2_offline as historical
from experiments.dogfooding.d2 import d2_ctl_prepare_once as old
from experiments.dogfooding.d2.d2_direct_manual import validate_admission
from experiments.dogfooding.d2.d2_no_inference_preflight import (
    ROOT, RESEARCH, CTL, DIRECT, VENV, POLICY_HEAD, TASK, validate_strategy,
)
from projectctl.core.digest import digest
from projectctl.quota.resolver import unknown_quota_snapshot
from projectctl.schemas.quota import QuotaSnapshot

OUT = ROOT / "observations/ctl-prepare-attempt-2"
OFFLINE = ROOT / "observations/ctl-attempt2-offline-qualification"
ATTEMPT1 = ROOT / "observations/ctl-prepare-attempt-1"
QUALIFIED_HEAD = "313f96537a4a18ac93f38e837a3032bbbcac5128"
ACK = "D2_ATTEMPT2_ONE_PREPARE_NO_WORKER"
SUCCESS = "D2_CTL_ATTEMPT2_PREPARE_PASS__WORKER_NOT_STARTED"


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def read_file(path, limit=2_000_000):
    if not path.is_file() or path.is_symlink() or path.stat().st_size > limit:
        raise ValueError("Missing, symlinked or oversized evidence")
    return path.read_bytes()


def bound_offline_evidence():
    if not OFFLINE.is_dir() or OFFLINE.is_symlink():
        raise ValueError("Offline qualification missing")
    record = dict(x.split("=", 1) for x in
                  read_file(OFFLINE / "result.txt").decode().splitlines() if "=" in x)
    if (record.get("decision") !=
            "D2_ATTEMPT2_OFFLINE_QUALIFIED__PREPARE_NOT_AUTHORIZED"
            or record.get("research_commit") != QUALIFIED_HEAD
            or record.get("exit_code") != "0"
            or record.get("last_step") != "complete"
            or record.get("attempt2_prepare_dispatched") != "false"
            or record.get("paid_worker_started") != "false"):
        raise ValueError("Offline qualification did not pass")
    manifest = read_file(OFFLINE / "FILE_SHA256.txt").decode().splitlines()
    verified = set()
    if not 5 <= len(manifest) <= 30:
        raise ValueError("Offline evidence manifest missing or unbounded")
    for line in manifest:
        m = re.fullmatch(r"([0-9a-f]{64})  \./([A-Za-z0-9_.-]+)", line)
        if not m or m[2] in verified or m[2] == "FILE_SHA256.txt":
            raise ValueError("Offline manifest entry invalid")
        if hashlib.sha256(read_file(OFFLINE / m[2])).hexdigest() != m[1]:
            raise ValueError("Offline qualification evidence digest drift")
        verified.add(m[2])
    if not {"result.txt", "preview.json", "replay.json",
            "tests.stderr.log", "attempt1-input-sha256.txt"}.issubset(verified):
        raise ValueError("Required offline qualification evidence not bound")
    if "Ran 23 tests in " not in read_file(OFFLINE / "tests.stderr.log").decode():
        raise ValueError("Synthetic offline tests not confirmed")
    replay = json.loads(read_file(OFFLINE / "replay.json"))
    preview = json.loads(read_file(OFFLINE / "preview.json"))
    if (replay.get("decision") !=
            "D2_ATTEMPT1_FALLBACK_REPLAY_PASS__NO_PROVIDER_CALLS"
            or preview.get("decision") !=
            "D2_ATTEMPT2_OFFLINE_PREVIEW_PASS__NO_CLAIM_NO_INFERENCE"):
        raise ValueError("Offline replay or preview decision drift")
    originals = set(historical.REQUIRED)
    rows = read_file(OFFLINE / "attempt1-input-sha256.txt").decode().splitlines()
    if len(rows) != len(originals):
        raise ValueError("Attempt-1 input manifest incomplete")
    for line in rows:
        m = re.fullmatch(r"([0-9a-f]{64})  ([A-Za-z0-9_.-]+)", line)
        if not m or m[2] not in originals:
            raise ValueError("Attempt-1 integrity entry invalid")
        originals.remove(m[2])
        if (hashlib.sha256(read_file(ATTEMPT1 / m[2])).hexdigest() != m[1]
                or replay.get("source_sha256", {}).get(m[2]) != m[1]):
            raise ValueError("Historical Attempt-1 input hash changed")
    return "D2_ATTEMPT2_OFFLINE_QUALIFICATION_BOUND"


def preview(expected_head):
    if not re.fullmatch(r"[0-9a-f]{40}", expected_head):
        raise ValueError("Exact research SHA required")
    if OUT.exists() or OUT.is_symlink():
        raise ValueError("Attempt-2 evidence path already exists: NO RETRY")
    if (os.environ.get("PROJECTCTL_HOME") != str(ROOT / "ctl-home")
            or os.environ.get("BD_ACTOR") != "d2-dogfood-owner"
            or Path(sys.executable).resolve() != (VENV / "bin/python").resolve()):
        raise ValueError("Wrong isolated D2 execution environment")
    if old.git(RESEARCH, "branch", "--show-current") != "research/advisory-skills-eval":
        raise ValueError("Research branch mismatch")
    if old.git(RESEARCH, "rev-parse", "HEAD") != expected_head:
        raise ValueError("Research HEAD not operator-pinned")
    if old.git(RESEARCH, "status", "--porcelain=v1", "--untracked-files=all"):
        raise ValueError("Research worktree not clean")
    qualified = bound_offline_evidence()
    ready = historical.preview_attempt2()  # Read-only: no provider/claim
    if (ready["decision"] !=
            "D2_ATTEMPT2_OFFLINE_PREVIEW_PASS__NO_CLAIM_NO_INFERENCE"
            or ready["ctl_runs"] != 0 or ready["beads_task"] != "open_unclaimed"):
        raise ValueError("CTL frozen readiness changed")
    target = old.git(CTL, "branch", "--show-current")
    if (not target or target == "HEAD"
            or old.git(CTL, "rev-parse", target) != POLICY_HEAD):
        raise ValueError("Frozen integration branch drift")
    return {"decision": "D2_ATTEMPT2_PREPARE_PREVIEW_PASS__NO_CLAIM_NO_INFERENCE",
            "target": target, "research_head": expected_head,
            "qualification": qualified, "task": TASK,
            "claim_created": False, "worker_started": False}


def admission(quota, scheduler):
    selected = validate_admission(quota, scheduler, now=datetime.now(timezone.utc))
    snap = QuotaSnapshot.model_validate(quota["snapshot"])
    unknown = digest(unknown_quota_snapshot(snap.account, snap.provider))
    received = scheduler.get("quota_snapshot_digest")
    if not isinstance(received, str) or not received or received == unknown:
        raise ValueError("Scheduler quota unknown or digest missing")
    return selected


def store(name, obj):
    (OUT / name).write_text(json.dumps(obj, sort_keys=True, indent=2) + "\n")


def prepare_once(initial):
    # Single-use identity must be created before any potentially mutating operation.
    os.umask(0o077)
    OUT.mkdir(mode=0o700)
    started = time.monotonic_ns()
    status = {"decision": "D2_CTL_ATTEMPT2_PREPARE_IN_PROGRESS",
              "attempt": 2, "retries": 0, "worker_started": False,
              "prepare_dispatched": False, "started_utc": timestamp(),
              "preview": initial}
    store("prepare-summary.json", status)
    dispatched = False
    stage = "quota"
    try:
        quota = json.loads(old.run_read([
            str(VENV / "bin/projectctl"), "quota", "--project", str(CTL), "--json"]))
        store("quota-before-prepare.json", quota)
        stage = "scheduler"
        scheduler = json.loads(old.run_read([
            str(VENV / "bin/projectctl"), "next", "--project", str(CTL), "--json"]))
        store("scheduler-before-prepare.json", scheduler)
        stage = "admission"
        status["admission"] = admission(quota, scheduler)
        stage = "capabilities"
        caps = json.loads(old.run_read([
            str(VENV / "bin/projectctl"), "worker", "capabilities",
            "--provider", "codex", "--json"]))
        strategy = json.loads(old.run_read([
            str(VENV / "bin/projectctl"), "worker", "strategy", TASK,
            "--project", str(CTL), "--provider", "codex",
            "--requested", "direct", "--json"]))
        validate_strategy(caps, strategy)
        store("capabilities-before-prepare.json", caps)
        store("strategy-before-prepare.json", strategy)
        stage = "last_readiness"
        again = historical.preview_attempt2()
        if (again["decision"] !=
            "D2_ATTEMPT2_OFFLINE_PREVIEW_PASS__NO_CLAIM_NO_INFERENCE"
            or old.git(RESEARCH, "rev-parse", "HEAD") != initial["research_head"]
            or old.git(CTL, "branch", "--show-current") != initial["target"]):
            raise ValueError("Frozen readiness changed")
        stage = "last_admission"
        status["admission"] = admission(quota, scheduler)
        command = [str(VENV / "bin/projectctl"), "run", "prepare",
                   "--strategy", "direct", "--target", initial["target"],
                   "--project", str(CTL), "--json"]
        store("command-metadata.json", {
            "argv": command, "model_execution": "FORBIDDEN", "task": TASK})
        stage = "dispatch_intent"
        status["prepare_dispatched"] = True  # conservative intent marker
        status["prepare_dispatch_intent_utc"] = timestamp()
        store("prepare-summary.json", status)
        dispatched = True
        stage = "prepare_command"
        t = time.monotonic_ns()
        try:
            proc = subprocess.run(command, cwd=RESEARCH, capture_output=True,
                                  text=True, timeout=180, check=False)
            stdout, stderr, rc = proc.stdout, proc.stderr, proc.returncode
        except subprocess.TimeoutExpired as exc:
            stdout, stderr, rc = exc.stdout or "", exc.stderr or "", 124
            if isinstance(stdout, bytes):
                stdout = stdout.decode("utf-8", "replace")
            if isinstance(stderr, bytes):
                stderr = stderr.decode("utf-8", "replace")
            status["timed_out"] = True
        status["prepare_wall_monotonic_seconds"] = (
            time.monotonic_ns() - t) / 1e9
        status["prepare_exit_code"] = rc
        (OUT / "prepare.stdout.json").write_text(stdout)
        (OUT / "prepare.stderr.log").write_text(stderr)
        if rc != 0:
            raise ValueError("Prepare failed or timed out: NO RETRY")
        stage = "postflight"
        payload = json.loads(stdout)
        store("prepare.json", payload)
        if not all(isinstance(payload.get(k), dict)
                   for k in ("plan", "run", "worktree")):
            raise ValueError("Malformed Prepare response")
        status["run_id"] = payload["run"].get("run_id")
        store("prepare-summary.json", status)
        checked = old.check_preparation(
            payload["plan"], payload["run"], payload["worktree"],
            target=initial["target"])
        shown = json.loads(old.run_read([
            str(VENV / "bin/projectctl"), "run", "show", checked["run_id"],
            "--project", str(CTL), "--json"]))
        store("run-show-after-prepare.json", shown)
        if (shown.get("run", {}).get("run_id") != checked["run_id"]
                or shown["run"].get("status") != "claimed"):
            raise ValueError("RunStore state mismatch")
        runs = json.loads(old.run_read([
            str(VENV / "bin/projectctl"), "runs", "--project", str(CTL), "--json"]))
        store("runs-after-prepare.json", runs)
        if (not isinstance(runs, list) or len(runs) != 1
                or runs[0].get("run_id") != checked["run_id"]):
            raise ValueError("Unexpected run inventory")
        task = old.parse_task(json.loads(old.run_read([
            "bd", "-C", str(CTL), "show", TASK, "--json"])))
        store("task-after-prepare.json", task)
        if task.get("status") != "in_progress" or not task.get("assignee"):
            raise ValueError("Task was not claimed")
        direct_status = (ROOT / "observations/direct-attempt-1/direct-git-status.txt"
                        ).read_text().rstrip("\n")
        if old.git(DIRECT, "status", "--short", "--untracked-files=all") != direct_status:
            raise ValueError("Direct arm changed")
        bound_offline_evidence()
        status["decision"] = SUCCESS
        status["prepared"] = checked
    except Exception as exc:
        status["decision"] = (
            "D2_CTL_ATTEMPT2_DISPATCHED_NEEDS_RECONCILIATION__NO_RETRY"
            if dispatched else "D2_CTL_ATTEMPT2_PRECLAIM_BLOCKED__NO_RETRY")
        status["error_type"] = type(exc).__name__
        status["failure_stage"] = stage  # never expose raw provider error
    finally:
        status["finished_utc"] = timestamp()
        status["total_wall_monotonic_seconds"] = (
            time.monotonic_ns() - started) / 1e9
        store("prepare-summary.json", status)
    return status


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--preview", action="store_true")
    modes.add_argument("--prepare", action="store_true")
    parser.add_argument("--expected-head", required=True)
    parser.add_argument("--ack-claim", action="store_true")
    parser.add_argument("--approval-phrase")
    args = parser.parse_args()
    if args.prepare and (not args.ack_claim or args.approval_phrase != ACK):
        parser.error("Prepare requires separate owner approval plus both ack gates")
    if args.preview and (args.ack_claim or args.approval_phrase):
        parser.error("Preview cannot claim")
    try:
        initial = preview(args.expected_head)
        if args.preview:
            print(json.dumps(initial, indent=2, sort_keys=True))
            return 0
        result = prepare_once(initial)
        print(json.dumps({
            "decision": result["decision"],
            "run_id": result.get("run_id"),
            "prepare_dispatched": result["prepare_dispatched"],
            "worker_started": False, "attempt": 2,
            "failure_stage": result.get("failure_stage"),
        }, indent=2, sort_keys=True))
        return 0 if result["decision"] == SUCCESS else 2
    except Exception as exc:
        print(json.dumps({
            "decision": "D2_CTL_ATTEMPT2_PREVIEW_BLOCKED__NO_DISPATCH",
            "error_type": type(exc).__name__, "worker_started": False,
            "attempt2_evidence_exists": OUT.exists() or OUT.is_symlink(),
        }), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
