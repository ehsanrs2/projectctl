#!/usr/bin/env python3
"""D2 CTL-arm readiness *after* completed Direct — no inference, no claims.

Read-only of frozen CTL and completed Direct; Git and Beads read queries may
refresh their operational caches. No quota refresh, run prepare/start/verify,
model call, checkout reset, source write, or raw source copy to ctl.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import yaml

from projectctl.schemas.config import ProjectConfig
from projectctl.schemas.execution_scope import ExecutionScopeCatalog
from projectctl.schemas.verification import VerificationCatalog

from experiments.dogfooding.d2.d2_direct_candidate_audit import audit as direct_audit
from experiments.dogfooding.d2.d2_no_inference_preflight import (
    ROOT, CTL, DIRECT, RESEARCH, VENV, BASE, POLICY_HEAD,
    MODEL, SDK, ADAPTER, TASK, ALLOWED_WRITES,
)
from experiments.dogfooding.d2.d2_freeze_policy import SPEC_SHA
from experiments.dogfooding.d2.d2_post_freeze_audit import POLICY_SHA

DIRECT_SOURCE = {
    "d2events/cli.py": "a9eec60be23a186805c1275f53ed6ece80ad63049d27a0c64ed9a24685d15451",
    "d2events/parse.py": "0eda41e5175e353773c49bdb41dcc41293f6f9df1b073385c75a7d7722065ef3",
    "d2events/report.py": "43e9ef46a244083c66fce87759028e90cb9344c5b782ebb89cdcd0d95640d625",
}
PROFILE_DIGEST = "canonical-json-sha256-v1:3e8b2ad56b3306fc92ce5e98034e1e4766a496448d49810d2d29a9240b614cbc"
TEST_COMMAND = ["python3","-B","-m","unittest","discover","-s","tests","-p","test_*.py","-v"]


def read_command(args: list[str]) -> str:
    result = subprocess.run(args, capture_output=True, text=True, timeout=45, check=False)
    if result.returncode:
        raise ValueError(f"Read command failed: {args[:4]} exit={result.returncode}")
    return result.stdout.rstrip("\n")


def git(root: Path, *args: str) -> str:
    return read_command(["git","-C",str(root),*args])


def sha(path: Path) -> str:
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"Missing/symlinked frozen file: {path.name}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_task(ready: object, detail: object) -> None:
    r = ready if isinstance(ready, list) else ready.get("issues", ready.get("ready", []))
    d = detail if isinstance(detail, list) else [detail]
    if not (len(r)==len(d)==1 and r[0].get("id")==d[0].get("id")==TASK
            and d[0].get("status")=="open" and not d[0].get("assignee")):
        raise ValueError("Canonical Beads D2 task not sole ready/unclaimed")
    if d[0].get("description","").rstrip("\n") != (CTL/"SPEC.md").read_text(encoding="utf-8").rstrip("\n"):
        raise ValueError("Canonical task description differs from frozen SPEC")


def validate_snapshots(data: dict, quota_summary: dict) -> None:
    if data.get("decision") != "D2_DIRECT_CANDIDATE_EVIDENCE_AUDIT_PASS__SEMANTIC_REVIEW_PENDING":
        raise ValueError("Direct evidence audit is not proven")
    expected = sorted(DIRECT_SOURCE)
    if data.get("changed_paths") != expected or data.get("test_count")!=26 or data.get("test_exit_code")!=0:
        raise ValueError("Direct frozen result drift")
    if data.get("direct_head") != BASE or data.get("ctl_head") != POLICY_HEAD:
        raise ValueError("Paired source commit drift")
    if data.get("source_inventory") is None:
        raise ValueError("Direct audit source inventory missing")
    for name, value in DIRECT_SOURCE.items():
        if data["source_inventory"].get(name,{}).get("sha256")!=value:
            raise ValueError(f"Direct source SHA drift: {name}")
    if quota_summary.get("decision") != "D2_NO_INFERENCE_PREFLIGHT_PASS":
        raise ValueError("Original Direct preflight evidence invalid")
    if quota_summary.get("predeclared_order") != ["direct_cli","projectctl"]:
        raise ValueError("Frozen experimental arm ordering changed")


def audit() -> dict:
    if os.environ.get("PROJECTCTL_HOME") != str(ROOT/"ctl-home"):
        raise ValueError("Use only the isolated D2 PROJECTCTL_HOME")
    if os.environ.get("BD_ACTOR") != "d2-dogfood-owner":
        raise ValueError("Beads actor mismatch")
    if Path(sys.executable).resolve() != (VENV/"bin/python").resolve():
        raise ValueError("Use pinned isolated venv")
    if git(RESEARCH,"branch","--show-current") != "research/advisory-skills-eval":
        raise ValueError("Wrong research branch")
    if git(RESEARCH,"status","--porcelain=v1","--untracked-files=all"):
        raise ValueError("Research checkout dirty")
    result = direct_audit()
    original = json.loads((ROOT/"observations/direct-attempt-1/preflight.json").read_text(encoding="utf-8"))
    validate_snapshots(result, original)
    if git(CTL,"rev-parse","HEAD") != POLICY_HEAD or git(DIRECT,"rev-parse","HEAD") != BASE:
        raise ValueError("Unexpected paired Git HEAD")
    if git(CTL,"status","--porcelain=v1","--untracked-files=all"):
        raise ValueError("CTL fixture is not clean")
    if git(CTL,"remote") or git(DIRECT,"remote"):
        raise ValueError("Unexpected fixture remotes")
    if (CTL/".projectctl/runs").exists() and any((CTL/".projectctl/runs").iterdir()):
        raise ValueError("CTL run records already exist")
    runs = json.loads(read_command([str(VENV/"bin/projectctl"),"runs","--project",str(CTL),"--json"]))
    if not isinstance(runs,list) or runs:
        raise ValueError("Expected zero D2 CTL runs before its first preparation")
    ready = json.loads(read_command(["bd","-C",str(CTL),"ready","--json"]))
    detail = json.loads(read_command(["bd","-C",str(CTL),"show",TASK,"--json"]))
    validate_task(ready,detail)
    if sha(CTL/"SPEC.md") != SPEC_SHA or sha(DIRECT/"SPEC.md") != SPEC_SHA:
        raise ValueError("Frozen SPEC changed")
    for name, digest in POLICY_SHA.items():
        if sha(CTL/name)!=digest:
            raise ValueError(f"CTL management policy drift: {name}")
    cfg = ProjectConfig.model_validate(yaml.safe_load((CTL/".projectctl/config.yaml").read_text(encoding="utf-8")))
    if cfg.task_store.provider!="beads" or cfg.scope_governance.mode!="required":
        raise ValueError("Missing canonical task authority or required scope governance")
    if cfg.orchestration.max_active_runs!=1:
        raise ValueError("CTL serial execution policy changed")
    if cfg.code_delivery.mode!="local" or cfg.code_transport.mode!="local":
        raise ValueError("CTL remote delivery policy drift")
    for profile in cfg.model_profiles.values():
        if profile.provider!="codex" or profile.model!=MODEL or profile.reasoning.value!="medium":
            raise ValueError("Frozen Codex model catalog drift")
    scope = ExecutionScopeCatalog.model_validate(yaml.safe_load((CTL/"projectctl.scope.yaml").read_text(encoding="utf-8")))
    if list(scope.tasks)!=[TASK] or {s.path for s in scope.tasks[TASK].writes} != set(ALLOWED_WRITES):
        raise ValueError("CTL exact write scope mismatch")
    if any(s.kind!="exact" for s in scope.tasks[TASK].writes):
        raise ValueError("Non-exact CTL write scope")
    verification = VerificationCatalog.model_validate(yaml.safe_load((CTL/"projectctl.verification.yaml").read_text(encoding="utf-8")))
    if verification.default_profile!="default":
        raise ValueError("Unexpected verification default")
    tests=verification.profiles["default"].commands
    if len(tests)!=1 or tests[0].argv!=TEST_COMMAND or not tests[0].required:
        raise ValueError("Independent frozen tests changed")
    profile=json.loads(read_command([str(VENV/"bin/projectctl"),"verification","profile","--project",str(CTL),"--json"]))
    if profile.get("profile_digest") != PROFILE_DIGEST or profile.get("source") != "projectctl.verification.yaml":
        raise ValueError("Verification resolution mismatch")
    if direct_audit.__name__ != "audit":
        raise ValueError("Direct evidence audit binding changed")
    return {
        "decision": "D2_CTL_READ_ONLY_PREPARE_GATE_PASS__CLAIM_NOT_AUTHORIZED",
        "projectctl_task": TASK,
        "policy_head": POLICY_HEAD,
        "direct_base": BASE,
        "frozen_source_readiness": "pass",
        "direct_result": "SEMANTICALLY_ASSESSED_PASS_WITH_EDGE_RISK",
        "direct_sha256": DIRECT_SOURCE,
        "direct_worker_seconds": result["codex_wall_monotonic_seconds"],
        "direct_token_usage": result["reported_usage"],
        "ctl_run_count": 0,
        "ctl_worktree_clean": True,
        "beads_task": "open_unclaimed",
        "write_scope": list(ALLOWED_WRITES),
        "verification_profile_digest": PROFILE_DIGEST,
        "runtime_contract": {"model":MODEL,"reasoning":"medium","sdk_version":SDK,"adapter_version":ADAPTER},
        "next_gate": "SEPARATE_OWNER_AUTHORIZATION_FOR_CTL_RUN_PREPARE_CLAIM__NO_MODEL",
        "paid_worker_started": False,
    }


def main() -> int:
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--read-only",action="store_true")
    args=ap.parse_args()
    if not args.read_only:
        ap.error("Explicit --read-only required: this program never claims tasks")
    try:
        print(json.dumps(audit(),indent=2,sort_keys=True))
        return 0
    except Exception as exc:
        print(json.dumps({"decision":"D2_CTL_READ_ONLY_PREPARE_GATE_BLOCKED",
                          "error_type":type(exc).__name__,
                          "reason":str(exc)[:400]}),file=sys.stderr)
        return 2


if __name__=="__main__":
    raise SystemExit(main())
