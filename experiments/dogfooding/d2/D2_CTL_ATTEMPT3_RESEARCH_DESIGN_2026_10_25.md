# D2 CTL Attempt 3 — independent admission reliability research design

**Date:** 2026-10-25  
**Scope:** isolated D2 research, not a ProjectCTL product/architecture change  
**Status:** DESIGN_REVIEW_READY — OFFLINE_ONLY — NO_ATTEMPT3_EXECUTION_AUTHORIZATION  
**Owner decision:** approved drafting a separate Attempt-3 design; **did not** approve implementing or dispatching a new Prepare, contacting the live quota provider, claiming a task, starting a Worker, or publishing any artifacts.

## 1. Research question and boundaries

Can the frozen ProjectCTL-governed D2 arm complete a **single** valid local
\`run prepare\` (without inference) under normal, fresh, independently observed
quota admission, without altering any frozen task, model, scope, or prior
evidence? If so, a **separately authorized** later worker experiment could
complete the paired comparison with the already-completed Direct arm.

This is a *third distinct opportunity*, not retrying Attempt 1 or Attempt 2.
No retry or resampling loop is authorized. A pre-dispatch stop consumes the
distinct attempt identity and is a valid negative experimental observation.

This study is intentionally **not** an attempt to lower MEDIUM resource
requirements, force task selection, manually override quota, or bypass the
canonical scheduler. It is also **not** a mandate to change production quota
orchestration. If a more reliable single-snapshot provider/scheduler
interface is desired, evaluate it in a *separate* research track because it
could change the experimental control-plane interface and require an ADR.

## 2. Evidence baseline: two different pre-dispatch exclusions

| Evidence | Attempt 1 | Attempt 2 |
| --- | --- | --- |
| Identifier | \`ctl-prepare-attempt-1\` | \`ctl-prepare-attempt-2\` |
| Observed decision | \`D2_CTL_PREPARE_PRECLAIM_BLOCKED__NO_RETRY\` | \`D2_CTL_ATTEMPT2_PRECLAIM_BLOCKED__NO_RETRY\` |
| Saved rejection reason | Scheduler \`quota_unknown\` | Candidate \`quota_insufficient\` |
| Quota/Scheduler distinction | First quota normal/high confidence; Scheduler digest matched canonical synthetic unknown | First quota \`conservation\`; Scheduler \`conservation\`; independent digest different/unclassified |
| Five-hour MEDIUM check (first quota) | passed | failed |
| Weekly MEDIUM check (first quota) | passed | passed |
| Prepare dispatched / Run ID / Worker | no / null / no | no / null / no |
| Cause limits | Cannot determine precise suppressed Provider exception | Cannot assert a Provider outage or a specific Scheduler snapshot value from sanitized output |

Attempt-2 postmortem was verified **on the operator's machine**, with
\`SYNTAX_PASS\`, 10/10 synthetic tests and
\`D2_CTL_ATTEMPT2_ADMISSION_FORENSICS_COMPLETE__READ_ONLY\`.
Saved quota sample age at *attempt finish* was approximately 4.39 seconds:
this is **not** exact age at admission. The failed
\`first_quota_official_normal\` predicate combines several checks; because
\`mode=conservation\`, that predicate alone does not prove non-official
provenance or Provider failure. The initial five-hour-floor predicate being
false does not independently reveal the numeric ratio.

**Important code distinction:** \`scheduler/eligibility.py\` emits
\`quota_unknown\` when Scheduler's quota state has unavailable five-hour or
weekly effective ratios, or is stale. It emits \`quota_insufficient\` when
these unknown-state conditions are absent and quota eligibility still fails.
Thus the two recorded exclusion *classes* differ, but neither proves a
particular underlying transport/RPC cause or the full independent Scheduler
snapshot contents.

The completed Direct arm remains a fixed reference: Codex CLI 0.163.0,
\`gpt-6-luna\`/medium, one paid turn, 32.81 s, 26/26 tests, three exact-path
changes; source hashes and original evidence are immutable. The CTL arm has
not run any Worker. There is **no** valid CTL quality/latency/token comparison
yet. CLI 0.163.0 and CTL SDK 0.160.0 + adapter 0.41.0 are a predeclared
interface confounder: do not silently change version pins.

## 3. Frozen experiment identity

| Control | Frozen value or required rule |
| --- | --- |
| Research branch | \`research/advisory-skills-eval\` |
| Research checkout | \`/home/ai/project/My/projectctl-advisory-lab\` |
| CTL/D2 root | \`$HOME/.local/state/projectctl-dogfood-d2\` |
| Isolated Python | \`$HOME/.local/share/projectctl-dogfood-d0/venv/bin/python\` |
| CTL fixture | \`$D2_ROOT/fixtures/ctl\`; HEAD \`3c69dd42497acadadc5d64e7b4abe5d412b309f5\` |
| Direct fixture | \`$D2_ROOT/fixtures/direct\`; HEAD \`32836ea5633230e50fb9d907dcdba83e357bcfc6\` |
| Canonical task | \`d2ctl-g4q\`, Beads actor \`d2-dogfood-owner\` |
| Model | \`gpt-6-luna\`, reasoning \`medium\` |
| Execution plan | \`direct\` strategy, workspace-write, deny-all, no network, no Worker during Prepare |
| Scope | exactly \`d2events/parse.py\`, \`d2events/report.py\`, \`d2events/cli.py\` |
| Verification | frozen independent 26-test profile; do not run as part of Prepare |
| Integration | local-only; no commits, merges, remote publication or task completion |
| MEDIUM effective ratios | five-hour >= 0.18; weekly >= 0.08; keep reserves and all project quota policy intact |
| History | Direct, both CTL attempts, offline qualifications and operator postmortem: read-only, no overwrite |
| Execution identity | **future** \`observations/ctl-prepare-attempt-3\` (must remain absent during design/offline qualification) |

Do not modify the protected \`fixtures/ctl\` and \`fixtures/direct\`, the
Beads task, policy catalogs, version pins, thresholds, model profiles,
specification, source baseline, or production \`projectctl/\` implementation.
Research code would be additive under \`experiments/dogfooding/d2/\` only.

A research checkout Git SHA MUST be reviewed/pinned *after* any future
source implementation commit. The SHA of this design document is not
automatically a live execution authorization.

## 4. Proposed three distinct authorization gates

**Approval A — design and offline qualification (current):** review this
document, design a distinct checker, synthetic unit tests and offline
preview; read previously retained evidence, source and fixture state.
No quota provider request, Scheduler resampling, Claim/Prepare/Worker,
RunStore mutation, changes to CTL or Direct. Read-only Git/Beads probes can
update operational caches. No Attempt-3 live identity creation.

**Approval B — later live *one* Attempt-3 Prepare:** requires a **new,
specific owner approval** after code review and successful offline tests.
The approved operator invocation must be explicit, HEAD-pinned, and
one-shot. This approval would permit exactly one bounded official quota
observation, optionally one independent Scheduler observation if first
quota passes, and at most one local \`run prepare\` dispatch. Any failure
stops permanently for Attempt 3. No model invocation is included.

**Approval C — later paid CTL Worker:** is separate from B and is **not**
requested, granted or implied by this document or by a successful Prepare.

There must never be a broad approval phrased as "finish D2"; each
privilege transition needs independent evidence and owner acknowledgement.

## 5. Candidate Attempt-3 operator state machine (future, unimplemented)

| Stage | Permitted operation | GO guard | On failure |
| --- | --- | --- | --- |
| D0: offline source/evidence gate | Read frozen Git/Beads/RunStore, historical hashes, local metadata | 0 CTL runs; sole open/unclaimed task; CTL/Direct/policy hashes fixed; precise research SHA; prior attempts untouched; future Attempt-3 path absent | STOP / OFFLINE_NO_GO; no live quota |
| D1: authorized identity allocation | One new exclusive \`0700\` directory for Attempt 3; record approval metadata + D0 evidence manifest | Explicit Approval B bound to SHA and one new identity; \`mkdir\` without reuse | STOP; identity consumed if created |
| D2: first quota sample | **One** fresh official \`projectctl quota\` sample in isolated D2 environment | valid \`codex_app_server\`, \`codex\` limit, ordinary usage true, confidence high and official for both windows, non-stale \`normal\`, age <=120 seconds, both MEDIUM floors | STOP with exact saved stage and sanitized reason. **Do not call Scheduler** if this gate fails |
| D3: independent Scheduler sample | **One** \`projectctl next\` command; it performs its own quota fetch | normal mode, exact single ready \`d2ctl-g4q\` selected/eligible, no exclusion reasons, balanced/medium, nonempty quota digest not equal to canonical unknown | STOP; never substitute the previous quota or override selection |
| D4: capability/plan/readiness | version-only capability and direct strategy checks; re-check D0 frozen state | pinned SDK/adapter, no fallback, frozen sandbox/policy; no CTL run/claim yet; valid first quota still fresh at dispatch; Scheduler decision timely | STOP, no Prepare |
| D5: dispatch intent | Persist unique one-dispatch intent marker and hashes before subprocess | no earlier intent marker in this identity | STOP if ambiguous; no automatic retry |
| D6: single Prepare | exactly one \`projectctl run prepare\`; timeout bounded | valid command and frozen integration target; **no \`run start\`** | DISPATCHED_NEEDS_RECONCILIATION; never retry |
| D7: verification | inspect returned plan, RunStore, claimed Beads task, isolated worktree, original Direct state | one claimed run, matching base/model/policy/task; no worker-started marker or candidate commit | stop and retain evidence; no inference |
| D8: closeout | sanitized summary + file SHA-256 manifest, operator review | unambiguous stage/dispatch count and immutable artifacts | no Worker until Approval C |

**Key efficiency improvement without weakening admission:** D2 validates the
first quota *before* asking for another independent Scheduler sample. If
first quota already fails (as in Attempt 2), the runner records a genuine
pre-dispatch block with fewer quota/provider calls. This optimizes checking,
**not** the eligibility threshold. Because D2 uses an independent
Scheduler sample, D3 can still disagree with a healthy D2; the runner must
then stop. No automatic waiting, backoff polling, rate-limit guessing,
manual snapshots or implicit retry is approved.

Strict time/read-contract requirements for future implementation:
- Reject missing/boolean/nonfinite effective ratios; preserve frozen
  reserves and policy thresholds. Validate the real Pydantic snapshot
  rather than trusting JSON field names alone.
- Validate the Scheduler's evaluated timestamp within an explicitly
  frozen short age window (proposal: <=120 seconds) and bound it to the
  same target/task/config without fabricating Scheduler provider
  provenance. \`projectctl next\` presently records a quota digest, not
  necessarily the raw independent provider response.
- Do not claim that the Scheduler snapshot equals the first quota:
  two independent reads legitimately have different \`observed_at\`.
  Compare against the canonical synthetic unknown **only** as a
  fail-closed exclusion; any indistinguishable/missing provenance is
  not upgraded into an "official" observation.
- An unexpected exception/timeout *after* dispatch intent is ambiguous.
  Only human forensic reconciliation may inspect state and decide
  whether a genuinely different future experiment can be proposed.
- Raw quota JSON and provider error details remain in private \`0700\`
  local evidence, never in GitHub or public console output. Public
  classifications: \`quota_unknown\`, \`quota_insufficient\`,
  \`quota_not_official\`, \`quota_stale\`, \`scheduler_rejected\`,
  \`frozen_state_drift\`, \`ambiguous_post_dispatch\`.

## 6. Acceptance matrix for an *offline* implementation review

Future source must pass deterministic unit tests before any Approval B:

1. Refuse existing/missing/symlinked evidence and reuse of any past attempt.
2. Refuse wrong research SHA, dirty source, wrong pinned environment,
   altered fixture HEAD/hash or unexpected CTL runs/Beads claim.
3. Bind retained Attempt-1 files to its existing offline SHA evidence;
   independently inventory/hash retained Attempt-2 JSON into a new
   review-only baseline (do not assume Attempt 2 already has a complete
   historical SHA manifest), without editing historical directories;
   preserve the accepted Direct candidate and 26-test evidence.
4. Refuse unknown, stale, non-official, zero/insufficient, boolean,
   nonfinite, too-old and non-MEDIUM first quota; no Scheduler fetch then.
5. Refuse Scheduler unknown/conservation, no task selection, unrelated task,
   extra candidates, unexpected reason, model drift, stale decision, missing
   digest, synthetic unknown digest.
6. Model the legal case where first quota is normal but second independent
   Scheduler sample returns \`quota_unknown\`; guarantee zero Prepare.
7. Model first-quota normal/second-Scheduler insufficient; guarantee zero Prepare.
8. Model full GO with mocks only: exactly **one** prepare subprocess, no model
   worker, exact task/model/strategy/perms/worktree, correct new evidence.
9. Model Prepare timeout, nonzero exit, malformed output, postflight mismatch
   and abrupt dispatch ambiguity: one dispatch maximum, permanent NO_RETRY.
10. Ensure no privileged commands or Provider calls occur in offline preview;
    test event/evidence redaction and checksum guards.

Qualification needs Python parse/compile, test count and results,
test-only mock command accounting, manual operator read-only preview,
file integrity checks, then a reviewable report with exact research SHA.
A mock success never counts as a completed CTL run or actual quota availability.
Never patch tests or quota policy just to make an operator gate pass.

## 7. Independent evidence and scientific interpretation

If later approved and executed, each Attempt-3 stage should retain:
operator approval fingerprint/reviewed research SHA; immutable manifest of
frozen task/spec/policy/direct and independently established prior-attempt
source hashes; exact
single-use evidence path; sanitized commands and wall times; raw quota and
Scheduler JSON in owner-only evidence; normalized checks and sample
timestamps; canonical snapshot/digest classifications; pre-dispatch
decision, dispatch intent and dispatch count; post-dispatch RunStore/task
state; worker-started=false and full file SHA-256 manifest.

Do not include account ID, auth token, provider trace messages, raw quota
payload, or local private paths that leak unrelated information in a
public Git commit. Keep historical operator evidence local and hash-bound.

If D2/D3 rejects the task again, report \`NO_GO_ADMISSION\` and stop;
this is still a legitimate censored outcome, not reason to resample.
If Prepare succeeds, report \`PREPARED__WORKER_NOT_AUTHORIZED\`.
Only a later independent Approval C can authorize the one CTL paid
worker comparison, followed by separate independent verification
and a predeclared assessment of quality, time, cost and interface
confounders. Neither Prepare alone nor synthetic tests establish parity.

## 8. Open decisions before coding Attempt 3

- Confirm future implementation maintains *existing* ProjectCTL quota
  and Scheduler public interfaces. Any snapshot coalescing proposal is
  out of scope for the frozen D2 comparison.
- Decide whether the stricter <=120 s Scheduler age gate is acceptable;
  it can reject an otherwise allowed invocation but cannot make an
  ineligible task eligible.
- Confirm the source evidence manifest format, operator command and
  independent reviewer for the future one-shot script.
- Confirm scheduling **only when** quota naturally meets the unchanged
  thresholds, not by lowering policy or polling repeatedly. A new attempt
  should be launched only with an independently reviewed opportunity.

**Current decision:** \`D2_ATTEMPT3_DESIGN_REVIEW_READY__OFFLINE_ONLY\`.  
**Not authorized:** live quota query, Scheduler resample, \`run prepare\`,
Task claim, Worktree creation, paid Worker, retries, integration or publication.  
**Next permission sought (later):** implement/review synthetic offline
qualification code, **not** dispatch Attempt 3.

## 9. Offline implementation checkpoint (2026-10-25)

A distinct **offline-only** implementation was committed as
`afed1db11d02ae072925ebc1d0b9591b6e245c8b`:

- `d2_ctl_attempt3_offline.py`: read-only historical and frozen-state
  preview; deterministic pure functions for ordered quota/Scheduler gate
  simulation. It has no `--prepare` mode.
- `test_d2_ctl_attempt3_offline.py`: 36 defined synthetic tests for
  invalid quota, Scheduler rejection, first-before-second read ordering,
  identity reuse, integrity and no-live-call semantics.
- `d2_ctl_attempt3_offline_manual.sh`: one-time offline qualification
  with pinned HEAD, AST parse, unit tests, immutable historical input-hash
  checks and read-only D2 preview.
- `D2_CTL_ATTEMPT3_OFFLINE_QUALIFICATION_2026_10_25.md`: operator runbook.

**Important:** The synthetic quota checker is a qualification prototype,
not a production live-admission implementation; it does not yet validate
the real Pydantic QuotaSnapshot or authorize a real Scheduler/Provider call.
The tests were authored and reviewed statically, but **their execution
inside the owner's pinned D0 environment is pending**. A passing
qualification would still NOT authorize Attempt-3 Prepare, Claim, or Worker.

The offline evidence directory, if created by the manual qualification,
is `observations/ctl-attempt3-offline-qualification`, separate from the
forbidden-until-approved live identity `ctl-prepare-attempt-3`.
