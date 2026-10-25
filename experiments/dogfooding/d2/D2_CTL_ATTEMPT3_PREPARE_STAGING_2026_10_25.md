# D2 Attempt 3 — staged one-Prepare code (NOT AUTHORIZED)

**Scope:** GitHub-side code preparation and synthetic tests only.
The operator-reported one-time offline Qualification passed syntax,
36 tests and read-only frozen preview at commit
\`c9cafddd1b0973b3e6fbb83ca1caa760928edd38\`.
Its evidence is in \`observations/ctl-attempt3-offline-qualification\`
and MUST NOT be regenerated, edited or deleted.

New separate runner:
\`d2_ctl_attempt3_prepare_once.py\`.
Different from consumed Attempt 1/2 runners. A distinct evidence identity
\`observations/ctl-prepare-attempt-3\` remains **absent** pending a new
express owner approval for one live Prepare. The code requires an exact
reviewed research SHA, clean checkout, pinned D0 environment, intact prior
qualification hashes, zero RunStore entries and unclaimed frozen task.

Candidate future live procedure (NOT APPROVED by this document):
- one first official quota read; Pydantic snapshot schema, project reserves,
  freshness and frozen MEDIUM floors must ALL pass **before** Scheduler;
- one independent fresh Scheduler selection, not forcibly overridden;
- version-only capabilities and direct strategy, final frozen-state recheck;
- at most one durable-intent-bound \`projectctl run prepare\`, no automatic
  retries; after uncertain dispatch require independent reconciliation;
- postflight RunStore/Beads/worktree/Direct immutability confirmation.
- no \`run start\`, worker inference, verification, integration or publication.

## Currently allowed: review + synthetic tests + preview only

After syncing to the **new exact reviewed research SHA** and verifying a
clean research checkout, first run the 15 synthetic tests:

    cd /home/ai/project/My/projectctl-advisory-lab
    "$HOME/.local/share/projectctl-dogfood-d0/venv/bin/python" -B \
      -m unittest -v experiments.dogfooding.d2.test_d2_ctl_attempt3_prepare_once

If green, export isolated D2 vars (same as prior) and run only:

    "$HOME/.local/share/projectctl-dogfood-d0/venv/bin/python" -B \
      -m experiments.dogfooding.d2.d2_ctl_attempt3_prepare_once \
      --preview --expected-head "$PIN"

Preview should return
\`D2_ATTEMPT3_PREPARE_PREVIEW_PASS__NO_CLAIM_NO_INFERENCE\`.
Git/Beads reads may touch caches. Do not use \`--prepare\` or acknowledgements.

**Authority status:** Candidate code presence and a green Preview NEVER
authorize a live Provider/Scheduler/Prepare or a paid Worker. A separate,
explicit owner instruction is required for each privilege transition.


## Operator-reported live Prepare outcome (2026-10-25)

The owner explicitly authorized **one** controlled Attempt-3 Prepare (NO
Worker), manually executed the pinned candidate runner, and supplied this
sanitized result:

- Decision: `D2_CTL_ATTEMPT3_PREPARE_PASS__WORKER_NOT_STARTED`
- Attempt: `3`
- `prepare_dispatched=true`
- `failure_stage=null`; `reason_code=null`
- `worker_started=false`
- Non-null run ID returned (retained in the owner's private D2 evidence,
  not copied to GitHub)

The candidate source returns this PASS only after its postflight verifies the
prepared plan, claimed RunStore state, Beads ownership and isolated worktree,
plus unchanged Direct fixture. These are source-contract semantics and
owner-supplied terminal evidence, not independent direct inspection of the
private machine or a claim that the paid Worker completed.

**Authorization B is consumed.** Do not rerun `--prepare`, delete the
`ctl-prepare-attempt-3` evidence identity, or start another Run.
The live quota/Scheduler observations and Prepare output remain in that
owner-only directory; do not publish raw account/provider payloads.

**Next gate:** read-only independent confirmation of the same prepared
Run's durable `claimed` state, lease absence, no `started_at`, no
`candidate_commit`, and frozen execution/worktree identity. The Worker's
`run start` API acquires execution admission and revalidates account quota,
execution plan, task claim and worktree before its model turn. A successful
Prepare does **not** guarantee Worker-start admission. Paid Worker start,
checkpoint resume, verification and integration require separate permissions;
none is authorized here.

**Status:** `D2_CTL_ATTEMPT3_PREPARED_BY_OPERATOR__WORKER_NOT_STARTED`;
`WAITING_FOR_INDEPENDENT_PREWORKER_REVIEW_AND_OWNER_APPROVAL`.

## Operator-reported one paid CTL Worker turn (2026-10-25)

The operator independently reported that the pre-Worker durable read-only
check passed all 11 checks for the prepared run: expected Run and task,
claimed state, pinned base, no prior start or candidate, lease-free,
existing clean isolated worktree, no worker-result evidence before start.

The owner subsequently approved **one** bounded paid `projectctl run start`
for that exact previously prepared CTL Run. A one-time local wrapper recorded
dispatch intent in a separate evidence directory and invoked exactly one
`run start`. The operator supplied the sanitized outcome:

| Recorded field | Value |
| --- | --- |
| decision | `D2_CTL_WORKER_START_OUTCOME_REQUIRES_REVIEW` |
| dispatch_intent_recorded | true |
| retry_authorized | false |
| exit_code | 0 |
| run_status | `verifying` |
| worker_status | `implemented` |
| checkpoint_present | false |

The unique Run ID remains in the owner's local evidence rather than
public Git history. The exact Worker token counts, model output,
changed-path inventory and elapsed wall time were not provided by the
sanitized message; do not invent them. This is operator-reported terminal
evidence, not direct inspection of the private run artifacts.

**Interpretation:** the paid CTL Worker returned implementation status
and advanced the Run to `verifying`. This does **not** mean independent
tests or policy verification passed. No model rerun, resume, new Prepare,
`run verify`, integration, merge or publication is authorized by this
worker-start outcome.

**Verification contract review:** current ProjectCTL `verify_run` is a
state-changing operation. It acquires a Run lease, resolves trusted
verification policy, inspects permitted scope, runs the frozen independent
commands when allowed, persists verification/evidence manifests, and can
transition the Run to verified/blocked/failed and reconcile the canonical
task. Accordingly, use a separate owner gate for `run verify`, after
read-only worker-artifact/source inspection.

**State:** `D2_CTL_WORKER_IMPLEMENTED__VERIFY_PENDING`;
`ONE_PAID_START_CONSUMED__NO_RETRY`.

## Operator-reported independent Verification PASS (2026-10-25)

The owner explicitly authorized ONE independent `projectctl run verify`
for the previously prepared, one-paid-turn CTL Run. The owner reported
the sanitized terminal result from the single-use verification wrapper:

- `decision=D2_CTL_VERIFICATION_OUTCOME_REQUIRES_REVIEW`
- `dispatch_intent_recorded=true`, `retry_authorized=false`
- `exit_code=0`, `run_status=ready_to_integrate`
- `overall_pass=true`, `verification_check_count=4`
- `policy_violation_count=0`
- Changed paths: exactly `d2events/cli.py`, `d2events/parse.py`,
  `d2events/report.py`.

**Interpretation:** ProjectCTL's independent verification and scope/policy
checks passed. Its implementation groups a frozen unittest invocation
into a single recorded check alongside internal diff-policy,
execution-write-scope, and workspace-stability checks. Thus the number
four is NOT the number of unit tests: separately inspect the bounded
captured verification log for `Ran 26 tests` and `OK`, and validate
the command/check status and its immutable digests before claiming an
explicit 26/26 test result.

The successful code path creates a candidate commit in the isolated
worktree and transitions the durable Run to `ready_to_integrate`.
Neither automatic integration nor merge into `main` occurred as
part of verification. Inspect the candidate hash, parent and current
frozen `main` before any delivery approval.

All direct results and previous Attempt-1/2/3 evidence remain immutable.
The exact CTL paid-worker time, tokens, cache accounting and full source
semantic quality have NOT yet been independently reviewed. CLI 0.163.0
versus CTL SDK 0.160.0/adapter 0.41.0 remains a known comparison
confounder. No `run integrate`, re-verify, retry, merge or publication
is authorized.

**State:** `D2_CTL_INDEPENDENT_VERIFICATION_PASS_BY_OPERATOR__CANDIDATE_REVIEW_PENDING`;
`INTEGRATION_NOT_AUTHORIZED`.

## Verified CTL candidate identity and frozen-test evidence (2026-10-25)

A first independent audit reported all Verification/Evidence/scope/log tests
PASS, including `Ran 26 tests` + `OK` and captured log SHA-256 digests.
It mistakenly reported `same_candidate=false` because the review script
assumed a flat worktree path `ctl-home/worktrees/<run_id>`; ProjectCTL's
actual WorktreeManager uses
`ctl-home/worktrees/<project_instance_id>/<run_id>`.
The owner then ran an amended read-only audit using the durable
RunStore `worktree_path` as the authority.

**Owner-reported outcome:** `D2_CTL_CANDIDATE_IDENTITY_PASS`.
All 11 checks PASS: ready-to-integrate state, verification PASS, RunStore and
Evidence candidate identity, safely rooted Worktree, no active lease,
single-parent Candidate based on frozen policy commit, Worktree HEAD
matching Candidate, clean worktree, exactly three changed paths, and
integration branch `main` still at the frozen policy commit.

- CTL candidate: `fedc609d4d247f38e883fb72d72e6d8c9eb38376`
- Base: `3c69dd42497acadadc5d64e7b4abe5d412b309f5`
- Verification wall: 1.084364 s (profile and policy included)
- Frozen independent tests: 26/26, signed-by-content matched local log digests
- `d2events/cli.py` SHA-256:
  `9335cb9ee2f1068b2524717e7227d1bb11150475004be45802f893764f7e09a7`
- `d2events/parse.py` SHA-256:
  `a148bcf3f469828ac0978791d127896c5625d91ce7d6c0b291912cf00c333a52`
- `d2events/report.py` SHA-256:
  `c4f946c852d374b28a4e26b4ee97edfeaac5f41b005d9c72c64f3cd703c5e9c6`

All three CTL source hashes differ from the preserved Direct source hashes.
Different code does not establish better or worse semantic quality.

**Status:** `D2_CTL_VERIFIED_CANDIDATE_IDENTITY_PASS`; cross-arm timing,
SDK usage accounting and CTL semantic review still pending. This is an
operator-supplied inspection result, not a claim of direct access to the
local candidate or raw private evidence. `run integrate`, Merge, Publish,
rerun and recovery actions are NOT authorized.
