# ADR-013: GitHub Remote Ref Claim Protocol

Status: Accepted

## Context

M3.0b1 makes ProjectCTL task lifecycle access provider-neutral and exposes task-authority
capabilities explicitly. GitHub Issues remains non-executable because ProjectCTL still needs a
concurrency-safe ownership primitive before two independent runners can prepare the same task.

GitHub issue labels and assignees are useful workflow metadata, but ProjectCTL does not treat them
as an atomic compare-and-swap task lock.

The remote Git repository already has a stronger ownership primitive: an exact ref value can be
created only when absent and deleted only while it still equals an expected object id.

M3.0b2 therefore concerns **claim and release only**. It does not define remote delivery or GitHub
Issue completion.

## Decision

### Claim namespace

A normalized GitHub issue `gh-N` uses the reserved remote branch:

```text
refs/heads/projectctl/claims/issue-N
```

This namespace is control-plane state, not a delivery branch.

### Unique marker commit

The claim ref points to a ProjectCTL-created marker commit.

The marker:

- uses the exact execution `base_commit` as parent
- uses the same tree as that base
- contains no source-code changes
- includes the task id, run id, integration target, claim token, and request time in its message
- is created with `git commit-tree` with local Git hooks disabled
- receives a unique SHA for a unique claim request

Using a unique marker SHA is required for ABA safety. Pointing every claim directly at the same
execution base would not let a stale releaser distinguish a newly reacquired claim from its old
ownership.

### Remote/base precondition

Before claim acquisition:

- the configured GitHub repository must match the repository represented by the local `origin`
  remote
- the remote integration-target branch must exist
- the remote integration-target SHA must equal the execution plan's exact `base_commit`

If the local execution base has not been published to the target remote, ProjectCTL does not create
a claim marker.

### Atomic acquisition

ProjectCTL acquires the claim with an explicit absent-only lease:

```text
git push --force-with-lease=<claim-ref>: origin <marker-sha>:<claim-ref>
```

The empty expected value means the remote ref must not exist.

After the push attempt, ProjectCTL observes the exact remote ref:

- ref equals this marker SHA → acquired, including idempotent retry
- ref exists at another SHA → claim lost
- ref remains absent after another push failure → provider/infrastructure failure, not a claim loss

ProjectCTL never infers ownership from push stderr text alone.

After acquisition succeeds, ProjectCTL revalidates the full execution-plan inputs once more before
creating the isolated worktree. If project state, task snapshot, quota eligibility, or Git base
changed during the distributed claim window, ProjectCTL releases its exact claim and stops stale.

### Exact release

A durable claim is released with:

```text
git push --force-with-lease=<claim-ref>:<ownership-sha> origin :<claim-ref>
```

The exact expected-SHA lease is the server-side release authority.

- successful push → this claim was released, even if another runner immediately reacquires the
  now-free ref before a diagnostic observation
- failed push + missing ref → idempotent success
- failed push + same ownership SHA → provider/infrastructure failure
- failed push + different SHA → ownership changed; fail with claim conflict and refuse deletion

A stale runner therefore cannot delete a later claim, and a legitimate immediate reacquisition
does not turn a successful prior release into a false conflict.

### Durable claim evidence

Before contacting the task authority, run preparation writes:

- `task-claim-request.json`
- a `task.claim.requested` event containing its digest

After the provider observes acquisition/conflict, ProjectCTL writes:

- `task-claim.json`
- a `task.claim.observed` event containing the claim digest and ownership evidence

Successful release records `task.claim.released`.

Before the first worker turn and before resuming a quota-checkpointed worker, ProjectCTL validates
that the provider still reports the exact durable claim as owned. Lost ownership stops execution
with `CLAIM_LOST`; ProjectCTL does not mutate the replacement owner's claim.

Loading a claim for release requires the request and claim artifacts to match their append-only run
event digests. Partial or modified artifacts fail closed.

### Crash recovery

A durable `TaskClaimRequest` is written before remote claim mutation. This ordering makes the
important crash window observable.

For a PREPARING run with a durable request but no durable claim result:

- the task authority may perform a **non-mutating reconciliation**
- GitHub deterministically reconstructs the expected marker SHA from the request and observes the
  remote claim ref
- if the ref equals that marker, ProjectCTL persists the missing TaskClaim and can reconstruct the
  isolated worktree
- if the ref is absent or belongs to another marker, the run records claim loss
- if the provider cannot prove ownership, recovery escalates rather than guessing

Recovery never creates a new claim as part of reconciliation.

A CLAIMED run with durable ownership but a missing worktree may rebuild the worktree only from the
exact execution base. Existing but dirty, wrong-branch, or wrong-HEAD worktrees fail closed.

### Legacy Beads compatibility

Runs created before M3.0b2 contain no durable claim artifacts.

For those runs only, Beads may use its legacy task-id release sequence when **both** claim artifact
files are absent.

If only one artifact exists, validation fails closed.

GitHub never permits legacy release without exact durable ownership evidence.

### Task-authority capability surface

After M3.0b2:

GitHub:
- read: supported
- claim: supported
- release: supported
- block_for_decision: unsupported
- complete: unsupported

Beads retains all current lifecycle capabilities.

Because the current execution lifecycle requires block and completion semantics as well as
claim/release, GitHub still does **not** pass the `execution-ready` gate.

### Doctor

For a GitHub task authority, doctor verifies without mutating the remote:

- GitHub Issues API readability
- configured repository identity
- origin remote identity
- Git transport read access

Write permission, rulesets, and branch-creation/deletion policy are proven only by an actual claim
attempt. Doctor does not create a probe claim.

### Workflow side effect

The claim namespace is under `refs/heads` because branch-ref creation/deletion and exact Git push
lease semantics are documented and testable.

Repositories whose GitHub Actions workflows trigger on every branch push may therefore see workflow
runs for claim creation/deletion. Such repositories should exclude the reserved namespace where
appropriate, for example:

```yaml
on:
  push:
    branches-ignore:
      - "projectctl/claims/**"
```

ProjectCTL does not switch to an undocumented/custom GitHub ref namespace merely to avoid this
side effect.

### GitHub repository policy

Repository rules, branch protections, or insufficient write permission may reject the reserved
claim ref. That is a real policy boundary, not something ProjectCTL bypasses.

A rejected or ambiguous claim does not fall back to issue labels, assignees, local locks, or
force-push without an explicit lease.

## Consequences

Positive:

- two independent runners have a real remote ownership race instead of a label convention
- claim acquisition is idempotently observable
- release proves exact ownership
- stale release cannot delete a replacement claim
- crash recovery has durable provider ownership evidence
- Beads remains backward-compatible for pre-M3.0b2 runs
- GitHub completion cannot accidentally become enabled merely because claim works

Tradeoffs:

- claim/release requires Git transport write permission in addition to GitHub Issues read access
- branch-level repository rules can intentionally block ProjectCTL claims
- broad push-triggered CI may need to ignore the reserved namespace
- a small marker commit is uploaded to the Git object database for each distinct claim request even
  after its ref is deleted

## Scope boundary

M3.0b2 does not:

- close or mutate GitHub Issues
- push verified delivery commits
- create pull requests
- define remote publication success
- make GitHub execution-ready
- infer dependencies or blocked-by relationships

M3.0c owns publication-aware remote completion semantics.
