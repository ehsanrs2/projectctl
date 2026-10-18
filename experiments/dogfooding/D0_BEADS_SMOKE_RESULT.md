# D0 Beads adapter smoke — operator evidence (2026-10-18)

**Result:** `DISPOSABLE_SMOKE_PASS`. This establishes **basic single-owner CLI/adapter contract compatibility only**; it is not a D1 authorization or full concurrency/lease qualification.

## Execution evidence supplied by operator

- Branch pull: `a9662f1..fe8a0ba` fast-forward, no runtime/production edits.
- Python unittest: **13/13 passed** (11 D0 preflight/fixture tests + 2 smoke entrypoint guards).
- `experiments/dogfooding/beads_adapter_smoke.py --execute --ack-temporary-repo` returned `status=DISPOSABLE_SMOKE_PASS`.
- Real smoke checks reported, in order: `isolated_local_git`, `beads_version_1_3_1`, `beads_init`, `adapter_create_json`, `adapter_read_ready_show_dep`, `adapter_claim_and_ownership`, `provider_heartbeat_available`, `adapter_release_single_actor_only`, `provider_atomic_unclaim`, `adapter_status_block`, `adapter_close`, `no_git_remote`.
- Output flags: `model_calls=0`, `real_project_mutations=0`, `adapter_release_atomic=false`, `provider_lease_renewal_in_adapter=false`, `d1_authorized=false`.
- Smoke used a newly created temporary Git repo with no remotes and isolated temporary Beads/Dolt state; operator did not run an LLM worker or D1.

## Scope of the pass

The installed `bd 1.3.1` and current ProjectCTL Beads adapter agree sufficiently on create/list/show/ready/claim/release/status/close and expected JSON for **one temporary task and one actor**. The provider's independent `heartbeat` and guarded `unclaim` commands also work there.

This does **not** establish that ProjectCTL renews Beads leases, that its two-step release is race-safe, or that completion/blocked status transitions behave correctly during conflicting claims/reclaimed leases. Do not infer those from a successful smoke.

## Remaining gates

1. **SDK model**: a separately initiated one-turn, read-only, tiny `openai-codex==0.160.0` probe using `gpt-6-luna` must confirm actual availability under the user's existing authorization and model/account entitlement. CLI 0.163.0 success is not equivalent evidence.
2. **Lease/ownership**: document bounded single-actor/no-concurrent-reclaimer scope for first D1; explicitly fail closed on owner mismatch and expiry. Broader production readiness still needs an atomic release/heartbeat design and tests, under a separate implementation decision.
3. **D1 setup**: new remote-free fixture repos outside ProjectCTL, isolated PROJECTCTL_HOME, one canonical Beads task, matching model/reasoning/sandbox, independent verification policy and quota/stop conditions. Do not start any worker without these conditions.

**Decision:** `D0_BEADS_SINGLE_ACTOR_CONTRACT_QUALIFIED`; `D1_NO_GO`. No ProjectCTL root/runtime code, architecture, or M6.0 changes.
