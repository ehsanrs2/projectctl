# D0 next gate — pinned Codex SDK model compatibility probe

**Status:** Prepared only. No model call or ProjectCTL worker run performed by this commit. D1 remains **NO-GO** until other gates close.

## Evidence leading to this gate

Operator confirmed 13/13 offline unit tests and `DISPOSABLE_SMOKE_PASS` for Beads 1.3.1, in a temporary no-remote Git repository. It covered the ProjectCTL Beads adapter's single-actor create/list/show/claim/release/block/close path and native Beads heartbeat/atomic unclaim. Provider lease renewal in the **ProjectCTL adapter remains absent**, and adapter release is not atomic; concurrency/expiry safety is not established.

The ProjectCTL source pins `openai-codex==0.160.0`; the separate direct Codex CLI is 0.163.0. The SDK adapter creates `Codex`, `CodexConfig`, `thread_start` with configured model/reasoning/sandbox, then `thread.run` with structured output.

## Single opt-in model probe

`sdk_model_probe.py` uses that same high-level SDK surface with:
- one `gpt-6-luna` turn, `medium` reasoning;
- `Sandbox.read_only`, deny-all approvals, disabled tool network, a fresh OS temporary directory for cwd;
- a closed one-field structured output schema and a single fixed, non-sensitive instruction;
- ephemeral thread, no ProjectCTL run/task, no Beads calls, no user project files;
- no credentials are printed; the SDK inherits the operator's existing authenticated environment;
- requires **both** `--execute` and `--ack-paid` for a live call. It may consume account quota, even if no separate invoice is generated.

This checks *SDK model acceptance plus a minimal structured turn*, not a full direct ProjectCTL worker execution, durable resume, or independent verification. It is not OS-level filesystem isolation and does not guarantee upstream account policy will permit the model.

## Manual operator steps

Run from the existing research worktree root after the new commit is pulled:

```bash
git status --short
git pull --ff-only origin research/advisory-skills-eval

D0_VENV="$HOME/.local/share/projectctl-dogfood-d0/venv"
export PATH="$D0_VENV/bin:$PATH"
"$D0_VENV/bin/python" -m compileall -q experiments/dogfooding
"$D0_VENV/bin/python" -m unittest -v experiments/dogfooding/test_d0_tools.py experiments/dogfooding/test_beads_adapter_smoke.py experiments/dogfooding/test_sdk_model_probe.py

# No model calls:
"$D0_VENV/bin/python" experiments/dogfooding/sdk_model_probe.py

# Explicit, single real model turn; run only if quota/consent is acceptable:
"$D0_VENV/bin/python" experiments/dogfooding/sdk_model_probe.py --execute --ack-paid
```

Expected: `SDK_MODEL_PROBE_PASS` with a completed turn and valid JSON. A failure reports only status and exception *type*; stop, do not auto-retry, do not switch model/sandbox silently.

## Follow-up decision

A pass closes `SDK_MODEL_RUNTIME_UNVERIFIED` for the **one-turn SDK surface**, but D1 remains blocked on controlled task ownership/lease assumptions, approved isolated state + fixture setup, scoped verification/quota config, and single-actor no-concurrent-reclaimer conditions. A fail creates a focused SDK compatibility issue to investigate offline (authentication, SDK version, model name, structured-output contract) before any new paid call. No modifications to ProjectCTL runtime/M6.0 are authorized.
