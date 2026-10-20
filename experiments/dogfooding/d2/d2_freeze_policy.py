#!/usr/bin/env python3
"""D2 isolated ProjectCTL policy freeze: preview or one approved local-only commit.

Never launches a worker, claims a task, requests quota, or modifies the D2 direct arm.
Research checkout must invoke with the existing isolated D0 ProjectCTL venv.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from datetime import datetime, timezone

import yaml

from projectctl.schemas.config import ProjectConfig
from projectctl.schemas.execution_scope import ExecutionScopeCatalog
from projectctl.schemas.verification import VerificationCatalog, DEFAULT_PROTECTED_PATHS
from experiments.dogfooding.d2.gitignore_review import (
    review_beads_gitignore, review_ignored_paths, validate_root_beads_gate_lock
)

TASK = "d2ctl-g4q"
BASE = "32836ea5633230e50fb9d907dcdba83e357bcfc6"
SETUP_HEAD = "ab34052b3cb2ece4452504ffa457ecf2d358891f"
SPEC_SHA = "8264746827bbb7300bf234023e6617324c78f37aecf524f2427a686925da8815"
EXPECTED_UNTRACKED = {
    "?? .projectctl/adoption.yaml",
    "?? .projectctl/config.yaml",
    "?? .projectctl/state.sqlite",
    "?? .projectctl/telemetry.sqlite",
    "?? docs/PROJECT_STATE.yaml",
}
TRACKED_COMMIT = {
    ".gitignore", "docs/PROJECT_STATE.yaml",
    "projectctl.scope.yaml", "projectctl.verification.yaml",
}
ALLOWED_SOURCE = {
    "d2events/parse.py", "d2events/report.py", "d2events/cli.py",
}
CHECK = ["python3", "-B", "-m", "unittest", "discover", "-s", "tests",
         "-p", "test_*.py", "-v"]


def run(argv: list[str], *, cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess:
    p = subprocess.run(argv, cwd=cwd, capture_output=True, text=True,
                       check=False, timeout=30)
    if check and p.returncode != 0:
        raise ValueError(f"Failed prerequisite: {argv[0]} {argv[1:3]} (exit {p.returncode})")
    return p


def git(root: Path, *args: str) -> str:
    return run(["git", "-C", str(root), *args]).stdout.strip()


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_task(root: Path, task_id: str) -> None:
    bd = run(["bd", "-C", str(root), "show", task_id, "--json"])
    data = json.loads(bd.stdout)
    issues = data if isinstance(data, list) else [data]
    if len(issues) != 1 or issues[0].get("id") != task_id:
        raise ValueError("Beads canonical Task mismatch")
    item = issues[0]
    if item.get("status") != "open" or item.get("assignee"):
        raise ValueError("D2 task is already claimed/closed")
    if item.get("description", "").rstrip("\n") != (root/"SPEC.md").read_text().rstrip("\n"):
        raise ValueError("Beads task description drifted from frozen SPEC")
    data = json.loads(run(["bd", "-C", str(root), "ready", "--json"]).stdout)
    ready = data if isinstance(data, list) else data.get("issues", data.get("ready", []))
    if len(ready) != 1 or ready[0].get("id") != task_id:
        raise ValueError("D2 task is not sole ready Beads task")


def build_outputs(root: Path, cfg: dict, current_ignore: str) -> dict[Path, str]:
    validated = ProjectConfig.model_validate(cfg)
    if (validated.task_store.provider != "beads"
            or validated.code_transport.mode != "local"
            or validated.code_delivery.mode != "local"
            or validated.scope_governance.mode != "optional"
            or validated.orchestration.max_active_runs != 1):
        raise ValueError("ProjectCTL local adoption configuration drift")
    cfg["scope_governance"] = {"mode": "required"}
    for profile in cfg["model_profiles"].values():
        profile["provider"] = "codex"
        profile["model"] = "gpt-6-luna"
        profile["reasoning"] = "medium"
    target = ProjectConfig.model_validate(cfg)
    assert target.scope_governance.mode == "required"
    assert all(v.model == "gpt-6-luna" and v.reasoning.value == "medium"
               for v in target.model_profiles.values())

    inputs = ("SPEC.md", "POLICY.md", "d2events/__init__.py",
              "d2events/parse.py", "d2events/report.py", "d2events/cli.py",
              "tests/__init__.py", "tests/test_parser.py",
              "tests/test_report.py", "tests/test_cli.py")
    scope = ExecutionScopeCatalog.model_validate({
        "schema_kind": "projectctl.execution_scope_catalog",
        "schema_version": 1,
        "tasks": {TASK: {
            "task_id": TASK,
            "inputs": [{"path": name, "kind": "exact"} for name in inputs],
            "writes": [{"path": name, "kind": "exact"}
                       for name in sorted(ALLOWED_SOURCE)],
            "resources": [],
        }}
    })
    protected = sorted(set(DEFAULT_PROTECTED_PATHS + [
        ".gitignore", "SPEC.md", "POLICY.md", "tests/**",
        "d2events/__init__.py", "projectctl.scope.yaml",
        "projectctl.verification.yaml",
    ]))
    catalog = VerificationCatalog.model_validate({
        "schema_kind": "projectctl.verification_catalog",
        "schema_version": 1,
        "default_profile": "default",
        "profiles": {"default": {
            "id": "default",
            "commands": [{
                "id": "fixed-d2-unittest",
                "argv": CHECK,
                "timeout_seconds": 120,
                "required": True,
            }],
            "diff_policy": {
                "require_changes": True,
                "max_changed_paths": 3,
                "allow_symlink_changes": False,
                "protected_paths": protected,
            },
        }},
    })
    assert {x.path for x in scope.tasks[TASK].writes} == ALLOWED_SOURCE
    assert catalog.profiles["default"].commands[0].argv == CHECK

    return {
        root / ".gitignore": current_ignore.rstrip("\n")
            + "\n\n# D2 isolated ProjectCTL operational databases / config\n"
            + ".projectctl/\n",
        root / ".projectctl/config.yaml": yaml.safe_dump(
            target.model_dump(mode="json"), sort_keys=False, allow_unicode=True
        ),
        root / "projectctl.scope.yaml": yaml.safe_dump(
            scope.model_dump(mode="json"), sort_keys=False, allow_unicode=True
        ),
        root / "projectctl.verification.yaml": yaml.safe_dump(
            catalog.model_dump(mode="json"), sort_keys=False, allow_unicode=True
        ),
    }


def prepare(root: Path, research: Path, home: Path) -> tuple[dict[Path, str], dict]:
    if any(x.is_symlink() for x in (root, research, home)):
        raise ValueError("symlinked root/research/home not allowed")
    root = root.resolve(strict=True)
    research = research.resolve(strict=True)
    home = home.resolve(strict=True)
    if root != Path.home()/".local/state/projectctl-dogfood-d2/fixtures/ctl":
        raise ValueError("Only exact D2 ctl disposable fixture is allowed")
    if research != Path.home()/"project/My/projectctl-advisory-lab":
        raise ValueError("Only the pinned research checkout is allowed")
    if home != Path.home()/".local/state/projectctl-dogfood-d2/ctl-home":
        raise ValueError("PROJECTCTL_HOME must be isolated to D2")
    if not (home/"state.sqlite").is_file():
        raise ValueError("Missing D2 ProjectCTL initialized operational DB")
    if git(research, "branch", "--show-current") != "research/advisory-skills-eval":
        raise ValueError("Wrong research branch")
    if git(research, "status", "--porcelain=v1", "--untracked-files=all"):
        raise ValueError("Research checkout is dirty")
    if git(root, "rev-parse", "--show-toplevel") != str(root):
        raise ValueError("D2 CTL Git top-level mismatch")
    if git(root, "rev-parse", "HEAD") != SETUP_HEAD:
        raise ValueError("D2 CTL setup commit drifted; do not repeat")
    if git(root, "rev-parse", "HEAD^") != BASE:
        raise ValueError("D2 original source commit is not setup parent")
    if git(root, "diff", "--name-only", BASE, SETUP_HEAD) != ".gitignore":
        raise ValueError("Setup commit changed application files")
    if git(root, "remote"):
        raise ValueError("D2 ctl repository unexpectedly has remotes")
    actual = set(git(root, "status", "--porcelain=v1",
                     "--untracked-files=all").splitlines())
    if actual != EXPECTED_UNTRACKED:
        raise ValueError(f"Unexpected D2 post-adoption Git status: {sorted(actual)}")
    if sha(root/"SPEC.md") != SPEC_SHA:
        raise ValueError("D2 frozen SPEC SHA mismatch")
    frozen_path = root.parent.parent/"observations/offline-setup-v1/baseline-manifest.json"
    m = json.loads(frozen_path.read_text(encoding="utf-8"))
    direct = root.parent/"direct"
    if (m.get("status") != "D2_OFFLINE_BASELINES_FROZEN"
            or m.get("base_sha") != BASE
            or Path(m["ctl_path"]).resolve() != root
            or Path(m["direct_path"]).resolve() != direct):
        raise ValueError("Original paired freeze manifest mismatch")
    if (git(direct, "rev-parse", "HEAD") != BASE
            or git(direct, "remote")
            or git(direct, "status", "--porcelain=v1", "--untracked-files=all")):
        raise ValueError("D2 direct arm is not pristine")
    if (direct/".beads").exists() or (direct/".projectctl").exists():
        raise ValueError("D2 direct arm has control-plane artifacts")
    for relative, digest in m["all_files_sha256"].items():
        for base in (root, direct):
            if base == root and relative == ".gitignore":
                continue
            path = base/relative
            if not path.is_file() or path.is_symlink() or sha(path) != digest:
                raise ValueError(f"Frozen application source changed: {relative}")

    setup = root.parent.parent/"observations/beads-setup-v1"
    frozen_beads_ignore = (setup/"gitignore-after.txt").read_text(encoding="utf-8")
    current_ignore = (root/".gitignore").read_text(encoding="utf-8")
    base_ignore = run(["git", "-C", str(root), "show", BASE + ":.gitignore"]).stdout
    review_beads_gitignore(base_ignore, current_ignore, frozen_beads_ignore)
    ignored = subprocess.run(["git", "-C", str(root), "ls-files", "--others",
                              "--ignored", "--exclude-standard", "-z"],
                             capture_output=True, check=True, timeout=15).stdout
    ignored_paths = [part.decode() for part in ignored.split(b"\0") if part]
    review_ignored_paths(ignored_paths)
    validate_root_beads_gate_lock(root, ignored_paths)

    canonical_task(root, TASK)

    for name in (".projectctl/config.yaml", ".projectctl/adoption.yaml",
                 "docs/PROJECT_STATE.yaml"):
        if not (root/name).is_file() or (root/name).is_symlink():
            raise ValueError("Missing or symlinked ProjectCTL adoption source: "+name)
    for name in ("projectctl.scope.yaml", "projectctl.verification.yaml"):
        if (root/name).exists() or (root/name).is_symlink():
            raise FileExistsError("Policy file already exists: "+name)
    current_cfg = yaml.safe_load((root/".projectctl/config.yaml").read_text())
    if not isinstance(current_cfg, dict):
        raise ValueError("ProjectCTL config YAML has invalid shape")
    outputs = build_outputs(root, current_cfg, current_ignore)
    hashes = {p.relative_to(root).as_posix(): hashlib.sha256(
        value.encode()).hexdigest() for p,value in outputs.items()}
    return outputs, {"candidate_sha256": hashes,
                     "task":TASK, "base_commit": BASE, "setup_commit":SETUP_HEAD,
                     "frozen_spec_sha256": SPEC_SHA,
                     "protected_paths": sorted(TRACKED_COMMIT),
                     "expected_worker_changes": sorted(ALLOWED_SOURCE)}


def apply(root: Path, outputs: dict[Path,str], summary: dict) -> dict:
    out = root.parent.parent/"observations/policy-freeze-v1"
    if out.exists() or out.is_symlink():
        raise FileExistsError("D2 policy evidence already exists")
    out.mkdir(mode=0o700)
    # Create first, stop on any partial failure. No retries or silent cleanup.
    for path,value in outputs.items():
        if path.name in ("projectctl.scope.yaml", "projectctl.verification.yaml"):
            with path.open("x", encoding="utf-8") as handle:
                handle.write(value)
        else:
            path.write_text(value, encoding="utf-8")
        if sha(path) != summary["candidate_sha256"][path.relative_to(root).as_posix()]:
            raise ValueError("Unexpected digest after policy file write")
    expected = {"?? docs/PROJECT_STATE.yaml",
                "?? projectctl.scope.yaml", "?? projectctl.verification.yaml",
                " M .gitignore"}
    status = set(git(root, "status", "--porcelain=v1",
                     "--untracked-files=all").splitlines())
    if status != expected:
        raise ValueError(f"Unexpected source paths after policy write: {sorted(status)}")
    rels = sorted(TRACKED_COMMIT)
    run(["git", "-C", str(root), "add", "--", *rels])
    names = set(git(root, "diff", "--cached", "--name-only").splitlines())
    if names != TRACKED_COMMIT:
        raise ValueError(f"Unexpected staged paths: {sorted(names)}")
    run(["git", "-C", str(root), "diff", "--cached", "--check"])
    run(["git", "-C", str(root), "-c", "commit.gpgsign=false",
         "-c", "user.name=D2 Fixture", "-c", "user.email=d2-fixture@invalid.example",
         "commit", "-m", "chore(d2): freeze required scope and fixed verification"])
    head = git(root, "rev-parse", "HEAD")
    if git(root, "rev-parse", "HEAD^") != SETUP_HEAD:
        raise ValueError("Unexpected policy commit ancestry")
    if set(git(root, "diff", "--name-only", SETUP_HEAD, head).splitlines()) != TRACKED_COMMIT:
        raise ValueError("Policy commit changed unexpected paths")
    if git(root, "status", "--porcelain=v1", "--untracked-files=all"):
        raise ValueError("D2 ctl fixture must be clean after policy freeze")
    if git(root.parent/"direct", "rev-parse", "HEAD") != BASE:
        raise ValueError("D2 direct source arm modified")
    canonical_task(root, TASK)
    report = {**summary, "status":"D2_POLICY_FROZEN_LOCAL_ONLY",
              "policy_commit": head,
              "observed_at_utc":datetime.now(timezone.utc).isoformat()}
    (out/"freeze-report.json").write_text(json.dumps(report,indent=2,sort_keys=True)+"\n")
    return report


def main() -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo",type=Path,required=True)
    parser.add_argument("--preview",action="store_true")
    parser.add_argument("--apply-and-freeze",action="store_true")
    parser.add_argument("--ack-local-commit",action="store_true")
    args=parser.parse_args()
    if args.preview == args.apply_and_freeze:
        parser.error("select --preview OR --apply-and-freeze")
    if args.apply_and_freeze and not args.ack_local_commit:
        parser.error("--apply-and-freeze requires --ack-local-commit")
    if args.preview and args.ack_local_commit:
        parser.error("do not use --ack-local-commit in preview")
    try:
        root=args.repo
        home_env=os.environ.get("PROJECTCTL_HOME","")
        if not home_env:
            raise ValueError("Set isolated PROJECTCTL_HOME first")
        outputs,summary=prepare(root,Path.home()/"project/My/projectctl-advisory-lab",
                                Path(home_env))
        if args.preview:
            result={**summary,"status":"D2_POLICY_PREVIEW_PASS__NO_FILES_WRITTEN"}
        else:
            result=apply(root.resolve(),outputs,summary)
        print(json.dumps(result,sort_keys=True,indent=2))
        return 0
    except Exception as exc:
        print(json.dumps({"status":"D2_POLICY_BLOCKED",
                          "error_type":type(exc).__name__,
                          "reason":str(exc)[:500]}),file=sys.stderr)
        return 2


if __name__=="__main__":
    raise SystemExit(main())
