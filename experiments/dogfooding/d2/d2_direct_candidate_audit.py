#!/usr/bin/env python3
"""D2 completed Direct arm: independent READ-ONLY evidence and source review.

Never invokes Codex, quota refresh, ProjectCTL runs, Beads mutations, tests,
Git writes or network calls. No file writes. Only prints local source when
--show-source is explicitly requested after the evidence audit passes.
"""
from __future__ import annotations

import argparse
import ast
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

from experiments.dogfooding.d2.d2_no_inference_preflight import (
    ROOT, RESEARCH, CTL, DIRECT, BASE, POLICY_HEAD,
)
from experiments.dogfooding.d2.d2_direct_manual import (
    OBS, PROMPT_SHA, EXPECTED, parse_events,
)

SUCCESS = "D2_DIRECT_TESTS_AND_SCOPE_PASS__HUMAN_REVIEW_PENDING"
EXPECTED_MODEL = "gpt-6-luna"
EXPECTED_RUNTIME = "codex-cli 0.163.0"


def command(argv: list[str], *, timeout: int = 20) -> str:
    proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    if proc.returncode:
        raise RuntimeError(f"Read-only Git command failed: {argv[0]} {argv[1:4]}")
    return proc.stdout


def git(repo: Path, *args: str) -> str:
    return command(["git", "-C", str(repo), *args]).rstrip("\n")


def digest(path: Path) -> str:
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"Missing or symlinked file: {path.name}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def json_file(path: Path) -> dict:
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"Missing or symlinked evidence: {path.name}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Invalid evidence document: {path.name}")
    return data


def source_inventory(root: Path, paths: set[str]) -> dict:
    out = {}
    for name in sorted(paths):
        path = root / name
        if path.stat().st_size > 32768:
            raise ValueError(f"Generated source unexpectedly large: {name}")
        src = path.read_text(encoding="utf-8")
        tree = ast.parse(src, filename=name)
        imports = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name for alias in node.names)
            if isinstance(node, ast.ImportFrom):
                imports.add("."*node.level+(node.module or ""))
        out[name] = {
            "sha256": digest(path),
            "lines": len(src.splitlines()),
            "imports_to_review": sorted(imports),
        }
    return out


def validate_summary(data: dict, event_data: dict) -> None:
    if (data.get("status") != SUCCESS
            or data.get("codex_exit_code") != 0
            or data.get("timed_out") is not False
            or data.get("attempt") != 1 or data.get("retries") != 0):
        raise ValueError("Direct completed-turn status does not match approved attempt")
    expected = {"model_requested": EXPECTED_MODEL,
                "reasoning_requested": "medium",
                "runtime_requested": EXPECTED_RUNTIME,
                "approval": "never", "sandbox": "workspace-write",
                "network": "disabled", "plugins_and_apps": "disabled",
                "prompt_sha256": PROMPT_SHA}
    for key, value in expected.items():
        if data.get(key) != value:
            raise ValueError(f"Direct run envelope drift: {key}")
    if not isinstance(data.get("codex_wall_monotonic_seconds"), (int, float)):
        raise ValueError("Missing measured worker wall duration")
    if not 0 < data["codex_wall_monotonic_seconds"] < 900:
        raise ValueError("Invalid worker duration")
    start = datetime.fromisoformat(data["start_utc"].replace("Z", "+00:00"))
    end = datetime.fromisoformat(data["end_utc"].replace("Z", "+00:00"))
    if start.tzinfo is None or end.tzinfo is None or end < start:
        raise ValueError("Invalid UTC measurement boundaries")
    v = data.get("verification") or {}
    if (v.get("exit_code") != 0 or v.get("test_count") != 26
            or not isinstance(v.get("wall_monotonic_seconds"), (int, float))
            or v["wall_monotonic_seconds"] <= 0):
        raise ValueError("Frozen acceptance evidence does not report 26 passing tests")
    for key in ("scope", "post_test_scope"):
        item = data.get(key) or {}
        if (item.get("changed_paths") != sorted(EXPECTED)
                or item.get("protected_hashes") != "match"
                or item.get("direct_git_head") != BASE
                or item.get("ctl_git_head") != POLICY_HEAD):
            raise ValueError(f"{key} source verification snapshot drift")
    if data.get("events") != event_data or not event_data["single_completed_turn"]:
        raise ValueError("Codex raw JSONL does not match recorded one-turn event counters")


def audit() -> dict:
    if os.environ.get("PROJECTCTL_HOME") != str(ROOT/"ctl-home"):
        raise ValueError("Wrong isolated D2 PROJECTCTL_HOME")
    for folder in (RESEARCH, DIRECT, CTL, OBS):
        if not folder.is_dir() or folder.is_symlink():
            raise ValueError(f"Required directory missing/symlinked: {folder.name}")
    if git(RESEARCH, "branch", "--show-current") != "research/advisory-skills-eval":
        raise ValueError("Wrong research branch")
    if git(RESEARCH, "status", "--porcelain=v1", "--untracked-files=all"):
        raise ValueError("Research checkout changed; do not mix evidence versions")
    if git(DIRECT, "rev-parse", "HEAD") != BASE:
        raise ValueError("Direct baseline HEAD changed")
    if git(CTL, "rev-parse", "HEAD") != POLICY_HEAD:
        raise ValueError("CTL policy HEAD changed")
    if git(CTL, "status", "--porcelain=v1", "--untracked-files=all"):
        raise ValueError("CTL fixture changed before independent Direct review")
    if git(DIRECT, "remote") or git(CTL, "remote"):
        raise ValueError("Unexpected remote in a D2 local fixture")
    if (DIRECT/".projectctl").exists() or (DIRECT/".beads").exists():
        raise ValueError("Direct arm unexpectedly has control-plane directory")

    changed = set(git(DIRECT, "diff", "--name-only", "HEAD", "--").splitlines())
    staged = git(DIRECT, "diff", "--cached", "--name-only", "HEAD", "--")
    untracked = git(DIRECT, "ls-files", "--others", "--exclude-standard")
    if changed != EXPECTED or staged or untracked:
        raise ValueError("Direct changed/staged/untracked paths do not match three frozen writes")
    ignored_raw = subprocess.run(
        ["git", "-C", str(DIRECT), "ls-files", "--others", "--ignored",
         "--exclude-standard", "-z"],
        capture_output=True, check=True, timeout=20).stdout
    ignored = [name.decode() for name in ignored_raw.split(b"\0") if name]
    if ignored:
        raise ValueError(f"Unexpected ignored Direct paths: {sorted(ignored)[:10]}")
    if command(["git","-C",str(DIRECT),"diff","--check","HEAD"]).strip():
        raise ValueError("Direct diff check has output")

    frozen = json_file(ROOT/"observations/offline-setup-v1/baseline-manifest.json")
    if frozen.get("base_sha") != BASE or frozen.get("spec_sha256") != digest(DIRECT/"SPEC.md"):
        raise ValueError("Frozen manifest origin or SPEC drift")
    for rel, expected in frozen["all_files_sha256"].items():
        if rel not in EXPECTED and digest(DIRECT/rel) != expected:
            raise ValueError(f"Protected file changed: {rel}")
    preflight = json_file(OBS/"preflight.json")
    if (preflight.get("decision") != "D2_NO_INFERENCE_PREFLIGHT_PASS"
            or preflight.get("direct_prompt_sha256") != PROMPT_SHA
            or preflight.get("predeclared_order") != ["direct_cli","projectctl"]):
        raise ValueError("Preflight prompt/order mismatch")
    if digest(OBS/"direct-prompt.txt") != PROMPT_SHA:
        raise ValueError("Executed Direct prompt hash drift")

    data = json_file(OBS/"direct-run-summary.json")
    events = parse_events(OBS/"codex-events.jsonl")
    validate_summary(data, events)
    if data.get("observed_changed_paths") != sorted(EXPECTED):
        raise ValueError("Recorded changed paths mismatch")
    quota = json_file(OBS/"quota-at-admission.json")
    scheduler = json_file(OBS/"scheduler-at-admission.json")
    admission = data.get("admission") or {}
    if (quota.get("snapshot", {}).get("observed_at") != admission.get("observed_at")
            or scheduler.get("selected_task_id") != "d2ctl-g4q"
            or scheduler.get("quota_snapshot_digest") != admission.get("quota_snapshot_digest")
            or scheduler.get("quota_mode") != "normal"
            or quota.get("stale") is not False
            or quota.get("snapshot",{}).get("provider") != "codex_app_server"):
        raise ValueError("Saved official quota/admission cross-evidence mismatch")

    text = (OBS/"fixed-unittest.stderr.log").read_text(encoding="utf-8")
    if not re.search(r"(?m)^Ran 26 tests? in ", text) or not re.search(r"(?m)^OK$", text):
        raise ValueError("Independent captured unittest transcript does not end with 26-test OK")
    if git(DIRECT, "status", "--short", "--untracked-files=all") + "\n" != (
        OBS/"direct-git-status.txt").read_text(encoding="utf-8"):
        raise ValueError("Saved Direct Git status differs from current working tree")
    if git(DIRECT, "diff", "--binary", "--no-ext-diff", "HEAD", "--") + "\n" != (
        OBS/"direct.patch").read_text(encoding="utf-8"):
        raise ValueError("Saved Direct binary patch differs from working tree")
    source = source_inventory(DIRECT, EXPECTED)
    return {
        "decision": "D2_DIRECT_CANDIDATE_EVIDENCE_AUDIT_PASS__SEMANTIC_REVIEW_PENDING",
        "direct_head": BASE, "ctl_head": POLICY_HEAD,
        "frozen_task": "d2ctl-g4q", "changed_paths": sorted(EXPECTED),
        "test_count": 26, "test_exit_code": 0,
        "codex_wall_monotonic_seconds": data["codex_wall_monotonic_seconds"],
        "independent_test_wall_seconds": data["verification"]["wall_monotonic_seconds"],
        "reported_usage": events["usage"],
        "reported_event_counts": events["event_counts"],
        "source_inventory": source,
        "retained_evidence_path": str(OBS),
        "semantic_review": "PENDING_HUMAN_REVIEW_OF_SOURCE_BELOW",
        "projectctl_paid_execution": "NOT_STARTED",
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--read-only", action="store_true")
    ap.add_argument("--show-source", action="store_true")
    args = ap.parse_args()
    if not args.read_only:
        ap.error("Pass --read-only; this program never mutates repositories.")
    try:
        summary = audit()
        print(json.dumps(summary, indent=2, sort_keys=True, ensure_ascii=False))
        if args.show_source:
            for path in sorted(EXPECTED):
                print(f"\n=== BEGIN ACTUAL DIRECT SOURCE: {path} ===")
                print((DIRECT/path).read_text(encoding="utf-8"))
                print(f"=== END ACTUAL DIRECT SOURCE: {path} ===")
        return 0
    except Exception as exc:
        print(json.dumps({"decision": "D2_DIRECT_EVIDENCE_AUDIT_BLOCKED",
                          "error_type": type(exc).__name__,
                          "reason": str(exc)[:400]}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
