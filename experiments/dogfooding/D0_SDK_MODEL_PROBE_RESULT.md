# D0 SDK compatibility result — operator-confirmed

**Date:** 2026-10-18. **Outcome:** `SDK_MODEL_PROBE_PASS`. **D1 worker:** NOT RUN. **Research-only**.

## Supplied evidence

- The operator pulled `dc65e2f` from `research/advisory-skills-eval`.
- Python compilation succeeded; all **16/16** D0 tool tests passed (11 original/preflight/fixture, 2 Beads smoke guard, 3 SDK model probe guard).
- Explicit operator invocation: `python experiments/dogfooding/sdk_model_probe.py --execute --ack-paid`.
- Returned fields: `status=SDK_MODEL_PROBE_PASS`, `turn_status=completed`, `structured_response_valid=true`, `model=gpt-6-luna`, `reasoning=medium`, `sandbox=read_only`, `projectctl_d1_authorized=false`.
- The script requires the pinned `openai-codex==0.160.0`; this confirms a minimal authenticated high-level Python SDK turn with structured output.
- The SDK probe used an isolated temporary working directory, `deny_all` approval, and no ProjectCTL task/Beads lifecycle; no worker patch, verification, integration, or durable SDK resume occurred.
- Earlier real Beads 1.3.1 disposable smoke separately qualified create/list/show/claim/release/block/close under one actor with **13/13** test success. Provider lease renewal and atomic release were **not** implemented in the ProjectCTL adapter.

## Gate disposition

| Gate | After this evidence |
| --- | --- |
| D0 runner/fixture unit tests | PASS (16/16) |
| Environment/projectctl/SDK packages | PASS for observed versions |
| Beads 1.3.1 basic single-owner CLI adapter | PASS (disposable smoke) |
| SDK `gpt-6-luna` minimal read-only structured turn | PASS |
| SDK workspace-write worker/task implementation | NOT TESTED; the point of D1 |
| Beads lease expiration and concurrent release | NOT QUALIFIED; restrict D1 to one actor, no concurrent reclaimer, inspect ownership at each transition |
| Isolated fixture/ProjectCTL state and verified scope/quota | NOT YET CONFIGURED |
| D1 paired execution | NOT STARTED |

The previous `SDK_MODEL_RUNTIME_UNVERIFIED` blocker is now **closed only for this minimal SDK turn**, not treated as proof of full ProjectCTL worker compatibility.

**Next:** prepare the two external remote-free D1 fixture baselines, freeze SHA/spec/protected-file hashes, then review the disposable ProjectCTL initialization/Beads ownership, scope and quota settings prior to the first paid worker run. No further standalone model probe is needed. Do not modify product/runtime code or active M6.0 files.
