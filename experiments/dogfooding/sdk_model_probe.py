#!/usr/bin/env python3
"""Opt-in one-turn Codex Python SDK model compatibility probe; never runs ProjectCTL D1."""
from __future__ import annotations

import argparse
import importlib.metadata
import json
from pathlib import Path
import tempfile

MODEL = 'gpt-6-luna'
REASONING = 'medium'
PINNED_SDK = '0.160.0'
WIRE_SCHEMA = {
    'type': 'object',
    'properties': {'probe_ok': {'type': 'boolean', 'const': True}},
    'required': ['probe_ok'],
    'additionalProperties': False,
}


def execute_probe() -> dict[str, object]:
    from openai_codex import ApprovalMode, Codex, CodexConfig, ExternalMessage, Sandbox

    # Do not reset HOME: SDK needs the user's already configured login; no secrets read by this script.
    with tempfile.TemporaryDirectory(prefix='projectctl-sdk-model-probe-') as tmp:
        working = Path(tmp)
        config = CodexConfig(
            cwd=str(working), client_name='projectctl-d0-probe',
            client_title='ProjectCTL D0 research model check', client_version='0.41.0',
            experimental_api=True,
            config_overrides=('sandbox_workspace_write.network_access=false',),
        )
        with Codex(config=config) as codex:
            thread = codex.thread_start(
                approval_mode=ApprovalMode.deny_all,
                cwd=str(working),
                developer_instructions=(
                    'This is a read-only capability probe. Do not use tools, access files, '
                    'run commands, or modify the environment. Output only the requested JSON.'
                ),
                ephemeral=True,
                model=MODEL,
                sandbox=Sandbox.read_only,
                config={
                    'model_reasoning_effort': REASONING,
                    'sandbox_workspace_write': {'network_access': False},
                },
            )
            result = thread.run(
                ExternalMessage(
                    tool_name='projectctl_sdk_model_probe',
                    namespace='projectctl',
                    content='Return JSON with probe_ok set to true. No other content.',
                ),
                approval_mode=ApprovalMode.deny_all,
                cwd=str(working),
                model=MODEL,
                output_schema=WIRE_SCHEMA,
                sandbox=Sandbox.read_only,
            )
            status = str(getattr(result.status, 'value', result.status)).lower()
            response = getattr(result, 'final_response', None)
            try:
                payload = json.loads(response) if response else None
            except (ValueError, TypeError):
                payload = None
            success = status == 'completed' and payload == {'probe_ok': True}
            return {
                'status': 'SDK_MODEL_PROBE_PASS' if success else 'SDK_MODEL_PROBE_FAIL',
                'turn_status': status,
                'structured_response_valid': payload == {'probe_ok': True},
                'model': MODEL,
                'reasoning': REASONING,
                'sandbox': 'read_only',
                'projectctl_d1_authorized': False,
            }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--ack-paid', action='store_true')
    args = parser.parse_args()
    if not (args.execute and args.ack_paid):
        print(json.dumps({'status': 'NOT_RUN', 'reason': 'Requires --execute and --ack-paid',
                          'paid_calls': 0}))
        return 0
    try:
        version = importlib.metadata.version('openai-codex')
        if version != PINNED_SDK:
            print(json.dumps({'status': 'SDK_VERSION_MISMATCH', 'expected': PINNED_SDK,
                              'observed': version, 'paid_calls': 0}))
            return 2
        result = execute_probe()
        print(json.dumps(result, sort_keys=True))
        return 0 if result['status'] == 'SDK_MODEL_PROBE_PASS' else 2
    except Exception as exc:
        print(json.dumps({'status': 'SDK_MODEL_PROBE_ERROR',
                          'error_type': type(exc).__name__,
                          'model': MODEL, 'projectctl_d1_authorized': False}, sort_keys=True))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
