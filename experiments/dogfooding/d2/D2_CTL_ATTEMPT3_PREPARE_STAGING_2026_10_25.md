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
