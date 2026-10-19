#!/usr/bin/env python3
"""One-time, local-only D1 fixture policy preparation. Never launches a worker."""
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


TASK_ID = "d1ctl-lh4"
SETUP_BASE = "1b38e7526c00009fd44a910e438d74969f00b3c9"
SOURCE_BASE = "da9379c70571c9366f5adfccecdfab148c814fc2"
SPEC_SHA = "aac3d5e847cd24849e92860553459bae9f7cbf70cbf00073eba140270160253d"
INITIAL_UNTRACKED = {
    "?? .projectctl/adoption.yaml",
    "?? .projectctl/config.yaml",
    "?? .projectctl/state.sqlite",
    "?? .projectctl/telemetry.sqlite",
    "?? docs/PROJECT_STATE.yaml",
}
PENDING_TRACKED = [".gitignore", "docs/PROJECT_STATE.yaml",
                   "projectctl.scope.yaml", "projectctl.verification.yaml"]


def git(root: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(root), *args], text=True,
                            capture_output=True, timeout=10, check=False)
    if result.returncode != 0:
        raise RuntimeError("Git preflight failed at " + args[0])
    return result.stdout.strip()


def prepare(root_arg: Path) -> tuple[Path, dict[Path, str], dict[str, str]]:
    if root_arg.is_symlink():
        raise ValueError("refusing symlinked --repo")
    root = root_arg.resolve(strict=True)
    if tuple(root.parts[-3:]) != ("projectctl-dogfood-d1", "fixtures", "ctl"):
        raise ValueError("repository must be the isolated dogfooding ctl fixture")
    if git(root, "rev-parse", "--show-toplevel") != str(root):
        raise ValueError("repo is not the top-level Git root")
    if git(root, "rev-parse", "HEAD") != SETUP_BASE:
        raise ValueError("unexpected setup HEAD (do not run twice)")
    if git(root, "rev-parse", SOURCE_BASE + "^{commit}") != SOURCE_BASE:
        raise ValueError("frozen source baseline missing")
    if git(root, "merge-base", "--is-ancestor", SOURCE_BASE, "HEAD"):
        pass  # merge-base emits no stdout on success
    if git(root, "remote"):
        raise ValueError("fixture must have zero remotes")
    status = set(git(root, "status", "--porcelain=v1",
                     "--untracked-files=all").splitlines())
    if status != INITIAL_UNTRACKED:
        raise ValueError("unexpected Git status; no files changed")
    if hashlib.sha256((root / "SPEC.md").read_bytes()).hexdigest() != SPEC_SHA:
        raise ValueError("frozen SPEC content has changed")
    for name in ["POLICY.md", "test_user_id.py", "user_id.py", "docs/PROJECT_STATE.yaml"]:
        item = root / name
        if item.is_symlink() or not item.is_file():
            raise ValueError("required fixture file missing or symlinked: " + name)
    home_env = os.environ.get("PROJECTCTL_HOME")
    expected_home = (root.parent.parent / "ctl-home").resolve()
    if not home_env or Path(home_env).expanduser().resolve() != expected_home:
        raise ValueError("PROJECTCTL_HOME must be the dedicated ctl-home")
    if not expected_home.is_dir() or not (expected_home / "state.sqlite").is_file():
        raise ValueError("ProjectCTL was not initialized under isolated home")
    for name in (".gitignore", ".projectctl/config.yaml"):
        item = root / name
        if item.is_symlink() or not item.is_file():
            raise ValueError("required setup path missing or symlinked: " + name)
    for name in ("projectctl.scope.yaml", "projectctl.verification.yaml"):
        item = root / name
        if item.exists() or item.is_symlink():
            raise FileExistsError("refusing overwrite of " + name)

    original_ignore = (root / ".gitignore").read_text(encoding="utf-8")
    if ".beads/" in original_ignore or ".dolt/" not in original_ignore:
        raise ValueError("unexpected Beads ignore content")
    if ".projectctl/" in original_ignore:
        raise ValueError("ProjectCTL ignore rule already exists")

    config_file = root / ".projectctl/config.yaml"
    cfg = yaml.safe_load(config_file.read_text(encoding="utf-8"))
    if not isinstance(cfg, dict):
        raise ValueError("invalid ProjectCTL config YAML")
    validated = ProjectConfig.model_validate(cfg)
    if (validated.task_store.provider != "beads" or
        validated.code_transport.mode != "local" or
        validated.code_delivery.mode != "local" or
        validated.scope_governance.mode != "optional"):
        raise ValueError("unexpected initialized ProjectCTL authority/policy")
    cfg["scope_governance"] = {"mode": "required"}
    for profile in cfg["model_profiles"].values():
        profile["provider"] = "codex"
        profile["model"] = "gpt-6-luna"
        profile["reasoning"] = "medium"
    updated = ProjectConfig.model_validate(cfg)
    if any(p.model != "gpt-6-luna" or p.reasoning.value != "medium"
           for p in updated.model_profiles.values()):
        raise AssertionError("worker model routing not uniformly pinned")

    scope = ExecutionScopeCatalog.model_validate({
        "schema_kind": "projectctl.execution_scope_catalog",
        "schema_version": 1,
        "tasks": {
            TASK_ID: {
                "task_id": TASK_ID,
                "inputs": [{"path": p, "kind": "exact"} for p in
                           ("SPEC.md", "user_id.py", "test_user_id.py", "POLICY.md")],
                "writes": [{"path": "user_id.py", "kind": "exact"}],
                "resources": [],
            }
        },
    })
    catalog = VerificationCatalog.model_validate({
        "schema_kind": "projectctl.verification_catalog",
        "schema_version": 1,
        "default_profile": "default",
        "profiles": {"default": {
            "id": "default",
            "commands": [{"id": "fixed-unittest",
                          "argv": ["python3", "-B", "-m", "unittest", "-v", "test_user_id.py"],
                          "timeout_seconds": 60, "required": True}],
        }},
    })
    outputs = {
        root / ".gitignore": (
            original_ignore.rstrip("\n") + "\n\n"
            "# Local ProjectCTL operational state (disposable D1 only)\n"
            ".projectctl/\n"
            "__pycache__/\n"
            "*.pyc\n"
        ),
        config_file: yaml.safe_dump(updated.model_dump(mode="json"),
                                    sort_keys=False, allow_unicode=True),
        root / "projectctl.scope.yaml":
            yaml.safe_dump(scope.model_dump(mode="json"),
                           sort_keys=False, allow_unicode=True),
        root / "projectctl.verification.yaml":
            yaml.safe_dump(catalog.model_dump(mode="json"),
                           sort_keys=False, allow_unicode=True),
    }
    manifest = {p.relative_to(root).as_posix(): hashlib.sha256(
        content.encode("utf-8")).hexdigest() for p, content in outputs.items()}
    return root, outputs, manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--ack-disposable", action="store_true")
    args = parser.parse_args()

    try:
        root, outputs, hashes = prepare(args.repo)
        if args.apply and args.ack_disposable:
            # Each path has already been checked for unexpected prior contents.
            for dest, body in outputs.items():
                if dest.name in ("projectctl.scope.yaml", "projectctl.verification.yaml"):
                    with dest.open("x", encoding="utf-8") as handle:
                        handle.write(body)
                else:
                    dest.write_text(body, encoding="utf-8")
            action = "POLICY_FILES_WRITTEN"
        else:
            action = "PREVIEW_ONLY"
        print(json.dumps({"status": action, "task_id": TASK_ID,
                          "modified_paths": sorted(hashes),
                          "expected_sha256": hashes,
                          "next_action": "review and commit only human-managed files; no worker"},
                         sort_keys=True))
        return 0
    except Exception as exc:
        print(json.dumps({"status": "BLOCKED", "reason_type": type(exc).__name__,
                          "reason": str(exc)[:200]}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
