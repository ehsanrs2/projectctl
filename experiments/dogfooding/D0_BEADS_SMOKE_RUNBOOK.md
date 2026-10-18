# D0 Beads 1.3.1 disposable adapter smoke

**State:** Prepared, not yet executed against the operator's installed Beads 1.3.1. D1 remains **NO-GO**.

The operator reported (2026-10-18) 11/11 D0 tool tests passing, no environment blockers, `environment_status=READY_FOR_RUNTIME_PROBE`, and `status=D1_NO_GO`. Provided help output for Beads 1.3.1 confirms `create --json`, `update --claim`, `assign`, `close --reason`, `unclaim --if-assignee`, `heartbeat`, and an embedded-Dolt `init` surface. Static CLI help does **not** prove adapter compatibility.

## Single manual provider smoke

From the **research** worktree root:

```bash
git pull --ff-only origin research/advisory-skills-eval

D0_VENV="$HOME/.local/share/projectctl-dogfood-d0/venv"
export PATH="$D0_VENV/bin:$PATH"

"$D0_VENV/bin/python" -m compileall -q experiments/dogfooding
"$D0_VENV/bin/python" -m unittest -v experiments/dogfooding/test_d0_tools.py experiments/dogfooding/test_beads_adapter_smoke.py

"$D0_VENV/bin/python" experiments/dogfooding/beads_adapter_smoke.py \
  --execute --ack-temporary-repo
```

The last command is a **real local Beads storage mutation** inside a newly created and exclusively owned OS temporary directory. It initializes a new no-remote Git repository, changes only that repository's Beads issues, and removes its exclusively created temp directory on exit. It does **not** invoke Codex inference, ProjectCTL worker/prepare/integrate, existing Beads workspaces, D1, or any Git push. It overrides `HOME`, XDG paths and Beads/Dolt routing variables in its own process; opts out of telemetry; uses `--skip-agents`, `--skip-hooks`, and local-only Git. This is application-level isolation, **not a formal guarantee of zero external network access**; stronger isolation requires OS/VM network controls.

It exercises the actual installed `projectctl.integrations.beads.client.BeadsClient` (editable source package) to create, list, inspect, claim, legacy release, re-claim, block and close. Separately exercises provider heartbeat and atomic `unclaim --if-assignee`. It pins expected `bd version 1.3.1`. Stop and review a failure rather than automatically changing Beads or ProjectCTL versions.

Expected: JSON `{"status":"DISPOSABLE_SMOKE_PASS",...}` and `model_calls=0`. On failure: `DISPOSABLE_SMOKE_FAILED` with only the failing step and exception **type**; raw Beads output and private filesystem paths are intentionally not published. Report the JSON and command exit code for review.

## Architectural caveat: ownership and lease

Even a pass does **not** prove the existing ProjectCTL adapter is safe under concurrent claims or five-minute lease expiry. The adapter uses a non-atomic `bd assign ID ""` then `bd update ID --status open` for release; Beads 1.3.1 offers atomic `bd unclaim ID --if-assignee ACTOR`. The ProjectCTL adapter also does not heartbeat the provider's lease; its own control-plane lease is not equivalent. Keep real D1 disabled until these are handled by a bounded compatibility decision and tests.

## Remaining D1 gates

- Confirm whether pinned `openai-codex 0.160.0` can actually run `gpt-6-luna` with intended reasoning/sandbox; Codex CLI 0.163.0 success is insufficient.
- Freeze fresh external fixture roots, independent acceptance, state isolation, canonical local Beads task readiness, scope and verification policies and quota.
- Complete this provider smoke; qualify any failures. No source/runtime/architecture changes are implied.
