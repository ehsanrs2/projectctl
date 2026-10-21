# D2 CTL Attempt 2 — OFFLINE qualification and fail-closed reliability research

**Scope:** Prepare a non-mutating, operator-executed qualification for a *possible* CTL Prepare Attempt 2. This does **not** create an Attempt-2 folder, acquire a Beads claim, create a ProjectCTL Run, make an App Server quota request, start Codex, alter frozen fixture/task/policy, integrate changes or authorize any subsequent execution.

**Historical checkpoint:** First Direct arm is accepted with static source-review edge-risk annotation and frozen 26-test evidence. CTL Prepare Attempt 1 has `D2_CTL_PREPARE_PRECLAIM_BLOCKED__NO_RETRY`, `run_id=null`, no inner Prepare dispatched and no worker. The operator independently confirmed that the saved Scheduler quota digest equals the canonical synthetic `unknown_quota_snapshot` digest, not the preceding official healthy quota digest.

## Root cause facts vs uncertainty

The `projectctl quota` CLI and `projectctl next` CLI each query quota independently; `next` calls `collect_scheduling_bundle()`, which calls `read_current_quota()` again. By default, `read_current_quota(...,fail_closed=True)` catches `ProviderUnavailableError` / `QuotaError` and returns a synthetic unknown snapshot. `QuotaManager` then marks the snapshot stale/unavailable and applies the frozen conservative unknown mode; Scheduler refuses the medium task with `quota_unknown`.

Digest equality confirms the **fallback snapshot identity**, not the exact transient exception class, App Server RPC method failure or timeout. Do not assert a specific network or rate-limit cause without additional observations.

## Implemented R&D-only components

- `experiments/dogfooding/d2/d2_ctl_attempt2_offline.py`: *only* `--replay-attempt1` and `--preview-attempt2`. No `--prepare`/`--execute` and no CLI paths to `projectctl quota`, `projectctl next`, `projectctl run prepare/start` or Codex App Server. `--replay-attempt1` loads the three retained evidence files (size/symlink bounded), rejects any sign of actual inner-Prepare dispatch, verifies first official high-confidence normal quota and its MEDIUM floor, frozen one-candidate Scheduler rejection with `quota_unknown`, consistent historical timestamps, and re-derives the canonical unknown/official digest identity. Outputs only approved non-secret classification and evidence file SHA-256, not account IDs or raw quota data. No exception messages from provider are surfaced in the classifier.
- `--preview-attempt2` replays the historical evidence and then calls the existing **read-only** D2 CTL readiness audit. It requires zero CTL runs, clean frozen CTL, open/unclaimed Beads Task, frozen policy and Direct HEAD, pinned isolated D0 Python/environment and the non-existence of the new `ctl-prepare-attempt-2` identity. Returns `D2_ATTEMPT2_OFFLINE_PREVIEW_PASS__NO_CLAIM_NO_INFERENCE`. It **does not create or reserve** the suggested future evidence directory on disk.
- `experiments/dogfooding/d2/test_d2_ctl_attempt2_offline.py`: 23 defined synthetic offline unit cases including exact digest match, wrong digests, altered eligibility, marker of inner Prepare dispatch, worker-start flag, nonzero retry count, explicit dispatch flag, observed run ID, protected symlinked/missing evidence, invalid boolean quota ratios, no subprocess calls, provider `fail_closed=True` and `fail_closed=False` behavior, conservative unknown quota classification, safe exception-class-only diagnostics, non-mutating Preview, and refusal of an already-existing Attempt-2 evidence identity.

**Execution status (operator-reported, 2026-10-21):** The owner executed the committed manual launcher on pinned research HEAD `313f96537a4a18ac93f38e837a3032bbbcac5128`. Terminal output reported all four steps, `D2_ATTEMPT2_OFFLINE_CONTRACT_VALIDATED`, and `D2_ATTEMPT2_OFFLINE_QUALIFIED__PREPARE_NOT_AUTHORIZED` at the single-use evidence directory. The 23-test count was enforced by that launcher. This is owner-supplied terminal evidence, not an independent read of the machine's private evidence files. It does **not** authorize Prepare/Claim/Worker.

## Manual offline qualification, synced separately

New committed entrypoint: `experiments/dogfooding/d2/d2_ctl_attempt2_offline_manual.sh`.
It requires an **explicit exact 40-character reviewed HEAD**; the shell script
never runs `git fetch`, `git pull` or any provider quota probe. Synchronize
the checkout *separately*, before entering the offline qualification gate.
Retrieve the exact approved HEAD from the reviewer/operator, not from unreviewed
remote state. Run this command manually from the pinned research checkout:

```bash
cd /home/ai/project/My/projectctl-advisory-lab
export D2_REVIEWED_SHA='paste-the-separately-reviewed-40-character-SHA-here'
bash experiments/dogfooding/d2/d2_ctl_attempt2_offline_manual.sh \
  --expected-head "$D2_REVIEWED_SHA"
```

Set `D2_REVIEWED_SHA` to the exact Git commit SHA provided in the review report (the placeholder above is deliberately invalid and will fail closed). The launcher checks branch, clean HEAD, pinned D0 Python and environment,
single-use evidence path availability, and frozen input-file presence. It
writes logs, input SHA-256 values, synthetic test output, historical replay,
readiness preview, integrity verification and final file manifest only to
`$HOME/.local/state/projectctl-dogfood-d2/observations/ctl-attempt2-offline-qualification`
(mode 0700, single-use). It does not create
`observations/ctl-prepare-attempt-2`.

Expected (not yet observed on operator machine): `Ran 23 tests`, `OK`,
`D2_ATTEMPT1_FALLBACK_REPLAY_PASS__NO_PROVIDER_CALLS`,
`D2_ATTEMPT2_OFFLINE_PREVIEW_PASS__NO_CLAIM_NO_INFERENCE`,
and `D2_ATTEMPT2_OFFLINE_QUALIFIED__PREPARE_NOT_AUTHORIZED`
with exit 0. A nonzero exit requires preservation and inspection, not rerun
under the same evidence identity. The launcher checks retained evidence SHA-256
even if a later gate fails (when the manifest was created). No tests run by
GitHub commit alone constitute local qualification.

## Later-stage protocol, NOT YET AUTHORIZED OR EXECUTED

At a separate owner approval after offline qualification, prepare a new Attempt-2 manual runner with *new immutable evidence directory*, current reliable canonical Codex quota, a newly obtained Scheduler decision that demonstrably selects `d2ctl-g4q`, frozen `gpt-6-luna`/medium + direct strategy, exact same write scope, **one** permitted claim/prepare dispatch, no model/integration/worker. Do not substitute a healthy first quota response for an unknown scheduler response; no threshold weakening or forced candidate selection. On another fail-closed quota unknown, record the distinct new attempt as blocked, not silently retry. Classify provider errors in sanitized local R&D only, never publish raw errors/credentials. Evaluate the scientific cost of any extra quota probes and version/interface confounding.

All existing historical evidence and both fixture worktrees remain untouched.

**State:** `D2_ATTEMPT2_R_AND_D_OFFLINE_QUALIFIED_BY_OPERATOR / 23_SYNTHETIC_TESTS_OPERATOR_REPORTED_PASS / ATTEMPT2_PREPARE_NOT_AUTHORIZED / CTL_PAID_START_NOT_AUTHORIZED`. The separate Attempt-2 guarded Prepare code and its tests are tracked in `D2_CTL_ATTEMPT2_PREPARE_RUNBOOK_2026_10_21.md`.
