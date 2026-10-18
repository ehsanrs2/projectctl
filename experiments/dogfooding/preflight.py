#!/usr/bin/env python3
"""Offline, read-only D0 environment preflight; no model calls or state writes."""
from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


EXPECTED_SDK = '0.160.0'


def _version(binary: str, args: list[str]) -> dict[str, object]:
    path = shutil.which(binary)
    # Explicit venv/bin/python does not automatically prepend venv/bin to PATH.
    if not path and binary == 'projectctl':
        candidate = Path(sys.executable).parent / binary
        if candidate.is_file() and os.access(candidate, os.X_OK):
            path = str(candidate)
    if not path:
        return {'available': False, 'version': None}
    try:
        result = subprocess.run([path, *args], capture_output=True, text=True,
                                timeout=5, check=False)
        lines = (result.stdout or result.stderr).strip().splitlines()
        version = lines[0][:100] if result.returncode == 0 and lines else None
        # Do not inadvertently serialize host paths printed by a probe.
        if version and ('/home/' in version or '/Users/' in version):
            version = 'redacted'
        return {'available': result.returncode == 0, 'version': version}
    except (OSError, subprocess.TimeoutExpired):
        return {'available': False, 'version': None}


def _package_version(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def _git(repo: Path, *args: str) -> str | None:
    try:
        p = subprocess.run(['git', '-C', str(repo), *args], capture_output=True,
                           text=True, timeout=5, check=False)
        return p.stdout.strip() if p.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def inspect(repo: Path | None = None) -> dict[str, object]:
    environment_blockers: list[dict[str, str]] = []
    pending_gates: list[dict[str, str]] = []

    def env_block(code: str, reason: str) -> None:
        environment_blockers.append({'code': code, 'reason': reason})

    def gate(code: str, reason: str) -> None:
        pending_gates.append({'code': code, 'reason': reason})

    git = _version('git', ['--version'])
    bd = _version('bd', ['version'])
    codex = _version('codex', ['--version'])
    projectctl = _version('projectctl', ['version'])
    sdk = _package_version('openai-codex')
    if not git['available']:
        env_block('GIT_UNAVAILABLE', 'Git version probe unavailable.')
    if not bd['available']:
        env_block('BLOCKED_TASK_AUTHORITY', 'Local Beads executable bd is not available via bd version.')
    if sdk != EXPECTED_SDK:
        env_block('CODEX_SDK_PIN_MISSING', 'Pinned openai-codex 0.160.0 is not installed in this Python environment.')
    if not codex['available']:
        env_block('CODEX_RUNTIME_UNAVAILABLE', 'Standalone Codex CLI version probe unavailable.')
    if not projectctl['available']:
        env_block('PROJECTCTL_CLI_UNAVAILABLE', 'ProjectCTL version command unavailable.')

    gate('SDK_MODEL_RUNTIME_UNVERIFIED',
         'Offline inspection cannot demonstrate actual gpt-6-luna acceptance by the pinned Python SDK.')

    if repo is None:
        gate('DISPOSABLE_REPO_REQUIRED', 'D1 requires a clean, dedicated local Git repository.')
        git_state: dict[str, object] = {'provided': False, 'is_git': False,
                                        'clean': False, 'has_remote': None}
    else:
        top = _git(repo, 'rev-parse', '--show-toplevel')
        status = _git(repo, 'status', '--porcelain=v1', '--untracked-files=all') if top else None
        remotes = _git(repo, 'remote') if top else None
        clean = status == ''
        git_state = {'provided': True, 'is_git': top is not None,
                     'clean': clean, 'has_remote': bool(remotes) if remotes is not None else None}
        if top is None:
            gate('REPO_NOT_GIT', 'Supplied path is not a readable Git worktree.')
        elif not clean:
            gate('REPO_DIRTY', 'Disposable repository has tracked or untracked changes.')
        if top and (remotes is None or remotes):
            gate('REMOTE_STATUS_UNKNOWN_OR_PRESENT', 'Disposable repository must have no Git remotes.')

    gate('PROJECT_POLICY_UNVERIFIED',
         'Scope governance, task readiness, verification, and quota require D1 operator inspection.')
    if not os.environ.get('PROJECTCTL_HOME'):
        gate('ISOLATED_STATE_ROOT_REQUIRED',
             'D1 requires an explicitly selected new and isolated PROJECTCTL_HOME.')
    else:
        gate('ISOLATED_STATE_ROOT_UNVERIFIED',
             'PROJECTCTL_HOME is set; its emptiness and isolation were not verified offline.')

    return {
        'schema': 'projectctl.dogfooding_d0_preflight.v2',
        'mode': 'offline_read_only_zero_inference',
        'python': '.'.join(map(str, sys.version_info[:3])),
        'environment': {'git': git, 'projectctl': projectctl, 'beads_bd': bd,
                        'codex_cli': codex, 'openai_codex_sdk': {
                            'available': sdk is not None, 'version': sdk,
                            'pinned_expected': EXPECTED_SDK,
                            'model_resolution': 'unverified_without_runtime'}},
        'repository': git_state,
        'isolation': {'projectctl_home_configured': bool(os.environ.get('PROJECTCTL_HOME')),
                      'secrets_read': False, 'network_used': False,
                      'projectctl_state_mutated': False},
        'environment_blockers': environment_blockers,
        'environment_status': 'BLOCKED' if environment_blockers else 'READY_FOR_RUNTIME_PROBE',
        'pending_d1_gates': pending_gates,
        'blockers': environment_blockers + pending_gates,
        'status': 'D1_NO_GO',
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, help='Disposable clean local Git repo; path is not emitted.')
    args = parser.parse_args()
    print(json.dumps(inspect(args.repo), indent=2, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
