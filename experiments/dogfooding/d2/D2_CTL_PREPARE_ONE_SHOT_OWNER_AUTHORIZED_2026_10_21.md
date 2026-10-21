# D2 CTL — owner authorization for exactly ONE local Prepare (2026-10-21)

**Owner approved:** ONE `projectctl run prepare` for the frozen task `d2ctl-g4q` in the isolated CTL fixture, solely to acquire the Beads claim, allocate a RunStore record, persist plan/strategy/capabilities/claim manifests, and create the isolated CTL worktree. **NOT approved:** `projectctl run start`, paid model inference, retries/hotfixes, autonomous execution, verification, candidate commits, integration, Beads closure or remote publication.

## Evidence before this decision

- The operator executed the post-Direct read-only CTL readiness checks from research HEAD `01f747975326e993352c139a9bb0373bbf35be70`: all **13/13 tests PASS** and `D2_CTL_READ_ONLY_PREPARE_GATE_PASS__CLAIM_NOT_AUTHORIZED`, exit `0`.
- The sole canonical D2 Task is `open_unclaimed`; CTL RunStore contains zero runs; CTL target worktree is clean.
- Direct successfully completed exactly one Codex CLI turn (32.809408731 seconds) and **26/26** frozen tests, with three source file SHA-256 values recorded in `d2_ctl_readiness.py`. This Direct candidate and its raw local evidence must not be modified/copied into CTL.
- CTL frozen policy HEAD is `3c69dd42497acadadc5d64e7b4abe5d412b309f5`; direct base is `32836ea5633230e50fb9d907dcdba83e357bcfc6`. Frozen strategy: direct; model `gpt-6-luna`; medium reasoning; `workspace_write`; `deny_all`; network disabled; local-only code delivery. CTL uses openai-codex SDK `0.160.0` and adapter `0.41.0`, different from Direct CLI `0.163.0`.

## Qualified manual Prepare package (operator execution pending)

The research-only `experiments/dogfooding/d2/d2_ctl_prepare_once.py` supports:

- `--preview`: re-audits the **completed** Direct evidence plus unchanged frozen CTL state, ensures the first Prepare evidence directory is absent, and pins the actual CTL branch at the approved Git policy commit; no quota query or claim.
- `--prepare --ack-claim`: creates a private mode-0700 evidence directory **once**, records the frozen Preview, requests **fresh high-confidence official** canonical Codex quota and the scheduler's sole eligible `d2ctl-g4q` task, checks the admission guard (including minimum MEDIUM remaining limits and a quota sample less than 120 seconds old), probes version-only SDK capabilities and direct strategy without inference, and repeats source readiness before dispatch. The sampled official quota's freshness is revalidated just before dispatch.
- Calls the exact supported `projectctl run prepare --strategy direct --target <frozen ctl branch> --project <isolated ctl fixture> --json` **once**; no internal retry. The actual `--target` is read from the already frozen ctl branch rather than guessed.
- Captures UTC/monotonic wall timing and CLI stdout/stderr, `plan`, `run`, `worktree`, RunStore state, Beads task after Claim, required frozen model/perms, worktree and Git HEAD, and checks that the Direct file-status snapshot is unchanged. Durable artifacts remain local under `$HOME/.local/state/projectctl-dogfood-d2/observations/ctl-prepare-attempt-1`; they are not committed/published.
- If the quota/capability or readiness gate fails before dispatch, it records `D2_CTL_PREPARE_PRECLAIM_BLOCKED__NO_RETRY` and stops. If an actual prepare command failed or post-Claim reconciliation diverged, it records `D2_CTL_PREPARE_DISPATCHED_NEEDS_RECONCILIATION__NO_RETRY` and **must not be run again**; inspect the partially-mutated Beads/RunStore/Worktree state in a separately approved recovery review. One success must report `D2_CTL_PREPARE_PASS__PAID_WORKER_NOT_STARTED`.

The research-only `test_d2_ctl_prepare_once.py` defines **15** synthetic offline cases (positive frozen plan, negative model/policy/task/target, approved acknowledgement, evidence no-reuse, preview/no-claim, pre-dispatch quota failure). This suite is **not yet observed on the user's pinned venv**. It contains only local synthetic temporary directories and mocks; it does not start ProjectCTL prepare in testing.

### Single authorized user action (do not retry automatically)

Run from a **child Bash**, which scopes `set -euo pipefail` without changing the interactive shell:

```bash
bash -c '
set -euo pipefail
cd /home/ai/project/My/projectctl-advisory-lab
git pull --ff-only origin research/advisory-skills-eval
# ALSO CHECK THE EXACT APPROVED RESEARCH HEAD SHOWN IN THE ASSISTANT RESPONSE.
VENV="$HOME/.local/share/projectctl-dogfood-d0/venv"
export PATH="$VENV/bin:$PATH"
export PROJECTCTL_HOME="$HOME/.local/state/projectctl-dogfood-d2/ctl-home"
export BD_ACTOR=d2-dogfood-owner
export BD_DISABLE_METRICS=1
export DOLT_DISABLE_EVENT_FLUSH=1
export DO_NOT_TRACK=1
export PYTHONDONTWRITEBYTECODE=1
"$VENV/bin/python" -B -m unittest -v experiments.dogfooding.d2.test_d2_ctl_prepare_once
"$VENV/bin/python" -B -m experiments.dogfooding.d2.d2_ctl_prepare_once --preview
"$VENV/bin/python" -B -m experiments.dogfooding.d2.d2_ctl_prepare_once --prepare --ack-claim
'
echo "D2_CTL_PREPARE_COMMAND_EXIT=$?"
```

Expected pre-mutation: `Ran 15 tests; OK`, `D2_CTL_PREPARE_PREVIEW_PASS__NO_CLAIM_NO_INFERENCE`. Expected after one authorized Prepare: `D2_CTL_PREPARE_PASS__PAID_WORKER_NOT_STARTED` and a new `run-...` ID. These are **expected, not observed**. If tests/Preview fail, do not prepare. If the evidence path already exists, do not reset it or repeat the attempt. Collect the local `prepare-summary.json` only (avoid uploading raw context/logs).

**Post-Prepare gate:** separate human assessment of run ID, claim, isolated worktree, frozen policy and availability. A separate affirmative owner decision is required before any paid ProjectCTL `run start`. No verify/integrate at this stage.

**State:** `D2_CTL_PREPARE_OWNER_APPROVED_ONCE / OFFLINE_PREPARE_HARNESS_TESTS_PENDING / CTL_PAID_START_NOT_AUTHORIZED`.
