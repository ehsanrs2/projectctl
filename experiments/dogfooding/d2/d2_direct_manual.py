#!/usr/bin/env python3
"""D2 Direct CLI single-attempt manual runner.

--preview: read-only, checks frozen preflight and proposed one-turn invocation.
--execute --ack-paid: checks *fresh* official D2 quota, then starts ONE paid turn.
Never starts a ProjectCTL worker, claims a task, retries, commits, or publishes.
Raw evidence remains local under 0700 observations/direct-attempt-1.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

from experiments.dogfooding.d2.d2_no_inference_preflight import (
    ROOT, RESEARCH, CTL, DIRECT, VENV, BASE, POLICY_HEAD, TASK,
    MODEL, CODEX_CLI, ALLOWED_WRITES, direct_prompt,
)

OBS = ROOT / "observations/direct-attempt-1"
PROMPT_SHA = "b4aa6e48872f07d1d608bf24a5beeed45ac9e68656defc52aa8c632b63c50f65"
WALL_TIMEOUT_SECONDS = 900
EXPECTED = set(ALLOWED_WRITES)


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def run_read(argv: list[str], *, timeout: int = 90) -> str:
    proc = subprocess.run(argv, cwd=RESEARCH, text=True,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          timeout=timeout, check=False)
    if proc.returncode:
        raise RuntimeError(f"Read-only preflight failed: {argv[0]} {argv[1:3]} status={proc.returncode}")
    return proc.stdout


def git(repo: Path, *args: str) -> str:
    # Preserve leading Git porcelain status markers (e.g. " M"), but
    # remove command-output terminal newlines before SHA comparisons.
    return run_read(["git", "-C", str(repo), *args]).rstrip("\n")


def sha(path: Path) -> str:
    if not path.is_file() or path.is_symlink():
        raise RuntimeError(f"Required ordinary file missing: {path.name}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def preflight() -> tuple[str, dict]:
    if Path(sys.executable).resolve() != (VENV/"bin/python").resolve():
        raise RuntimeError("Only pinned D0 ProjectCTL venv allowed")
    if os.environ.get("PROJECTCTL_HOME") != str(ROOT/"ctl-home"):
        raise RuntimeError("Wrong D2 PROJECTCTL_HOME")
    if os.environ.get("BD_ACTOR") != "d2-dogfood-owner":
        raise RuntimeError("Wrong Beads actor")
    if OBS.exists() or OBS.is_symlink():
        raise RuntimeError("Direct attempt evidence path already exists: do not retry")
    report = json.loads(run_read([
        str(VENV/"bin/python"), "-B", "-m",
        "experiments.dogfooding.d2.d2_no_inference_preflight",
    ], timeout=120))
    if (report.get("decision") != "D2_NO_INFERENCE_PREFLIGHT_PASS"
            or report.get("direct_baseline") != BASE
            or report.get("frozen_policy_head") != POLICY_HEAD
            or report.get("direct_prompt_sha256") != PROMPT_SHA
            or report.get("predeclared_order") != ["direct_cli", "projectctl"]):
        raise RuntimeError("D2 no-inference preflight contract mismatch")
    if git(DIRECT, "status", "--porcelain=v1", "--untracked-files=all"):
        raise RuntimeError("Direct fixture not clean")
    if git(DIRECT, "rev-parse", "HEAD") != BASE or git(CTL, "rev-parse", "HEAD") != POLICY_HEAD:
        raise RuntimeError("Either frozen Git head drifted")
    prompt = direct_prompt(
        (DIRECT/"SPEC.md").read_text(encoding="utf-8"),
        (DIRECT/"POLICY.md").read_text(encoding="utf-8"),
    )
    if hashlib.sha256(prompt.encode("utf-8")).hexdigest() != PROMPT_SHA:
        raise RuntimeError("Frozen direct prompt hash mismatch")
    return prompt, report


def validate_admission(quota: dict, next_decision: dict, *, now: datetime) -> dict:
    snapshot = quota.get("snapshot", {})
    if (snapshot.get("provider") != "codex_app_server"
            or snapshot.get("selected_limit_id") != "codex"
            or snapshot.get("ordinary_usage_allowed") is not True
            or quota.get("stale") is not False or quota.get("mode") != "normal"):
        raise ValueError("Official Codex quota not authorized/fresh")
    observed = datetime.fromisoformat(snapshot["observed_at"].replace("Z", "+00:00"))
    age = (now - observed).total_seconds()
    if observed.tzinfo is None or age < -10 or age > 120:
        raise ValueError(f"Official quota sample too old/clock drift: {age:.1f}s")
    for span in ("five_hour", "weekly"):
        bucket = snapshot.get(span) or {}
        if bucket.get("source") != "official" or bucket.get("confidence") != "high":
            raise ValueError(f"{span} not high-confidence official")
    eff = quota.get("effective", {})
    if not isinstance(eff.get("five_hour"), (float, int)) or eff["five_hour"] < .18:
        raise ValueError("Insufficient effective five-hour quota for MEDIUM")
    if not isinstance(eff.get("weekly"), (float, int)) or eff["weekly"] < .08:
        raise ValueError("Insufficient effective weekly quota for MEDIUM")
    if (next_decision.get("selected_task_id") != TASK
            or next_decision.get("quota_mode") != "normal"):
        raise ValueError("Scheduler did not select sole D2 task")
    candidates = next_decision.get("candidates", [])
    if (len(candidates) != 1 or candidates[0].get("task_id") != TASK
            or candidates[0].get("eligibility", {}).get("eligible") is not True
            or candidates[0].get("eligibility", {}).get("reasons") != []):
        raise ValueError("D2 task admission failed")
    model = candidates[0].get("model") or {}
    if model.get("profile") != "balanced" or model.get("reasoning") != "medium":
        raise ValueError("Model profile selection changed")
    return {"observed_at": snapshot["observed_at"],
            "sample_age_seconds": age,
            "selected_task_id": TASK,
            "selected_limit_id": "codex",
            "five_hour_effective": eff["five_hour"],
            "weekly_effective": eff["weekly"],
            "quota_snapshot_digest": next_decision.get("quota_snapshot_digest")}


def changed_paths(repo: Path) -> set[str]:
    paths: set[str] = set()
    for args in (
        ("diff", "--no-renames", "--name-only", "-z", "HEAD", "--"),
        ("diff", "--cached", "--no-renames", "--name-only", "-z", "HEAD", "--"),
        ("ls-files", "--others", "--exclude-standard", "-z", "--"),
        ("ls-files", "--others", "--ignored", "--exclude-standard", "-z"),
    ):
        raw = subprocess.run(["git","-C",str(repo),*args], check=True,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20).stdout
        paths.update(x.decode() for x in raw.split(b"\0") if x)
    return paths


def validate_source_after() -> dict:
    if git(DIRECT, "rev-parse", "HEAD") != BASE or git(DIRECT, "remote"):
        raise ValueError("Direct Git history or remotes changed")
    if git(CTL, "rev-parse", "HEAD") != POLICY_HEAD:
        raise ValueError("CTL Git commit changed during direct run")
    if git(CTL, "status", "--porcelain=v1", "--untracked-files=all"):
        raise ValueError("CTL worktree changed during direct run")
    manifest = json.loads((ROOT/"observations/offline-setup-v1/baseline-manifest.json").read_text())
    for name, frozen in manifest["all_files_sha256"].items():
        if name not in EXPECTED and sha(DIRECT/name) != frozen:
            raise ValueError(f"Direct protected file drift: {name}")
    for name in EXPECTED:
        if not (DIRECT/name).is_file() or (DIRECT/name).is_symlink():
            raise ValueError(f"Missing or symlinked worker output: {name}")
    changed = changed_paths(DIRECT)
    if changed != EXPECTED:
        raise ValueError(f"Unexpected changed or ignored files: {sorted(changed)}")
    check = subprocess.run(["git","-C",str(DIRECT),"diff","--check","HEAD"],
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15)
    if check.returncode:
        raise ValueError("Git diff --check failed")
    return {"changed_paths": sorted(changed), "protected_hashes": "match",
            "direct_git_head": BASE, "ctl_git_head": POLICY_HEAD}


def parse_events(path: Path) -> dict:
    counts = Counter()
    usage = None
    malformed = 0
    threads = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            malformed += 1
            continue
        kind = item.get("type", "missing_type")
        counts[kind] += 1
        if kind == "thread.started":
            threads.append(item.get("thread_id"))
        if kind == "turn.completed" and isinstance(item.get("usage"), dict):
            usage = item["usage"]
    return {
        "event_counts": dict(counts), "malformed_lines": malformed,
        "thread_count": len(threads),
        "usage": usage if usage is not None else "unknown",
        "single_completed_turn": counts["thread.started"] == 1
           and counts["turn.started"] == 1
           and counts["turn.completed"] == 1
           and counts["turn.failed"] == 0
           and malformed == 0,
        "usage_accounting_note": "cached_input_tokens and reasoning_output_tokens are subsets, not additional totals",
    }


def execute(prompt: str, preflight_result: dict) -> dict:
    # Refresh official quota immediately before this one paid call.
    quota = json.loads(run_read([str(VENV/"bin/projectctl"),"quota",
                                 "--project",str(CTL),"--json"]))
    next_decision = json.loads(run_read([str(VENV/"bin/projectctl"),"next",
                                         "--project",str(CTL),"--json"]))
    admission = validate_admission(quota, next_decision, now=datetime.now(timezone.utc))
    if OBS.exists() or OBS.is_symlink():
        raise RuntimeError("Evidence path appeared: refusing duplicate paid execution")
    os.umask(0o077)  # restrict prompt, provider usage and raw JSONL evidence
    OBS.mkdir(mode=0o700)
    (OBS/"direct-prompt.txt").write_text(prompt, encoding="utf-8")
    (OBS/"preflight.json").write_text(json.dumps(preflight_result,indent=2)+"\n")
    (OBS/"quota-at-admission.json").write_text(json.dumps(quota,indent=2)+"\n")
    (OBS/"scheduler-at-admission.json").write_text(json.dumps(next_decision,indent=2)+"\n")
    cli = shutil.which("codex")
    if not cli:
        raise RuntimeError("Codex CLI not found after quota observation")
    command = [
        cli, "--disable", "apps", "--disable", "plugins", "exec",
        "--ignore-user-config", "--ignore-rules", "--strict-config",
        "--ephemeral", "--cd", str(DIRECT),
        "--model", MODEL, "--sandbox", "workspace-write",
        "--config", 'approval_policy="never"',
        "--config", 'model_reasoning_effort="medium"',
        "--config", 'sandbox_workspace_write.network_access=false',
        "--json", "-",
    ]
    start_utc = utc()
    started = time.monotonic_ns()
    timed_out = False
    with (OBS/"codex-events.jsonl").open("w", encoding="utf-8") as out, (
          OBS/"codex-stderr.log").open("w", encoding="utf-8") as err:
        try:
            proc = subprocess.run(command, input=prompt, text=True, cwd=DIRECT,
                                  stdout=out, stderr=err,
                                  timeout=WALL_TIMEOUT_SECONDS, check=False)
            rc = proc.returncode
        except subprocess.TimeoutExpired:
            timed_out, rc = True, 124
    duration = (time.monotonic_ns()-started)/1e9
    data = {
        "status": "D2_DIRECT_REVIEW_REQUIRED",
        "model_requested": MODEL, "reasoning_requested": "medium",
        "runtime_requested": CODEX_CLI,
        "approval": "never", "sandbox": "workspace-write",
        "network": "disabled", "plugins_and_apps": "disabled",
        "attempt": 1, "retries": 0,
        "prompt_sha256": PROMPT_SHA, "admission": admission,
        "start_utc": start_utc, "end_utc": utc(),
        "codex_wall_monotonic_seconds": duration,
        "codex_exit_code": rc, "timed_out": timed_out,
        "events": parse_events(OBS/"codex-events.jsonl"),
        "verification": "not_run", "scope": "not_checked",
    }
    # Preserve a post-turn manifest even if the model failed or modified forbidden files.
    try:
        data["observed_changed_paths"] = sorted(changed_paths(DIRECT))
        (OBS/"direct-git-status.txt").write_text(
            git(DIRECT, "status", "--short", "--untracked-files=all")+"\n")
        (OBS/"direct.patch").write_text(
            git(DIRECT, "diff", "--binary", "--no-ext-diff", "HEAD", "--")+"\n")
    except Exception as exc:
        data["postflight_collection_error"] = type(exc).__name__
    if rc != 0 or not data["events"]["single_completed_turn"]:
        data["status"] = "D2_DIRECT_FAILED_NO_RETRY"
    else:
        try:
            data["scope"] = validate_source_after()
        except Exception as exc:
            data["scope"] = {"decision": "failed", "reason": str(exc)[:500]}
            data["status"] = "D2_DIRECT_SCOPE_FAILED_NO_RETRY"
        if isinstance(data["scope"], dict) and data["scope"].get("protected_hashes") == "match":
            began = time.monotonic_ns()
            test_command = ["python3","-B","-m","unittest","discover",
                            "-s","tests","-p","test_*.py","-v"]
            with (OBS/"fixed-unittest.stdout.log").open("w") as output, (
                  OBS/"fixed-unittest.stderr.log").open("w") as error:
                try:
                    tested = subprocess.run(test_command,cwd=DIRECT,env={
                        **os.environ,"PYTHONDONTWRITEBYTECODE":"1"},
                        stdout=output,stderr=error,timeout=120,check=False)
                    test_rc = tested.returncode
                except subprocess.TimeoutExpired:
                    test_rc = 124
            stderr = (OBS/"fixed-unittest.stderr.log").read_text(errors="replace")
            match = re.search(r"Ran (\d+) tests? in ", stderr)
            count = int(match.group(1)) if match else None
            data["verification"] = {
                "exit_code": test_rc, "test_count": count,
                "wall_monotonic_seconds": (time.monotonic_ns()-began)/1e9,
            }
            if test_rc != 0 or count != 26:
                data["status"] = "D2_DIRECT_TESTS_FAILED_NO_RETRY"
            else:
                try:
                    data["post_test_scope"] = validate_source_after()
                    data["status"] = "D2_DIRECT_TESTS_AND_SCOPE_PASS__HUMAN_REVIEW_PENDING"
                except Exception as exc:
                    data["status"] = "D2_DIRECT_POST_TEST_SCOPE_FAILED_NO_RETRY"
                    data["post_test_scope_error"] = str(exc)[:500]
    (OBS/"direct-run-summary.json").write_text(json.dumps(data,indent=2,sort_keys=True)+"\n")
    return data


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--preview", action="store_true")
    mode.add_argument("--execute", action="store_true")
    parser.add_argument("--ack-paid", action="store_true")
    args = parser.parse_args()
    if args.execute and not args.ack_paid:
        parser.error("A paid Direct CLI call requires --execute --ack-paid")
    if args.preview and args.ack_paid:
        parser.error("--preview cannot include --ack-paid")
    try:
        prompt, report = preflight()
        if args.preview:
            print(json.dumps({
                "decision": "D2_DIRECT_HARNESS_PREVIEW_PASS__NO_PAID_CALL",
                "preflight": report["decision"],
                "prompt_sha256": PROMPT_SHA,
                "observations": str(OBS),
                "direct_clean": True,
                "frozen_order": report["predeclared_order"],
                "paid_execution": "NOT_AUTHORIZED_OR_STARTED",
            }, indent=2))
            return 0
        data = execute(prompt, report)
        print(json.dumps({
            "decision": data["status"],
            "codex_exit_code": data["codex_exit_code"],
            "wall_seconds": data["codex_wall_monotonic_seconds"],
            "turn_count": data["events"]["event_counts"].get("turn.started",0),
            "usage": data["events"]["usage"],
            "verification": data["verification"],
            "evidence_dir": str(OBS),
        },indent=2))
        return 0 if data["status"].startswith(
            "D2_DIRECT_TESTS_AND_SCOPE_PASS") else 2
    except Exception as exc:
        print(json.dumps({
            "decision": "D2_DIRECT_HARNESS_BLOCKED_NO_MODEL_CALL_OR_UNKNOWN_IF_POST_START",
            "error_type": type(exc).__name__, "reason": str(exc)[:500],
            "existing_evidence_path": str(OBS) if OBS.exists() else None,
        }), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
