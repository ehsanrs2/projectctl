# D2 final research closeout — 2026-10-25

**Decision:** `D2_RESEARCH_COMPLETE__CTL_LOCAL_INTEGRATION_PASS`

**Scope:** A single paired dogfood experiment using independently executed Direct Codex CLI and a ProjectCTL-controlled Codex worker. All references to `main` below concern the **isolated CTL fixture**, not the projectctl product repository. Evidence is based on operator-reported, sanitized local command outputs and independent inspection of source excerpts. Original D2 private logs, quota observations and task state remain on the owner's workstation.

## Executive result

The CTL arm completed its full local lifecycle: official quota and Scheduler admission (on third Prepare attempt), durable Beads claim, isolated Worktree, one paid worker execution, independent verification, candidate commit, one owner-approved `run integrate`, exact-base fast-forward of isolated fixture `main`, Beads task closure, and successful temporary-worktree cleanup.

The local integration wrapper returned:
- decision: `D2_CTL_LOCAL_INTEGRATION_PASS`;
- exactly one dispatch intent; `retry_authorized=false`, exit code 0;
- durable Run status `passed`, canonical Beads task status `closed`;
- all 11 post-integration checks true: exact candidate, `main` equal to candidate and clean, local delivery and no publication, task completion, unchanged Direct arm, correct before/after target;
- `worktree_cleaned=true`.

These are operator-reported checks, not an assertion of live remote access to the operator's machine.

## Frozen identities

- Task: `d2ctl-g4q` — offline JSONL event reporting using stdlib, exactly 3 permitted source writes.
- Direct baseline: `32836ea5633230e50fb9d907dcdba83e357bcfc6`.
- CTL policy baseline: `3c69dd42497acadadc5d64e7b4abe5d412b309f5`.
- CTL verified and integrated candidate: `fedc609d4d247f38e883fb72d72e6d8c9eb38376`.
- Integration was local-only (`code_delivery.mode=local`, `code_transport.mode=local`); neither the original product repository's `main` nor any remote branch was merged/pushed.

## Paired observations

| Dimension | Direct | CTL |
| --- | --- | --- |
| Paid model coding attempts | 1 | 1 |
| Worker outcome | successful | implemented |
| Independent frozen tests | 26/26 | 26/26 |
| Permitted source paths | exactly 3 | exactly 3 |
| Semantic source review | PASS with edge risk | PASS with edge risk |
| Lines in 3 files | 142 | 108 |
| Python AST nodes | 803 | 738 |
| Worker time signal | 32.809408731 s monotonic execution | 33.908 s between durable events |
| Verification time signal | 0.165026099 s frozen tests | 1.084364 s including policy checks and candidate |
| Input tokens | 196,969 (of which 185,088 cached) | unknown; not retained in canonical WorkerResult |
| Output tokens | 2,335 | unknown |
| Final deliverable | uncommitted Direct fixture patch retained | locally integrated verified fixture candidate |
| Control-plane admission | manually checked | two earlier blocked Prepare attempts; third passed |

CTL's 108 LOC is 23.94% fewer than Direct's 142 LOC, but all three files differ by SHA-256; this is not a quality ranking. The aggregators are effectively equivalent. Direct Parser has somewhat more explicit validation and slightly stronger subjective readability. Both pass frozen tests and source review, with shared resource-exhaustion/deep-JSON edge risk outside the 26-test suite.

The 33.908 s vs 32.8094 s comparison is **descriptive only**: timing boundaries differ, and there is one observation per arm. Verification elapsed times likewise cover different activities. The Direct CLI 0.163.0 and CTL openai-codex SDK/runtime 0.160.0 (adapter 0.41.0) are confounders. CTL token/caching figures must not be estimated from Direct numbers.

## Operational lessons and follow-up

1. **Demonstrated value:** policy-bound quota/Scheduler admission, exact task ownership, audit-friendly run/evidence digests, enforced three-file scope, independently verified tests, tamper-checked candidate identity, fail-closed local delivery and Beads completion all worked together in the final successful attempt.
2. **Measured friction:** two CTL admission blocks, multiple independent authorization gates and manual inspections occurred before full completion. They matter when assessing user-effort and end-to-end time even though no extra paid CTL coding turn was performed.
3. **Instrumentation gap:** CTL canonical `WorkerResult` does not expose token usage or a precisely equivalent model-turn monotonic clock. Add non-sensitive durable usage/latency attribution before any cost-benefit conclusions.
4. **Operator ergonomics:** consolidate fragmented read-only preflight/audit steps into a purpose-built, single-shot, fail-closed lifecycle harness with durable intent and safe reconciliation, without relaxing owner consent boundaries.
5. **Provider evolution:** Beads warned that the legacy `bd --json` shape changes in v2.0; separately qualify the envelope migration before upgrading. This did not fail D2.
6. **Future research:** predeclare at least three independent, comparable tasks/seed replications with matched instrumentation and controlled model/SDK versions. Evaluate hard failures, human-intervention count and time-to-delivery in addition to source quality.
7. **Delivery distinction:** This completes the isolated D2 local Integration experiment. It is **not** a request to merge research work into the product's default branch, deploy ProjectCTL, redo Direct, publish artifacts or trigger further paid model runs.

**Closed state:** `D2_CLOSED__BOTH_ARMS_VERIFIED__CTL_LOCAL_INTEGRATION_PASS__REMOTE_UNCHANGED`. Further implementation or publication remains a separate owner decision.
