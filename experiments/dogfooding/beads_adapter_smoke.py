#!/usr/bin/env python3
"""Opt-in, model-free Beads 1.3.1 contract smoke inside an owned temporary Git repo."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


def run(argv: list[str], *, cwd: Path, timeout: int = 45) -> str:
    result = subprocess.run(argv, cwd=cwd, capture_output=True, text=True,
                            check=False, timeout=timeout)
    if result.returncode != 0:
        raise RuntimeError(f'{Path(argv[0]).name} {argv[1] if len(argv)>1 else ""} exit={result.returncode}')
    return result.stdout.strip()


def verify_state(client, issue_id: str, status: str, assignee: str | None = None) -> dict:
    issue = client.show(issue_id)
    actual_status = str(issue.get('status', '')).lower()
    if actual_status != status:
        raise AssertionError(f'expected status={status}; actual={actual_status}')
    if assignee is not None and str(issue.get('assignee') or '') != assignee:
        raise AssertionError('claimed assignee mismatch')
    return issue


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true', help='Run the disposable Beads smoke')
    parser.add_argument('--ack-temporary-repo', action='store_true', help='Confirm temporary local repo creation')
    args = parser.parse_args()
    if not args.execute or not args.ack_temporary_repo:
        print(json.dumps({'status': 'NOT_RUN', 'reason': 'Both --execute and --ack-temporary-repo are required'}))
        return 0

    bd = shutil.which('bd')
    git = shutil.which('git')
    if not bd or not git:
        print(json.dumps({'status': 'BLOCKED_DEPENDENCY', 'git': bool(git), 'bd': bool(bd)}))
        return 2

    # Import the real ProjectCTL adapter; never import or invoke a Codex worker.
    from projectctl.integrations.beads.client import BeadsClient

    completed: list[str] = []
    actor = 'd0-smoke-actor'
    source_checkout = Path(__file__).resolve().parents[2]
    temp_parent = Path(tempfile.gettempdir()).resolve()
    if temp_parent == source_checkout or temp_parent.is_relative_to(source_checkout):
        print(json.dumps({'status': 'BLOCKED_UNSAFE_TEMP_ROOT'}))
        return 2

    original_env = dict(os.environ)
    try:
        with tempfile.TemporaryDirectory(prefix='pctl-d0-beads-') as tmp:
            root = Path(tmp)
            home, local_repo = root/'home', root/'repo'
            home.mkdir()
            local_repo.mkdir()
            # Prevent ambient Beads/Dolt database routing to any real user data.
            for key in list(os.environ):
                if key.startswith(('BD_', 'BEADS_', 'DOLT_')):
                    os.environ.pop(key, None)
            os.environ.update({
                'HOME': str(home),
                'XDG_CONFIG_HOME': str(home / '.config'),
                'XDG_DATA_HOME': str(home / '.local' / 'share'),
                'XDG_CACHE_HOME': str(home / '.cache'),
                'GIT_CONFIG_GLOBAL': os.devnull,
                'GIT_CONFIG_NOSYSTEM': '1',
                'BD_ACTOR': actor,
                'BD_DISABLE_METRICS': '1',
                'DO_NOT_TRACK': '1',
                'DOLT_DISABLE_EVENT_FLUSH': '1',
                'BD_NON_INTERACTIVE': '1',
                'BD_LAST_TOUCHED_FALLBACK': '0',
            })
            run([git, 'init', '--quiet', str(local_repo)], cwd=root)
            run([git, 'config', 'user.name', actor], cwd=local_repo)
            run([git, 'config', 'user.email', 'd0-smoke@invalid.example'], cwd=local_repo)
            if run([git, 'remote'], cwd=local_repo):
                raise RuntimeError('temporary Git repo unexpectedly has a remote')
            completed.append('isolated_local_git')

            version = run([bd, 'version'], cwd=local_repo)
            if not version.startswith('bd version 1.3.1'):
                raise RuntimeError('Beads version changed; repeat contract review')
            completed.append('beads_version_1_3_1')

            run([bd, 'init', '--non-interactive', '--skip-agents', '--skip-hooks',
                 '--setup-exclude', '--prefix', 'd0smoke'], cwd=local_repo, timeout=90)
            completed.append('beads_init')
            client = BeadsClient(local_repo, executable=bd, timeout_seconds=40)

            ident = client.create_issue(title='D0 disposable check',
                                        description='No network, project data, or model task.',
                                        issue_type='task', priority=2)
            if not ident or not ident.startswith('d0smoke-'):
                raise AssertionError('unexpected issue id/prefix')
            completed.append('adapter_create_json')

            if ident not in [str(x.get('id')) for x in client.list_all()]:
                raise AssertionError('created issue absent from list_all')
            if ident not in [str(x.get('id')) for x in client.list_ready()]:
                raise AssertionError('created issue absent from list_ready')
            if client.list_dependencies(ident):
                raise AssertionError('new issue has unexpected dependencies')
            verify_state(client, ident, 'open')
            completed.append('adapter_read_ready_show_dep')

            client.claim_issue(ident)
            verify_state(client, ident, 'in_progress', assignee=actor)
            completed.append('adapter_claim_and_ownership')
            run([bd, 'heartbeat', ident], cwd=local_repo)
            completed.append('provider_heartbeat_available')

            # Legacy two-step release: exercise in an uncontended temporary repo only.
            client.release_issue(ident)
            verify_state(client, ident, 'open', assignee='')
            completed.append('adapter_release_single_actor_only')

            client.claim_issue(ident)
            verify_state(client, ident, 'in_progress', assignee=actor)
            run([bd, 'unclaim', ident, '--if-assignee', actor], cwd=local_repo)
            verify_state(client, ident, 'open', assignee='')
            completed.append('provider_atomic_unclaim')

            client.update_status(ident, 'blocked')
            verify_state(client, ident, 'blocked')
            completed.append('adapter_status_block')
            client.update_status(ident, 'open')
            client.close_issue(ident, 'D0 temporary-only smoke complete')
            verify_state(client, ident, 'closed')
            completed.append('adapter_close')
            if run([git, 'remote'], cwd=local_repo):
                raise AssertionError('unexpected Git remote')
            completed.append('no_git_remote')

        print(json.dumps({'status': 'DISPOSABLE_SMOKE_PASS', 'checks': completed,
                          'adapter_release_atomic': False,
                          'provider_lease_renewal_in_adapter': False,
                          'model_calls': 0, 'real_project_mutations': 0,
                          'd1_authorized': False}, sort_keys=True))
        return 0
    except Exception as exc:
        print(json.dumps({'status': 'DISPOSABLE_SMOKE_FAILED', 'checks': completed,
                          'failure_type': type(exc).__name__,
                          'model_calls': 0, 'd1_authorized': False}, sort_keys=True))
        return 2
    finally:
        os.environ.clear()
        os.environ.update(original_env)


if __name__ == '__main__':
    raise SystemExit(main())
