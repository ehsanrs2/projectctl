#!/usr/bin/env python3
"""Offline, read-only D0 environment preflight. Emits redacted JSON only."""
from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


def _version(binary: str, args: list[str]) -> dict[str, object]:
    path = shutil.which(binary)
    if not path:
        return {"available": False, "version": None}
    try:
        result = subprocess.run([path, *args], capture_output=True, text=True, timeout=5, check=False)
        out = (result.stdout or result.stderr).strip().splitlines()
        return {"available": result.returncode == 0, "version": out[0][:100] if result.returncode == 0 and out else None}
    except (OSError, subprocess.TimeoutExpired):
        return {"available": False, "version": None}


def _package_version(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def _git(repo: Path, *args: str) -> str | None:
    try:
        p = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, timeout=5, check=False)
        return p.stdout.strip() if p.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def inspect(repo: Path | None = None) -> dict[str, object]:
    blockers: list[dict[str, str]] = []
    def block(code: str, reason: str) -> None:
        blockers.append({"code": code, "reason": reason})

    git = _version("git", ["--version"])
    bd = _version("bd", ["--version"])
    codex = _version("codex", ["--version"])
    projectctl = _version("projectctl", ["--version"])
    sdk = _package_version("openai-codex")
    if not git["available"]:
        block("GIT_UNAVAILABLE", "Git executable/version probe unavailable.")
    if not bd["available"]:
        block("BLOCKED_TASK_AUTHORITY", "Local Beads executable `bd` is unavailable or its version probe failed.")
    if sdk != "0.160.0":
        block("CODEX_SDK_PIN_MISSING", "The active Python environment does not report pinned openai-codex 0.160.0.")
    block("SDK_MODEL_RUNTIME_UNVERIFIED", "Static source forwards a model string; offline checks cannot establish gpt-6-luna runtime resolution.")
    if not codex["available"]:
        block("CODEX_RUNTIME_UNAVAILABLE", "Codex CLI version probe is unavailable; this does not establish SDK runtime readiness.")
    if repo is None:
        block("DISPOSABLE_REPO_REQUIRED", "Pass --repo for a disposable, clean local Git repository used only for this experiment.")
        git_state: dict[str, object] = {"provided": False, "is_git": False, "clean": False, "has_remote": None}
    else:
        top = _git(repo, "rev-parse", "--show-toplevel")
        status = _git(repo, "status", "--porcelain=v1", "--untracked-files=all") if top else None
        remotes = _git(repo, "remote") if top else None
        clean = status == ""
        git_state = {"provided": True, "is_git": top is not None, "clean": clean, "has_remote": bool(remotes) if remotes is not None else None}
        if top is None:
            block("REPO_NOT_GIT", "The supplied path is not a readable Git worktree.")
        elif not clean:
            block("REPO_DIRTY", "The supplied repository has tracked or untracked changes.")
        elif remotes is None or remotes:
            block("REMOTE_STATUS_UNKNOWN_OR_PRESENT", "The disposable repository must have no Git remotes.")
        # We intentionally never serialize repository paths or config contents.
        block("PROJECT_POLICY_UNVERIFIED", "Project config, scope governance, verification policy, and quota controls require operator review in the disposable repo.")
        block("ISOLATED_STATE_ROOT_REQUIRED", "D1 must set a fresh dedicated PROJECTCTL_HOME before any ProjectCTL state operation.")

    if not projectctl["available"]:
        block("PROJECTCTL_CLI_UNAVAILABLE", "ProjectCTL CLI version probe is unavailable in PATH.")
    return {
        "schema": "projectctl.dogfooding_d0_preflight.v1",
        "mode": "offline_read_only_zero_inference",
        "python": ".".join(map(str, sys.version_info[:3])),
        "environment": {"git": git, "projectctl": projectctl, "beads_bd": bd, "codex_cli": codex,
                        "openai_codex_sdk": {"available": sdk is not None, "version": sdk,
                                              "pinned_expected": "0.160.0", "model_resolution": "unverified_without_runtime"}},
        "repository": git_state,
        "isolation": {"projectctl_home_configured": bool(os.environ.get("PROJECTCTL_HOME")),
                      "secrets_read": False, "network_used": False, "projectctl_state_mutated": False},
        "blockers": blockers,
        "status": "BLOCKED" if blockers else "READY_FOR_SINGLE_DOGFOOD",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, help="Disposable local Git worktree to inspect; path is not emitted.")
    args = parser.parse_args()
    print(json.dumps(inspect(args.repo), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
