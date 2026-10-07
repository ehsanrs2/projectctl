# ADR-034: Automated Worker Turns Use One Account-Global Dispatcher

Status: Accepted

## Context

M4.0a made quota-consuming worker admission account-global.

M4.0b added cross-project portfolio arbitration, while M4.1b later introduced bounded same-project
active sets. The post-M4 review found that these correct components still selected automated worker
turns through different orchestration paths:

- portfolio mode assumed at most one active run per project;
- project-local auto selected/continued work directly;
- parallel batch selected same-project worker turns directly;
- verification, integration and recovery were mixed with worker-turn progression.

M4.2a unified execution-input authority. M4.2b now closes the remaining orchestration split.

## Decision

ProjectCTL separates **worker-turn arbitration** from **non-worker lifecycle maintenance**.

### ProjectTurnEnvelope

Each project exposes one derived, non-authoritative `ProjectTurnEnvelope v1`.

The envelope answers only:

> If this project receives the next quota-consuming turn for its account, what exact worker action
> is eligible now?

Possible actions are:

- `resume_run`
- `start_run`
- `admit_task`

The envelope includes:

- project instance/id/root
- quota account
- active run ids/count
- configured active-set capacity
- selected run/task/resource class
- scheduler/project/quota digests
- parallel-admission requirement
- non-worker run ids
- integration queue head
- explicit exclusion reasons

It contains no cross-project scheduler score.

### Active-set capacity authority

`.projectctl/config.yaml` now owns:

```yaml
orchestration:
  max_active_runs: 1
```

The current project-config schema is v9.

Values:

- `1`: serial automated active set
- `2..8`: bounded parallel active set

A CLI flag is not an independent concurrency authority.

When capacity exceeds one, automated first-slot admission is parallel-bound from the beginning.
This prevents a serial unbound first run from later becoming an unsafe peer when a second slot is
admitted.

### Project-local turn arbitration

Within one project:

1. checkpointed RUNNING continuation has highest priority;
2. CLAIMED start is next;
3. a new task may be admitted only if active-set capacity remains;
4. new parallel admission requires pairwise M4.1/M4.2 proof against all active bindings;
5. live project-local leases are never stolen;
6. malformed/unbound active sets fail closed.

The local arbiter produces an envelope. It does not consume account admission.

### Account-global portfolio arbitration

Portfolio v2 evaluates project envelopes.

It chooses between projects using:

1. continuation action class before new admission;
2. least-recently-admitted fairness within the action class;
3. deterministic registration/project identity tie-breaks.

A project with multiple valid parallel-bound active runs is no longer excluded merely for having
more than one active run.

M4.0a remains the final atomic quota-account admission authority immediately before provider
contact.

### One automated dispatcher

Automated paths use the same portfolio fairness decision:

- `projectctl portfolio run`
- `projectctl portfolio cycle`
- project-local `projectctl run auto`
- `projectctl parallel run`

A project-local command never silently executes another project's work. If portfolio arbitration
selects another registered project, the local command yields with durable/reportable
`portfolio_yield` semantics.

Thus selecting a different autonomous CLI surface cannot bypass account-global fairness.

Manual low-level lifecycle commands remain explicit operator actions rather than portfolio-fair
autonomous loops.

### Non-worker maintenance

Verification, integration, delivery/review reconciliation and deterministic crash recovery do not
consume an account worker-turn slot.

They are advanced separately through project maintenance.

Maintenance:

- never starts or resumes a worker;
- respects live project-local leases;
- does not integrate/reconcile target-changing work while another exact-base worker phase remains;
- uses parallel integration when the run has a parallel binding;
- remains bounded and deterministic.

Account-global `portfolio cycle` performs maintenance for registered projects on that account before
selecting at most one worker turn.

### Parallel batch semantics

`projectctl parallel run` is now a bounded fair wave rather than a local worker-turn loop.

It:

1. validates/reconciles the current parallel active set;
2. requests worker turns through portfolio fairness;
3. yields if another project wins the account;
4. stops admitting when configured active capacity is reached;
5. drains non-worker phases independently.

`--max-runs` is compatibility/assertion only and, when supplied, must equal configured
`orchestration.max_active_runs`.

### Serial auto semantics

`projectctl run auto` no longer treats a valid multi-run active set as inherently corrupt.

It can maintain the active set and request its next worker turn through the same portfolio
dispatcher.

A live run lease, invalid active set, human decision, review wait, stale quota or another project's
fair turn still causes a deterministic stop/yield.

### Observability

M4.2b adds derived orchestration status exposing:

- active run ids/count/capacity
- non-worker run ids
- integration queue head
- next local turn envelope
- current account admission owner

This remains observational, not authority.

## Consequences

Positive:

- account fairness cannot be bypassed by choosing serial versus parallel autonomous commands;
- portfolio understands bounded same-project concurrency;
- M4.0a remains the sole atomic account-admission authority;
- worker turns and non-worker lifecycle phases have explicit separate responsibilities;
- active-set capacity has one project configuration authority;
- status exposes the real concurrent control-plane state.

Tradeoffs:

- project config advances to schema v9;
- autonomous project-local commands may yield instead of executing immediately;
- true simultaneous worker turns on one quota account remain intentionally unsupported;
- projects changing capacity from one to multiple active runs must first reach a clean/bound state;
- orchestration remains turn-based rather than an always-on daemon.

## Rejected alternatives

### Keep portfolio single-run and special-case parallel CLI

Rejected because this preserves multiple fairness authorities.

### Let `parallel run` bypass portfolio because M4.0a still serializes quota

Rejected because quota safety alone does not provide cross-project fairness.

### Integrate/verify under the account admission lease

Rejected because these phases do not consume provider quota and would unnecessarily block other
projects' worker turns.

### Make `--max-runs` the concurrency authority

Rejected because runtime flags are not durable project policy.

### Treat every active run equally in portfolio ranking

Rejected because only quota-consuming continuation/admission actions belong in worker-turn
arbitration.

## Implementation record

Implemented in M4.2b.

Public contracts:

- `ProjectTurnEnvelope v1`
- `ProjectTurnResult v1`
- `ProjectMaintenanceResult v1`
- `OrchestrationStatus v1`
- `PortfolioDecision v2`
- `PortfolioTurnResult v2`
- `PortfolioCycleResult v1`
- `ProjectConfig v9`

## Follow-up

With M4.2a and M4.2b complete, the post-M4 contract-closure sequence is complete.

The next milestone is:

> **M5.0 — Context Discovery & Scope Assistance**

Derived repository/AST/Graphify relationships may propose execution scopes, but human/control-plane
scope authority remains unchanged.
