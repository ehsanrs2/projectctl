# ADR-029: Global Admission Before Portfolio Scheduling or Parallel Runs

Status: Accepted

## Context

ProjectCTL's single-project execution lifecycle is now mature enough that the next scaling boundary
is cross-project coordination.

Quota observations are already account-global in `$PROJECTCTL_HOME/state.sqlite`, while scheduling,
execution preflight and worker start are still initiated independently by each project.

Two projects sharing one Codex account can therefore observe the same quota state and both decide
that a worker turn is admissible.

The existing project-local safeguards do not solve this:

- project locks coordinate one repository only;
- run leases coordinate one run store only;
- task claims coordinate task ownership, not provider-account budget;
- the quota checkpoint monitor reacts after a worker turn has started;
- the project registry identifies projects but does not arbitrate execution.

Naively adding portfolio scheduling or parallel runs before solving this would introduce a global
decision layer without a global ownership primitive.

## Decision

The next architecture phase is **M4 — Global Orchestration & Safe Concurrency**.

Its first milestone is:

> **M4.0a — Account-Global Execution Admission**

### Admission authority

Account admission state belongs in:

```text
$PROJECTCTL_HOME/state.sqlite
```

It is account-global operational state, not project config, task state, telemetry or provider state.

### First-version admission semantics

M4.0a will permit at most one active quota-consuming worker turn per configured quota account.

This is deliberately conservative.

ProjectCTL does not currently have a trustworthy per-task token/cost predictor, so M4.0a will not
invent percentage or token reservations.

### Admission identity

A durable admission must bind at least:

- quota account;
- project instance id;
- logical project id;
- run id;
- lease owner;
- acquisition time;
- heartbeat time;
- expiry time.

### Atomicity

Admission acquisition must use a real account-global atomic primitive.

For the local-first architecture, SQLite transaction + uniqueness in the global state DB is the
chosen first primitive.

A caller may not contact the quota-consuming worker provider until it owns a valid admission.

### Fresh quota after ownership

Acquiring admission is not itself proof that budget is sufficient.

While holding the admission and before provider contact, ProjectCTL must obtain/evaluate fresh quota
again.

This closes the race where multiple projects previously evaluated one shared observation before
either began work.

### Lifecycle of an admission

Admission is held only while the quota-consuming worker turn needs exclusivity.

It is released when the turn:

- completes;
- checkpoints;
- fails before/during provider execution;
- is explicitly aborted.

It is not held during:

- independent verification;
- local integration;
- direct Git publication;
- external PR/MR review waiting.

A future multi-provider model may define independent budget domains, but M4.0a remains scoped to the
existing quota-account abstraction.

### Crash recovery

Admissions are expiring leases, not permanent locks.

Recovery must distinguish:

- live owner;
- expired/stale owner;
- same run reacquisition/reconciliation;
- foreign run ownership.

Stale lease reclamation must be explicit and auditable.

### Global DB migration

Adding authoritative admission state requires a real global-state schema migration.

M4.0a must:

- advance the global state DB version;
- back up before migration;
- expose deterministic migration behavior;
- validate expected tables/indexes after migration.

### Project-local quota policy remains local

The global admission authority does not replace per-project quota policy.

The architecture remains:

```text
account quota observation  -> account-global authority
account execution admission -> account-global authority
project reserve/thresholds  -> project-local policy
task resource requirement   -> project-local scheduling/execution policy
```

### Portfolio scheduling comes after admission

M4.0b may use the existing global project registry to arbitrate which project receives the next
admission.

It must not replace each project's local task scheduler.

### Parallel runs come later

Same-project parallelism remains unsupported until separate milestones prove:

- scoped execution inputs;
- resource/write-set independence;
- exact-base conflict handling;
- integration ordering;
- transformed-candidate reverification.

Removing the current multiple-active-run stop without those proofs is explicitly rejected.

## Consequences

Positive:

- cross-project execution no longer races on one account budget;
- later portfolio scheduling has an atomic grant primitive;
- future parallelism is built on explicit resource admission rather than optimistic concurrency;
- no fictional token estimator is required.

Tradeoffs:

- first-version M4.0a serializes quota-consuming worker turns per account;
- throughput across projects may initially be lower than technically possible;
- global DB migration becomes part of the control-plane contract.

## Rejected alternatives

### Start with portfolio ranking

Rejected because a ranking decision cannot prevent another process from starting independently.

### Start with multiple active runs

Rejected because current snapshot and exact-base evidence contracts make naive parallel integration
unsafe, and quota admission is still global-racy.

### Reserve estimated token percentages

Rejected because ProjectCTL does not yet possess a trustworthy task-cost estimator.

### Use project-local locks

Rejected because they cannot coordinate separate project roots sharing one provider account.

### Use the task tracker as quota ownership

Rejected because task authority and provider-account budget are different mutable concerns.

## Follow-up

The intended M4 sequence is:

1. M4.0a — Account-Global Execution Admission
2. M4.0b — Portfolio Scheduling & Cross-Project Arbitration
3. M4.1a — Parallel Planning Safety Contract
4. M4.1b — Safe Parallel Execution & Integration

Context discovery/Graphify may be pulled forward before M4.1a if it is needed as derived evidence
for code/write-scope discovery, but it does not precede M4.0a.
