# ADR-032: Bounded Parallel Runtime With Deterministic Reapplication

Status: Accepted

## Context

M4.1a established a deterministic independence proof for same-project tasks but deliberately left
the runtime single-run.

M4.1b must enable multiple active runs without weakening four existing authorities:

- account-global worker admission from M4.0a;
- task/execution ownership;
- exact-base verification evidence;
- deterministic integration.

A naive implementation would remove the multiple-active-run guard and let each verified candidate
integrate independently. That is unsafe because the first integration advances the shared target
and makes every other same-base candidate stale.

## Decision

M4.1b introduces an explicit **parallel runtime** on top of M4.1a proofs.

The legacy serial `projectctl run auto` remains serial and fail-closed around multiple active
runs. Parallel active sets are owned by the new parallel orchestrator rather than being silently
adopted by the old loop.

### Bounded active set

The explicit parallel runtime accepts:

```text
2 <= max_parallel_runs <= 8
```

A new run may enter the active set only while capacity exists.

Before task claim/worktree creation, its M4.1a `ParallelPlan` is compared against every existing
parallel-bound active run.

Any pairwise dependency, write, input, resource or target/base conflict rejects admission.

This active set is the first runtime resource reservation primitive: declared exclusive resources
cannot coexist in two admitted active bindings.

### ParallelRunBinding

After the task claim succeeds, ProjectCTL captures the task/dependency digest again in the
post-claim state and writes `ParallelRunBinding v1` into the run directory.

The binding records:

- pre-claim proof digest;
- post-claim admitted plan;
- peer plan digests;
- peer safety-decision digests;
- binding time.

This avoids treating the task's own READY → RUNNING claim transition as external input drift.

A run without this binding cannot silently join a multi-run active set.

### Account admission remains authoritative

M4.1b does **not** relax M4.0a.

For one configured quota account:

```text
multiple isolated active runs
        ↓
at most one quota-consuming worker turn at a time
        ↓
worker turn releases account admission
        ↓
another admitted run may receive the next turn
```

Parallelism therefore means bounded concurrent work-in-progress across isolated worktrees and
lifecycle phases. It does not fabricate a safe multi-turn quota capacity that ProjectCTL cannot
measure.

### Verified write scope enforcement

M4.1a write declarations are not merely planning hints.

Before a parallel candidate may integrate, every independently verified changed path must be
covered by the run's declared write scope.

A worker that changes a path outside that scope is moved to human decision and is not integrated.

### Deterministic integration queue

For one integration target, parallel-bound active runs are ordered by:

1. run creation time;
2. stable run id tie-break.

The queue includes unfinished earlier runs, not only candidates that happen to finish verification
first.

Therefore a later run cannot win the target merely because its worker or verifier completed first.

An `AWAITING_REVIEW` run remains queue head until review delivery resolves; later candidates do
not advance the target underneath an outstanding review.

### Target advancement

If queue head verification was performed on the current target base, normal exact fast-forward
integration is used.

If the target advanced after the run was verified, ProjectCTL does **not** reuse the old evidence
and does not mark the stale candidate acceptable.

The runtime first proves:

- the recorded base remains an ancestor of the current target;
- target advancement did not touch the run's declared inputs;
- target advancement did not touch the run's declared writes;
- scoped task/dependency state still matches the admitted binding;
- project state and scope declaration still match;
- the old verified candidate changed only declared write paths;
- the candidate patch applies cleanly to the new target.

Any failure stops closed.

### Reapplication and fresh verification

When those checks pass, ProjectCTL performs a control-plane reapplication:

```text
old verified base
      ↓
old verified candidate
      ↓ extract exact binary patch

current target base
      ↓
apply old candidate patch without creating a commit
      ↓
run status -> VERIFYING
      ↓
fresh independent verification
      ↓
new exact-base candidate commit
      ↓
new evidence
      ↓
integration
```

The original execution plan, evidence and verification manifest are archived under the
reapplication directory before mutation.

The durable run is atomically rebound to the new base and its old candidate is cleared before fresh
verification is accepted.

A transformed candidate can never inherit the old passing evidence.

### Reapplication crash evidence

Before mutating the run worktree, ProjectCTL persists `ParallelReapplicationRequest v1`.

After durable rebind it writes `ParallelReapplicationManifest v1`.

Recovery classifies an interrupted reapplication conservatively:

- original candidate still intact -> retry is safe;
- new base + VERIFYING durable state -> fresh verification is required;
- any ambiguous intermediate state -> fail closed for human decision.

M4.1b prefers an explicit recovery stop over guessing that a partially transformed workspace is
valid.

### Multiple-run recovery

`projectctl parallel recover` inspects every active parallel binding, first re-checks pairwise
independence, then reconciles each run independently through the existing run recovery machinery.

A live run lease is not stolen.

The presence of multiple active runs is no longer itself a recovery error when all are
parallel-bound and pairwise safe.

### Explicit commands

M4.1b adds:

```bash
projectctl parallel run --max-runs 2
projectctl parallel queue
projectctl parallel integrate RUN_ID
projectctl parallel recover
```

The bounded batch command fills one wave of active slots, advances worker/verification phases, then
drains the deterministic integration queue as far as safely possible.

It does not become an unbounded daemon.

### Legacy serial auto mode

`projectctl run auto` remains unchanged in ownership semantics.

If it encounters multiple active runs, it continues to stop rather than taking control of a
parallel-runtime active set.

This is intentional separation between two orchestrators, not an unfinished migration.

## Consequences

Positive:

- same-project multiple active runs are now possible under explicit M4.1a proof;
- worker turns still obey the account-global quota gate;
- exclusive resources receive durable active-set admission semantics;
- worker completion timing cannot reorder integration;
- stale same-base candidates can be deterministically reapplied only when scope evidence proves the
  target advancement is unrelated;
- transformed candidates always receive fresh verification/evidence;
- recovery handles multiple bound active runs without collapsing to the legacy single-run rule.

Tradeoffs:

- quota-consuming worker turns remain serialized for one account;
- deterministic creation-order integration can make a later ready candidate wait for an earlier
  unfinished run;
- reapplication is conservative and may require human intervention after an ambiguous crash;
- legacy serial auto mode and parallel mode are intentionally separate commands.

## Rejected alternatives

### Permit multiple worker turns on one account

Rejected because ProjectCTL still lacks a trustworthy task-cost/token reservation model.

### Integrate whichever candidate finishes first

Rejected because runtime speed would become integration authority and reproducibility would be
lost.

### Rebase/cherry-pick and keep the old evidence

Rejected because the transformed tree is not the verified tree.

### Allow workers to update their own parallel scope

Rejected because scope is human-managed execution authorization.

### Let serial auto adopt a parallel active set automatically

Rejected because that would blur orchestrator ownership and recovery semantics.

## Follow-up

M4.0a through M4.1b complete the correctness sequence identified by the post-M3 architecture
review.

The next step should be a **post-M4 architecture review** before choosing another major feature.
Likely candidates include context discovery/derived code graphs, richer scope assistance, worker
diversity and governed skills, but none should be declared the next implementation milestone until
the review re-evaluates the now-complete global/parallel control plane.
