#!/usr/bin/env python3
"""D2 CTL: exactly ONE owner-approved local run prepare; NEVER start a worker.

--preview is source/read-only (Beads reads may touch operational caches).
--prepare --ack-claim creates one durable ProjectCTL run, claims the single
frozen Beads task, and creates an isolated worktree. NO model turn, verify,
integration, Direct candidate mutation, retries, or remote publication.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from experiments.dogfooding.d2.d2_ctl_readiness import audit as readiness_audit
from experiments.dogfooding.d2.d2_direct_manual import validate_admission
from experiments.dogfooding.d2.d2_no_inference_preflight import validate_strategy
from experiments.dogfooding.d2.d2_no_inference_preflight import (
    ROOT, RESEARCH, CTL, DIRECT, VENV, BASE, POLICY_HEAD, TASK, MODEL,
    ALLOWED_WRITES,
)

OUT = ROOT / "observations/ctl-prepare-attempt-1"
EXPECTED_SCOPE = set(ALLOWED_WRITES)
PREPARE_TIMEOUT = 180


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def run_read(argv: list[str], *, timeout: int = 90) -> str:
    result = subprocess.run(argv, cwd=RESEARCH, capture_output=True,
                            text=True, check=False, timeout=timeout)
    if result.returncode != 0:
        raise RuntimeError(f"Read probe failed: {argv[:4]}, exit={result.returncode}")
    return result.stdout.rstrip("\n")


def git(repo: Path, *args: str) -> str:
    return run_read(["git", "-C", str(repo), *args])


def record(name: str, data: object) -> None:
    (OUT / name).write_text(
        json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def parse_task(raw: object) -> dict:
    items = raw if isinstance(raw, list) else [raw]
    if len(items) != 1 or items[0].get("id") != TASK:
        raise ValueError("Expected exactly one canonical D2 Beads task")
    return items[0]


def check_preparation(plan: dict, run: dict, worktree: dict, *,
                      target: str) -> dict:
    rid = run.get("run_id")
    if not isinstance(rid, str) or not rid.startswith("run-") or len(rid) > 90:
        raise ValueError("Invalid prepared run identifier")
    if run.get("task_id") != TASK or plan.get("task_id") != TASK:
        raise ValueError("Prepared run task is not frozen D2 task")
    if run.get("status") != "claimed" or run.get("candidate_commit") is not None:
        raise ValueError("Prepared run status/candidate drift")
    if run.get("started_at") is not None:
        raise ValueError("Worker appears to have started during prepare")
    if run.get("lease_owner") is not None:
        raise ValueError("Prepare should release the run lease")
    if plan.get("strategy") != "direct" or plan.get("base_commit") != POLICY_HEAD:
        raise ValueError("Prepared strategy/base commit drift")
    if plan.get("integration_target_ref") != target:
        raise ValueError("Prepared integration target drift")
    worker = plan.get("worker") or {}
    if (worker.get("provider") != "codex"
            or worker.get("actual_model") != MODEL
            or worker.get("reasoning") != "medium"):
        raise ValueError("Prepared model/effort/provider drift")
    perms = plan.get("execution_policy") or {}
    if (perms.get("sandbox") != "workspace_write"
            or perms.get("approval") != "deny_all"
            or perms.get("network") != "disabled"):
        raise ValueError("Prepared sandbox/approval/network drift")
    grants = perms.get("git") or {}
    if not isinstance(grants, dict) or any(grants.values()):
        raise ValueError("Git privilege in prepared policy")
    if (worktree.get("id") != rid or worktree.get("base_commit") != POLICY_HEAD
            or run.get("worktree_id") != rid):
        raise ValueError("Prepared worktree identity/base mismatch")
    wt = Path(worktree["path"]).resolve()
    home_worktrees = (ROOT/"ctl-home/worktrees").resolve()
    if wt == home_worktrees or not wt.is_relative_to(home_worktrees):
        raise ValueError("Prepared worktree is outside isolated D2 home")
    if not wt.is_dir() or wt.is_symlink():
        raise ValueError("Prepared worktree is missing or symlinked")
    if git(wt, "rev-parse", "HEAD") != POLICY_HEAD:
        raise ValueError("Prepared worktree HEAD differs from frozen policy")
    if git(wt, "status", "--porcelain=v1", "--untracked-files=all"):
        raise ValueError("Worker already modified the prepared worktree")
    if git(CTL, "rev-parse", "HEAD") != POLICY_HEAD:
        raise ValueError("CTL Git HEAD changed during preparation")
    if git(CTL, "status", "--porcelain=v1", "--untracked-files=all"):
        raise ValueError("CTL target repository became dirty")
    if git(DIRECT, "rev-parse", "HEAD") != BASE:
        raise ValueError("Direct source baseline moved unexpectedly")
    run_dir = CTL / ".projectctl" / "runs" / rid
    if not (run_dir/"execution-plan.json").is_file():
        raise ValueError("Prepared durable execution plan missing")
    if (run_dir/"worker-result.json").exists():
        raise ValueError("Worker result exists before paid start")
    return {"run_id": rid, "task_id": TASK, "status": "claimed",
            "worker_started": False, "worktree": str(wt),
            "model": MODEL, "reasoning": "medium",
            "execution": {"sandbox": "workspace_write", "approval": "deny_all",
                          "network": "disabled"}, "integration_target": target}


def preview() -> dict:
    if os.environ.get("PROJECTCTL_HOME") != str(ROOT/"ctl-home"):
        raise ValueError("Incorrect D2 isolated PROJECTCTL_HOME")
    if os.environ.get("BD_ACTOR") != "d2-dogfood-owner":
        raise ValueError("Unexpected Beads actor")
    if Path(sys.executable).resolve() != (VENV/"bin/python").resolve():
        raise ValueError("Only pinned D0 venv Python is allowed")
    if OUT.exists() or OUT.is_symlink():
        raise ValueError("First D2 CTL preparation evidence path already exists; NO RETRY")
    result = readiness_audit()
    if (result.get("decision") !=
            "D2_CTL_READ_ONLY_PREPARE_GATE_PASS__CLAIM_NOT_AUTHORIZED"
            or result.get("ctl_run_count") != 0
            or result.get("beads_task") != "open_unclaimed"):
        raise ValueError("Current CTL readiness audit refused preparation")
    target = git(CTL, "branch", "--show-current")
    if not target or target == "HEAD" or git(CTL, "rev-parse", target) != POLICY_HEAD:
        raise ValueError("CTL integration target is not frozen to policy HEAD")
    if git(RESEARCH, "status", "--porcelain=v1", "--untracked-files=all"):
        raise ValueError("Research source checkout is dirty")
    return {"decision": "D2_CTL_PREPARE_PREVIEW_PASS__NO_CLAIM_NO_INFERENCE",
            "task": TASK, "target": target, "policy_head": POLICY_HEAD,
            "readiness": result["decision"], "observation_path": str(OUT),
            "paid_worker_started": False, "beads_task_claimed": False}


def perform_prepare(initial: dict) -> tuple[dict, bool]:
    os.umask(0o077)
    OUT.mkdir(mode=0o700)  # exclusive by preceding preview existence check
    started = time.monotonic_ns()
    data = {"decision": "D2_CTL_PREPARE_IN_PROGRESS__NO_WORKER_START",
            "attempt": 1, "retries": 0, "worker_started": False,
            "start_utc": utc(), "preview": initial,
            "evidence_path": str(OUT)}
    record("prepare-summary.json", data)
    dispatched = False
    try:
        q = json.loads(run_read([str(VENV/"bin/projectctl"),"quota",
                                 "--project",str(CTL),"--json"]))
        n = json.loads(run_read([str(VENV/"bin/projectctl"),"next",
                                 "--project",str(CTL),"--json"]))
        record("quota-before-prepare.json", q)
        record("scheduler-before-prepare.json", n)
        data["admission"] = validate_admission(
            q, n, now=datetime.now(timezone.utc))
        capabilities = json.loads(run_read([
            str(VENV/"bin/projectctl"),"worker","capabilities",
            "--provider","codex","--json"]))
        strategy = json.loads(run_read([
            str(VENV/"bin/projectctl"),"worker","strategy",TASK,
            "--project",str(CTL),"--provider","codex",
            "--requested","direct","--json"]))
        validate_strategy(capabilities, strategy)  # version-only; no model call
        record("capabilities-before-prepare.json", capabilities)
        record("strategy-before-prepare.json", strategy)
        # Re-check the task and evidence before the mutation, after quota reads.
        fresh = readiness_audit()
        if fresh["decision"] != initial["readiness"]:
            raise ValueError("Current readiness changed after official quota checks")
        if git(CTL, "branch", "--show-current") != initial["target"]:
            raise ValueError("Integration branch changed before prepare")
        command = [str(VENV/"bin/projectctl"),"run","prepare",
                   "--strategy","direct","--target",initial["target"],
                   "--project",str(CTL),"--json"]
        record("command-metadata.json", {"argv":command,
                                         "expected_task":TASK,
                                         "model_execution":"FORBIDDEN"})
        # Account for time spent on capability and frozen-state probes; the
        # previously observed official quota must still be fresh at dispatch.
        data["admission"] = validate_admission(
            q, n, now=datetime.now(timezone.utc))
        data["prepare_dispatch_utc"] = utc()
        record("prepare-summary.json", data)
        t = time.monotonic_ns()
        dispatched = True  # exactly one actual prepare subprocess follows
        try:
            proc = subprocess.run(command, cwd=RESEARCH, capture_output=True,
                                  text=True, timeout=PREPARE_TIMEOUT,
                                  check=False)
            stdout, stderr, rc = proc.stdout, proc.stderr, proc.returncode
        except subprocess.TimeoutExpired as exc:
            stdout = (exc.stdout or b"").decode("utf-8",errors="replace") if isinstance(exc.stdout,bytes) else exc.stdout or ""
            stderr = (exc.stderr or b"").decode("utf-8",errors="replace") if isinstance(exc.stderr,bytes) else exc.stderr or ""
            rc = 124
            data["timed_out"] = True
        data["prepare_wall_monotonic_seconds"] = (time.monotonic_ns()-t)/1e9
        data["prepare_exit_code"] = rc
        (OUT/"prepare.stdout.json").write_text(stdout, encoding="utf-8")
        (OUT/"prepare.stderr.log").write_text(stderr, encoding="utf-8")
        if rc != 0:
            raise ValueError(f"Prepare command failed/timeout: exit={rc}; NO RETRY")
        payload = json.loads(stdout)
        record("prepare.json", payload)
        if not all(isinstance(payload.get(k),dict) for k in ("plan","run","worktree")):
            raise ValueError("Prepare did not return plan/run/worktree objects")
        # Preserve the ID before deeper validation even if claims/branches drift.
        data["run_id"] = payload["run"].get("run_id")
        record("prepare-summary.json", data)
        checked = check_preparation(payload["plan"],payload["run"],
                                    payload["worktree"],target=initial["target"])
        shown = json.loads(run_read([str(VENV/"bin/projectctl"),"run","show",
                                     checked["run_id"],"--project",str(CTL),"--json"]))
        record("run-show-after-prepare.json", shown)
        if (shown.get("run",{}).get("status") != "claimed"
                or shown["run"].get("run_id") != checked["run_id"]):
            raise ValueError("Durable run state differs from claimed status")
        runs = json.loads(run_read([str(VENV/"bin/projectctl"),"runs",
                                    "--project",str(CTL),"--json"]))
        record("runs-after-prepare.json", runs)
        if (len(runs)!=1 or runs[0].get("run_id") != checked["run_id"]):
            raise ValueError("Unexpected D2 RunStore count/ID after prepare")
        task = parse_task(json.loads(run_read(["bd","-C",str(CTL),
                                                "show",TASK,"--json"])))
        record("task-after-prepare.json", task)
        if task.get("status") != "in_progress" or not task.get("assignee"):
            raise ValueError("Beads task did not transition to claimed/in-progress")
        # Preserve Direct arm in place; verify no new source mutations.
        if git(DIRECT,"status","--short","--untracked-files=all") != (
                ROOT/"observations/direct-attempt-1/direct-git-status.txt"
                ).read_text(encoding="utf-8").rstrip("\n"):
            raise ValueError("Direct worktree status changed during CTL preparation")
        data["decision"] = "D2_CTL_PREPARE_PASS__PAID_WORKER_NOT_STARTED"
        data["prepared"] = checked
    except Exception as exc:
        data["decision"] = ("D2_CTL_PREPARE_DISPATCHED_NEEDS_RECONCILIATION__NO_RETRY"
                            if dispatched else "D2_CTL_PREPARE_PRECLAIM_BLOCKED__NO_RETRY")
        data["error_type"] = type(exc).__name__
        data["reason"] = str(exc)[:600]
        # Do not query/mutate ambiguous run state automatically after an error.
    finally:
        data["end_utc"] = utc()
        data["total_wall_monotonic_seconds"] = (time.monotonic_ns()-started)/1e9
        record("prepare-summary.json", data)
    return data, dispatched


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--preview",action="store_true")
    mode.add_argument("--prepare",action="store_true")
    ap.add_argument("--ack-claim",action="store_true")
    args = ap.parse_args()
    if args.prepare and not args.ack_claim:
        ap.error("Owner must explicitly pass --prepare --ack-claim")
    if args.preview and args.ack_claim:
        ap.error("--ack-claim cannot accompany --preview")
    try:
        checks = preview()
        if args.preview:
            print(json.dumps(checks,indent=2,sort_keys=True))
            return 0
        result,_ = perform_prepare(checks)
        print(json.dumps({
            "decision":result["decision"],
            "run_id":result.get("run_id"),
            "prepare_exit_code":result.get("prepare_exit_code"),
            "prepare_wall_monotonic_seconds":result.get("prepare_wall_monotonic_seconds"),
            "evidence_path":str(OUT),
            "paid_worker_started":False,
            "reason":result.get("reason"),
        },indent=2,sort_keys=True))
        return 0 if result["decision"]=="D2_CTL_PREPARE_PASS__PAID_WORKER_NOT_STARTED" else 2
    except Exception as exc:
        print(json.dumps({
            "decision": "D2_CTL_PREPARE_NOT_DISPATCHED_BLOCKED",
            "type":type(exc).__name__,"reason":str(exc)[:600],
            "evidence_path_exists":OUT.exists(),
        },ensure_ascii=False),file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
