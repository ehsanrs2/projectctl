#!/usr/bin/env python3
"""D2 paired-run preflight. Source read-only; does NOT run inference or prepare a run.

This invokes already-qualified D2 source audit, version-only Codex capability
probe, strategy negotiation, CLI help and model pin inspection. It intentionally
does NOT refresh quota: recheck fresh quota at each later paid-execution gate.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import yaml

from projectctl.schemas.config import ProjectConfig
from experiments.dogfooding.d2.d2_post_freeze_audit import audit as frozen_audit

ROOT = Path.home() / ".local/state/projectctl-dogfood-d2"
RESEARCH = Path.home() / "project/My/projectctl-advisory-lab"
CTL = ROOT / "fixtures/ctl"
DIRECT = ROOT / "fixtures/direct"
VENV = Path.home() / ".local/share/projectctl-dogfood-d0/venv"
MODEL = "gpt-6-luna"
SDK = "0.160.0"
ADAPTER = "0.41.0"
CODEX_CLI = "codex-cli 0.163.0"
BASE = "32836ea5633230e50fb9d907dcdba83e357bcfc6"
POLICY_HEAD = "3c69dd42497acadadc5d64e7b4abe5d412b309f5"
TASK = "d2ctl-g4q"
EXPECTED_FLAGS = (
    "--ignore-user-config", "--ignore-rules", "--strict-config",
    "--ephemeral", "--json", "--model", "--sandbox", "--cd",
)
ALLOWED_WRITES = ("d2events/cli.py", "d2events/parse.py", "d2events/report.py")
ORDER = ("direct_cli", "projectctl")


def direct_prompt(spec: str, policy: str) -> str:
    """Exact frozen direct-arm task wrapper; never read ctl implementation."""
    return (
        "You are implementing one isolated D2 coding task in this Git repository.\n"
        "Implement the supplied SPEC exactly using the Python standard library only.\n"
        "Only modify d2events/parse.py, d2events/report.py and d2events/cli.py.\n"
        "Do not edit SPEC.md, POLICY.md, tests/**, d2events/__init__.py, "
        "or any other file.\n"
        "Do not create Git commits, branches, tags, or remotes.\n"
        "Do not use network services, plugins, apps, subagents, or external repositories.\n"
        "Do not inspect ProjectCTL, Beads, ctl arm, or files outside this Git repository.\n"
        "You may inspect and run frozen tests but must not modify them.\n"
        "Implement the task independently and provide a brief final summary.\n"
        "\n=== SPEC.md ===\n"
        + spec
        + "\n=== POLICY.md ===\n"
        + policy
    )


def check_call(argv: list[str], *, timeout: int = 35) -> str:
    output = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    if output.returncode != 0:
        raise ValueError(f"Read-only probe failed: {argv[:4]} exit={output.returncode}")
    return output.stdout


def validate_cli_help(version: str, root_help: str, exec_help: str) -> None:
    if version.strip() != CODEX_CLI:
        raise ValueError(f"Direct Codex CLI version drift: {version.strip()}")
    missing = [flag for flag in EXPECTED_FLAGS if flag not in exec_help]
    if missing or "--disable" not in root_help:
        raise ValueError(f"CLI lacks pinned isolation flags: {missing}")


def validate_strategy(capability: dict, strategy: dict) -> None:
    runtime = capability["runtime"]
    if capability.get("probe_kind") != "version_only":
        raise ValueError("Expected version-only adapter probe (no model turn)")
    if (runtime.get("sdk_name"), runtime.get("sdk_version")) != ("openai-codex", SDK):
        raise ValueError("ProjectCTL Codex SDK version drift")
    if runtime.get("runtime_version") != SDK or runtime.get("adapter_version") != ADAPTER:
        raise ValueError("ProjectCTL pinned runtime/adapter drift")
    def usable(node: dict) -> bool:
        return node.get("runtime") == "supported" and node.get("adapter") == "supported"
    perms = capability["permissions"]
    if (not usable(capability["modes"]["default"])
            or not usable(perms["sandboxes"]["workspace_write"])
            or not usable(perms["approvals"]["deny_all"])):
        raise ValueError("Required Codex permissions are unsupported")
    if (strategy.get("task_id") != TASK
            or strategy.get("requested") != "direct"
            or strategy.get("resolved") != "direct"
            or strategy.get("compatible") is not True
            or strategy.get("fallback_used") is not False
            or strategy.get("unsupported")):
        raise ValueError("Direct strategy is not strictly compatible")
    expected = {"approval": "deny_all", "mode": "default",
                "network": "disabled", "sandbox": "workspace_write"}
    if strategy.get("execution") != expected or strategy.get("planning") is not None:
        raise ValueError("Worker execution permissions drift")


def main() -> int:
    try:
        exe = Path(sys.executable).resolve()
        if exe != (VENV / "bin/python").resolve():
            raise ValueError("Run through pinned D0 isolated Python venv")
        if os.environ.get("PROJECTCTL_HOME") != str(ROOT / "ctl-home"):
            raise ValueError("Wrong or missing isolated PROJECTCTL_HOME")
        if os.environ.get("BD_ACTOR") != "d2-dogfood-owner":
            raise ValueError("Wrong D2 Beads actor")
        frozen = frozen_audit()
        assert frozen["decision"] == "D2_POST_FREEZE_READ_ONLY_PASS"
        assert frozen["policy_commit"] == POLICY_HEAD and frozen["baseline_commit"] == BASE
        assert frozen["task"] == TASK and frozen["direct_unchanged"] is True
        assert tuple(frozen["worker_writes"]) == ALLOWED_WRITES
        assert frozen["verification_test_count"] == 26
        cfg = ProjectConfig.model_validate(
            yaml.safe_load((CTL / ".projectctl/config.yaml").read_text(encoding="utf-8")))
        balanced = next((value for key, value in cfg.model_profiles.items()
                         if getattr(key, "value", str(key)) == "balanced"), None)
        if balanced is None or balanced.model != MODEL or balanced.reasoning.value != "medium":
            raise ValueError("Balanced model identity mismatch")
        if importlib.metadata.version("openai-codex") != SDK:
            raise ValueError("Installed Codex SDK package version drift")
        cli = shutil.which("codex")
        if not cli:
            raise ValueError("Codex CLI executable not found")
        version = check_call([cli, "--version"])
        root_help = check_call([cli, "--help"])
        exec_help = check_call([cli, "exec", "--help"])
        validate_cli_help(version, root_help, exec_help)

        capability = json.loads(check_call([
            str(VENV / "bin/projectctl"), "worker", "capabilities",
            "--provider", "codex", "--json"]))
        strategy = json.loads(check_call([
            str(VENV / "bin/projectctl"), "worker", "strategy", TASK,
            "--project", str(CTL), "--provider", "codex",
            "--requested", "direct", "--json"]))
        validate_strategy(capability, strategy)

        spec = (DIRECT / "SPEC.md").read_text(encoding="utf-8")
        policy = (DIRECT / "POLICY.md").read_text(encoding="utf-8")
        prompt = direct_prompt(spec, policy)
        prompt_sha = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        result = {
            "decision": "D2_NO_INFERENCE_PREFLIGHT_PASS",
            "frozen_policy_head": POLICY_HEAD,
            "direct_baseline": BASE,
            "task": TASK,
            "predeclared_order": list(ORDER),
            "direct_prompt_sha256": prompt_sha,
            "model": MODEL,
            "reasoning_effort": "medium",
            "direct_codex_cli_version": version.strip(),
            "ctl_codex_sdk_version": SDK,
            "ctl_adapter_version": ADAPTER,
            "probe_kind": "version_only",
            "strategy": "direct",
            "execution": strategy["execution"],
            "worker_writes": list(ALLOWED_WRITES),
            "verification_test_count": 26,
            "quota_observation": "RECHECK_FRESH_OFFICIAL_QUOTA_BEFORE_EACH_ARM",
            "paid_execution": "NOT_AUTHORIZED_OR_STARTED",
            "caveat": ("CLI 0.163.0 and SDK 0.160.0 are different "
                       "interfaces/runtimes; version-only probe does not "
                       "verify paid model identity or equivalent tool exposure."),
        }
        print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(json.dumps({"decision": "D2_NO_INFERENCE_PREFLIGHT_BLOCKED",
                          "error_type": type(exc).__name__,
                          "reason": str(exc)[:400]}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
