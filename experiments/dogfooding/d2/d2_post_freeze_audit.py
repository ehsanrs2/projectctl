#!/usr/bin/env python3
"""D2 post-freeze audit: read-only of application source and control-plane policy.

No git writes, ProjectCTL prepare/start, claims, paid model calls, or task changes.
Git and Beads read queries may refresh their own operational caches. This script
does not save evidence: retain the terminal output separately if desired.
"""
from __future__ import annotations

import ast
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import yaml

from experiments.dogfooding.d2.gitignore_review import (
    review_ignored_paths, validate_root_beads_gate_lock,
)
from projectctl.schemas.config import ProjectConfig
from projectctl.schemas.execution_scope import ExecutionScopeCatalog
from projectctl.schemas.verification import VerificationCatalog, DEFAULT_PROTECTED_PATHS

BASE = "32836ea5633230e50fb9d907dcdba83e357bcfc6"
BEADS_SETUP = "ab34052b3cb2ece4452504ffa457ecf2d358891f"
POLICY_COMMIT = "3c69dd42497acadadc5d64e7b4abe5d412b309f5"
TASK = "d2ctl-g4q"
SPEC_SHA = "8264746827bbb7300bf234023e6617324c78f37aecf524f2427a686925da8815"
PROFILE_DIGEST = "canonical-json-sha256-v1:3e8b2ad56b3306fc92ce5e98034e1e4766a496448d49810d2d29a9240b614cbc"
POLICY_SHA = {
    ".gitignore": "42e957af9d0cb01303304932893e705324025272f8d77d1a6a4c854912690627",
    ".projectctl/config.yaml": "c9178fa44b85bf122cecbe614b0c5bb112b7cf2869a8018e63c0303be48d53e2",
    "projectctl.scope.yaml": "cc97841324e26c49541db1b935c7e66c79e4d14f6a4a4b213c13b9bb6e155f9f",
    "projectctl.verification.yaml": "2b989d2b151f8bc4e3fa6044e09bbd4e421006fb64896ab7ad71dded74d985e4",
}
TRACKED_POLICY = {
    ".gitignore", "docs/PROJECT_STATE.yaml",
    "projectctl.scope.yaml", "projectctl.verification.yaml",
}
WORKER_WRITES = {"d2events/parse.py", "d2events/report.py", "d2events/cli.py"}
CHECK = ["python3", "-B", "-m", "unittest", "discover",
         "-s", "tests", "-p", "test_*.py", "-v"]


def cmd(argv: list[str]) -> str:
    p = subprocess.run(argv, capture_output=True, text=True, timeout=30)
    if p.returncode != 0:
        raise ValueError(f"Non-zero read-query exit: {argv[0]} {argv[1:4]}: {p.returncode}")
    return p.stdout.rstrip("\n")


def git(root: Path, *args: str) -> str:
    return cmd(["git", "-C", str(root), *args])


def sha(path: Path) -> str:
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"Missing or symlinked required source: {path.name}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def audit() -> dict:
    research = Path.home() / "project/My/projectctl-advisory-lab"
    root = Path.home() / ".local/state/projectctl-dogfood-d2"
    ctl, direct = root/"fixtures/ctl", root/"fixtures/direct"
    home = root/"ctl-home"
    freeze = root/"observations/policy-freeze-v1/freeze-report.json"
    manifest = root/"observations/offline-setup-v1/baseline-manifest.json"

    assert os.environ.get("PROJECTCTL_HOME") == str(home)
    assert os.environ.get("BD_ACTOR") == "d2-dogfood-owner"
    for path in (research, ctl, direct, home):
        assert path.is_dir() and not path.is_symlink(), path
    assert git(research, "branch", "--show-current") == "research/advisory-skills-eval"
    assert git(research, "status", "--porcelain=v1", "--untracked-files=all") == ""
    assert git(ctl, "rev-parse", "--show-toplevel") == str(ctl)
    assert git(direct, "rev-parse", "--show-toplevel") == str(direct)
    assert git(ctl, "rev-parse", "HEAD") == POLICY_COMMIT
    assert git(ctl, "rev-parse", "HEAD^") == BEADS_SETUP
    assert git(ctl, "rev-parse", "HEAD^^") == BASE
    assert set(git(ctl, "diff", "--name-only", BEADS_SETUP, POLICY_COMMIT).splitlines()) == TRACKED_POLICY
    assert git(ctl, "status", "--porcelain=v1", "--untracked-files=all") == ""
    assert git(direct, "status", "--porcelain=v1", "--untracked-files=all") == ""
    assert git(direct, "rev-parse", "HEAD") == BASE
    assert git(ctl, "remote") == git(direct, "remote") == ""
    assert not (direct/".beads").exists() and not (direct/".projectctl").exists()

    frozen = json.loads(manifest.read_text(encoding="utf-8"))
    report = json.loads(freeze.read_text(encoding="utf-8"))
    assert frozen["status"] == "D2_OFFLINE_BASELINES_FROZEN"
    assert frozen["base_sha"] == BASE and frozen["spec_sha256"] == SPEC_SHA
    assert len(frozen["all_files_sha256"]) == 11
    assert Path(frozen["ctl_path"]).resolve() == ctl
    assert Path(frozen["direct_path"]).resolve() == direct
    assert report["status"] == "D2_POLICY_FROZEN_LOCAL_ONLY"
    assert report["task"] == TASK
    assert report["policy_commit"] == POLICY_COMMIT
    assert report["base_commit"] == BASE and report["setup_commit"] == BEADS_SETUP
    assert report["candidate_sha256"] == POLICY_SHA

    for name, expected in frozen["all_files_sha256"].items():
        assert sha(direct/name) == expected, f"Direct drift: {name}"
        if name != ".gitignore":
            assert sha(ctl/name) == expected, f"CTL frozen source drift: {name}"
    for name, expected in POLICY_SHA.items():
        assert sha(ctl/name) == expected, f"Policy drift: {name}"
    assert sha(ctl/"SPEC.md") == SPEC_SHA

    # Every tracked file must be expected: original 11 plus three new managed files.
    original = set(frozen["all_files_sha256"])
    expected_tracked = original | {"docs/PROJECT_STATE.yaml",
                                     "projectctl.scope.yaml","projectctl.verification.yaml"}
    assert set(git(ctl, "ls-files").splitlines()) == expected_tracked

    config = ProjectConfig.model_validate(
        yaml.safe_load((ctl/".projectctl/config.yaml").read_text(encoding="utf-8")))
    assert config.task_store.provider == "beads"
    assert config.code_transport.mode == config.code_delivery.mode == "local"
    assert config.scope_governance.mode == "required"
    assert config.orchestration.max_active_runs == 1
    assert all(p.provider == "codex" and p.model == "gpt-6-luna"
               and p.reasoning.value == "medium" and p.enabled
               for p in config.model_profiles.values())

    scope = ExecutionScopeCatalog.model_validate(
        yaml.safe_load((ctl/"projectctl.scope.yaml").read_text(encoding="utf-8")))
    assert list(scope.tasks) == [TASK]
    task_scope = scope.tasks[TASK]
    assert {x.path for x in task_scope.writes} == WORKER_WRITES
    assert all(x.kind == "exact" for x in task_scope.writes)
    assert task_scope.resources == []
    expected_inputs = set(frozen["all_files_sha256"]) - {".gitignore"}
    assert {x.path for x in task_scope.inputs} == expected_inputs
    assert all(x.kind == "exact" for x in task_scope.inputs)

    verify = VerificationCatalog.model_validate(
        yaml.safe_load((ctl/"projectctl.verification.yaml").read_text(encoding="utf-8")))
    assert verify.default_profile == "default"
    profile = verify.profiles["default"]
    assert len(profile.commands) == 1
    check = profile.commands[0]
    assert check.id == "fixed-d2-unittest" and check.argv == CHECK
    assert check.required and check.timeout_seconds == 120
    policy = profile.diff_policy
    assert policy.require_changes and not policy.allow_symlink_changes
    assert policy.max_changed_paths == 3
    protected = set(DEFAULT_PROTECTED_PATHS) | {
        ".gitignore","SPEC.md","POLICY.md","tests/**",
        "d2events/__init__.py","projectctl.scope.yaml","projectctl.verification.yaml"}
    assert protected.issubset(set(policy.protected_paths))
    resolution = json.loads(cmd(["projectctl","verification","profile",
                                 "--project",str(ctl),"--json"]))
    assert resolution["source"] == "projectctl.verification.yaml"
    assert resolution["profile_digest"] == PROFILE_DIGEST
    assert resolution["profile"]["commands"][0]["argv"] == CHECK

    # Check the complete frozen test corpus without running the stub acceptance tests.
    test_count = 0
    for relative in ("tests/test_parser.py", "tests/test_report.py", "tests/test_cli.py"):
        node = ast.parse((ctl/relative).read_text(encoding="utf-8"))
        test_count += sum(isinstance(n, ast.FunctionDef) and n.name.startswith("test_")
                          for n in ast.walk(node))
    assert test_count == 26

    # Stronger than git status: reject ignored non-Beads application artifacts.
    raw = subprocess.run(["git","-C",str(ctl),"ls-files","--others","--ignored",
                          "--exclude-standard","-z"],
                         capture_output=True,check=True,timeout=15).stdout
    ignored = [x.decode("utf-8") for x in raw.split(b"\0") if x]
    assert all(x.startswith(".beads/") or x.startswith(".dolt/")
               or x == ".beads-credential-key" or x == ".beads.gate.lock"
               or x.startswith(".projectctl/") for x in ignored)
    review_ignored_paths([x for x in ignored if not x.startswith(".projectctl/")])
    validate_root_beads_gate_lock(ctl, ignored)
    # Run directory is not an authorized execution record at this point.
    run_root = ctl/".projectctl/runs"
    assert not run_root.exists() or not any(run_root.iterdir())

    ready = json.loads(cmd(["bd","-C",str(ctl),"ready","--json"]))
    detail = json.loads(cmd(["bd","-C",str(ctl),"show",TASK,"--json"]))
    ready = ready if isinstance(ready,list) else ready.get("issues",ready.get("ready",[]))
    detail = detail if isinstance(detail,list) else [detail]
    assert len(ready) == len(detail) == 1
    assert ready[0]["id"] == detail[0]["id"] == TASK
    assert detail[0]["status"] == "open" and not detail[0].get("assignee")
    assert detail[0]["description"].rstrip("\n") == (ctl/"SPEC.md").read_text().rstrip("\n")
    assert git(ctl, "status", "--porcelain=v1", "--untracked-files=all") == ""
    assert git(direct, "status", "--porcelain=v1", "--untracked-files=all") == ""

    return {
        "decision": "D2_POST_FREEZE_READ_ONLY_PASS",
        "policy_commit": POLICY_COMMIT,
        "baseline_commit": BASE,
        "task": TASK,
        "task_status": "open_unclaimed",
        "scope_governance": "required",
        "worker_writes": sorted(WORKER_WRITES),
        "verification_command": CHECK,
        "verification_test_count": test_count,
        "verification_profile_digest": PROFILE_DIGEST,
        "protected_files_and_policy_hashes": "match",
        "ctl_worktree_clean": True,
        "direct_unchanged": True,
        "ignored_application_paths": "none_detected",
        "inference_started": False,
        "next_gate": "OFFICIAL_QUOTA_AND_MODEL_CAPABILITY_PREFLIGHT__NO_WORKER",
    }


def main() -> int:
    try:
        print(json.dumps(audit(), indent=2, sort_keys=True))
        return 0
    except Exception as exc:
        print(json.dumps({"decision":"D2_POST_FREEZE_AUDIT_BLOCKED",
                          "error_type":type(exc).__name__,
                          "reason":str(exc)[:350]}),file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
