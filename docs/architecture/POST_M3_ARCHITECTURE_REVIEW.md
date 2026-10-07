# Post-M3 Architecture Review

Date: 2026-10-05

## Executive conclusion

M0-M3 have established a coherent single-project control plane:

- deterministic task normalization and scheduling;
- explicit task-authority capability boundaries;
- independent execution ownership;
- isolated worktrees;
- worker capability negotiation;
- quota-aware checkpointing;
- independent verification and evidence;
- exact-base integration;
- direct and review-required delivery;
- crash-safe task completion across Beads, GitHub Issues, Linear and Jira.

The next architectural bottleneck is no longer provider support.

The highest-priority correctness gap is **account-global execution admission**.

Quota observation is already account-global, while execution admission is still project-local.
Two ProjectCTL projects that share one Codex account can currently observe the same quota snapshot
and both independently decide that execution is allowed. There is no account-global lease or
reservation that serializes those decisions.

This gap must be closed before portfolio scheduling or safe parallel execution.

The recommended next sequence is:

1. **M4.0a — Account-Global Execution Admission**
2. **M4.0b — Portfolio Scheduling & Cross-Project Arbitration**
3. **M4.1a — Parallel Planning Safety Contract**
4. **M4.1b — Safe Parallel Execution & Integration**

Graph/context discovery, governed skills, additional worker providers and research/experiment flows
remain valuable, but they are not prerequisites for correctness of the global control plane.

---

## 1. Scope of this review

This review re-evaluates the architecture after M3.3c against the core ProjectCTL invariants:

- one authority per mutable concern;
- human intent remains authoritative;
- Task != Run;
- scheduler != execution planner;
- workers are not authorities;
- verification is independent;
- verified code is not silently transformed;
- quota is account-global while policy is project-local;
- unknown state fails closed;
- autonomy remains bounded.

The review focuses on the next scaling boundary rather than adding another provider.

---

## 2. What is architecturally strong now

### 2.1 Authority axes are separated

ProjectCTL now treats these as independent concerns:

- Task Authority
- Code Transport
- Execution Ownership
- Code Delivery
- Verification Evidence
- Run Lifecycle
- Quota Observation

This is the most important architectural improvement from M3.

A GitHub, Linear or Jira task authority no longer implicitly decides code hosting, claim strategy or
delivery semantics.

### 2.2 Provider expansion no longer weakens the core

GitHub Issues, Linear and Jira were each introduced incrementally:

- read semantics first;
- dependency/readiness semantics next;
- lifecycle writes only after an additive/fail-closed mutation contract was proven.

This is a reusable provider-adoption pattern rather than a collection of one-off adapters.

### 2.3 Recovery evidence is first-class

Claims, checkpoints, publication, review delivery and lifecycle completion all have durable evidence
or a deterministic reconciliation path.

The control plane generally asks "what can be proven after a crash?" before enabling mutation.

### 2.4 Delivery is now policy, not provider behavior

Local integration, direct Git publication and review-required delivery are explicit modes.

PR/MR creation is no longer confused with completion, and ProjectCTL does not silently bypass
repository review policy.

### 2.5 Quota observation is correctly account-global

Quota provider selection and observations already live in `$PROJECTCTL_HOME/state.sqlite`, not in
individual repositories.

This is the right authority location and is important groundwork for M4.

---

## 3. Critical findings

## Finding A — account-global quota has no account-global admission authority

**Severity: high / correctness prerequisite**

Current behavior:

- every project reads the same account-global quota source;
- every project evaluates its own local `QuotaPolicy`;
- execution preflight checks the live quota before starting;
- checkpoint monitors continue to observe account quota during a worker turn.

Missing behavior:

- there is no global lease/reservation saying which project/run is currently allowed to consume the
  account budget;
- two projects can pass preflight against the same snapshot concurrently;
- both can then start quota-consuming worker turns.

This violates the spirit of invariant 4.8 even though quota storage itself is correctly global.

### Decision

The next milestone must introduce **account-global execution admission** in
`$PROJECTCTL_HOME/state.sqlite`.

Because ProjectCTL does not yet possess a trustworthy per-task token/cost estimator, M4.0a must
**not invent numeric quota reservations**.

The safe first contract is an exclusive, expiring account admission lease:

```text
quota account
    ↓
at most one active quota-consuming worker turn
    ↓
fresh quota revalidation
    ↓
worker turn
    ↓
release on completion/checkpoint/failure
```

This is conservative but provable.

---

## Finding B — portfolio scheduling is partially scaffolded but not implemented

**Severity: medium / next after admission**

The global state DB already contains a `project_registry` with stable project-instance identities.

However:

- scheduling remains project-local;
- project registry is not yet an arbitration authority;
- scheduler scores from different projects are not automatically comparable because project-local
  policies and weights may differ;
- there is no portfolio decision artifact.

### Decision

Do not jump directly to a global weighted scheduler.

M4.0b should define a separate portfolio arbitration layer that consumes project-local scheduler
results rather than replacing them.

Project schedulers remain authoritative for "best task inside this project".

The portfolio layer decides "which project may receive the next account admission".

---

## Finding C — current parallel execution would violate existing plan/evidence assumptions

**Severity: high / parallelism blocker**

M2 intentionally stops when more than one active run exists.

That limitation is not merely an orchestration switch.

Three deeper contracts make naive parallelism unsafe:

1. **ExecutionPlan task input is snapshot-wide.**
   Preflight compares the plan against the semantic digest of the complete TaskSnapshot.
   Completion or lifecycle movement of another task can invalidate a parallel plan even when the
   selected task itself did not change.

2. **Verified candidates are exact-base.**
   Two runs starting from the same target base may both verify successfully.
   After the first integrates, the second candidate is no longer based on the current target.
   ProjectCTL correctly refuses to silently rebase it.

3. **Integration is serialized on one shared target.**
   The project-wide integration lock prevents concurrent target mutation, but it does not make the
   second exact-base candidate valid after the first target advancement.

### Decision

Safe parallelism is not "remove the single-active-run check".

It needs its own architecture sequence:

- scoped execution-input digests;
- declared or proven write/resource scopes;
- conflict detection;
- deterministic integration ordering;
- a reapplication/reverification contract when target advancement transforms a candidate.

This belongs after global admission and portfolio arbitration.

---

## Finding D — run-store concurrency primitives are stronger than the auto-loop policy

**Severity: low / useful groundwork**

The project run store already has:

- per-run leases;
- one-active-run-per-task uniqueness;
- isolated worktrees;
- append-only run events.

The auto loop nevertheless treats multiple active runs as a fail-closed stop.

This is appropriate today.

The existence of lower-level concurrency primitives should not be mistaken for a proven parallel
scheduler.

---

## Finding E — global state DB needs a first explicit migration path

**Severity: medium / M4.0a prerequisite**

The global DB is currently schema version 1 and contains:

- accounts;
- quota observations;
- project registry;
- provider status.

M4.0a will add authoritative mutable execution-admission state.

That requires:

- `GLOBAL_STATE_DB_VERSION=2`;
- explicit migration/backup semantics analogous to project-state migrations;
- integrity constraints around account/admission identity;
- deterministic stale-lease reclamation.

Global operational state must not be added as an ad-hoc table without a migration contract.

---

## Finding F — context discovery is still intentionally shallow

**Severity: medium / not next**

Current context assembly is deterministic and inspectable, but:

- `code_paths=[]`;
- `graph_revision=None`;
- there is no Context Discovery phase;
- Graphify is still only a future feature flag.

This can reduce worker efficiency on large repositories.

However, it does not currently violate an authority or concurrency invariant.

Graph/context discovery should remain derived and should be added after the global execution
boundary is sound.

---

## Finding G — additional workers are architecturally possible but not a control-plane prerequisite

**Severity: low-to-medium**

The worker layer is provider-neutral, but Codex is the only implemented worker adapter.

Adding another worker provider is useful for flexibility and quota routing, but doing so before
account-global admission would introduce more shared-resource scheduling complexity without first
solving the existing Codex-account race.

---

## Finding H — Blueprint had historical drift

**Severity: medium / documentation authority**

Before this review, the Blueprint still contained historical statements that:

- Linear was only a read adapter;
- review-required delivery had no PR/MR adapter;
- the runtime lifecycle only described behavior through M3.2c2.

Those statements were no longer true after M3.2c3 and M3.3c.

Because the Blueprint is an architecture authority, this review updates those sections rather than
leaving historical implementation notes in the current-state description.

---

## 4. Candidate prioritization

| Candidate | Correctness leverage | Prerequisite value | User value | Complexity | Priority |
| --- | ---: | ---: | ---: | ---: | ---: |
| Account-global execution admission | Very high | Very high | High | Medium | **1** |
| Portfolio scheduling | High | High | High | Medium-high | **2** |
| Safe parallel runs | High | Low until 1-2 exist | Very high | Very high | **3** |
| Context Discovery / Graphify | Medium | Medium for later write-scope inference | High | Medium-high | 4 |
| Additional worker providers | Medium | Low | Medium-high | Medium | 5 |
| Governed skills registry | Medium | Low | Medium | Medium | 6 |
| Research/Experiment flows | Low for execution correctness | Low | High for R&D workflows | High | 7 |
| Rich trace/evaluation export | Low | Low | Medium | Medium | 8 |
| Obsidian cockpit | Low | Low | Medium | Medium | 9 |

The ordering is not a judgment of product importance. It is an architecture dependency ordering.

---

## 5. M4 architecture direction

M4 should be named **Global Orchestration & Safe Concurrency**.

It should not start by making runs parallel.

### M4.0a — Account-Global Execution Admission

Goal:

> Prevent independent ProjectCTL projects from concurrently admitting quota-consuming worker turns
> against the same account-global quota snapshot.

Required contract:

- admission authority lives in `$PROJECTCTL_HOME/state.sqlite`;
- identity binds quota account, project instance, project id and run id;
- one active admission per account in the first version;
- admission has owner, acquired time, heartbeat and expiry;
- acquisition is atomic through SQLite `BEGIN IMMEDIATE` + uniqueness;
- stale lease reclamation is explicit and auditable;
- fresh quota is checked while admission is held before provider contact;
- no provider call occurs without admission;
- checkpoint/completion/provider failure releases admission;
- crash recovery reconciles expired/stale admission;
- admission is not held while waiting for external PR/MR review;
- no fabricated token/cost reservation;
- project-local quota policy remains project-local;
- account quota observation remains account-global.

Non-goals:

- portfolio ranking;
- multiple simultaneous turns on one account;
- token-cost prediction;
- same-project parallel runs;
- global daemon.

### M4.0b — Portfolio Scheduling & Cross-Project Arbitration

Goal:

> Select which registered project receives the next account admission while preserving each
> project's own task scheduler authority.

Required direction:

- build a global PortfolioSnapshot from registered, healthy project instances;
- project scheduler still chooses the candidate inside each project;
- portfolio policy ranks project-level candidate envelopes;
- project-local scheduler weights are not directly compared as globally meaningful numbers;
- human/project priority must be explicit;
- inaccessible/stale project roots fail closed or are excluded with reason;
- portfolio decision is a durable/inspectable artifact.

### M4.1a — Parallel Planning Safety Contract

Goal:

> Define when two runs in one project are independent enough to execute concurrently without
> invalidating each other's proof inputs.

Required direction:

- scoped task/input digests instead of whole-snapshot invalidation where safe;
- explicit resource/write scopes;
- dependency and target-ref conflict checks;
- stable-base relationships;
- no LLM-only conflict authority.

Graph-derived code relationships may assist here, but remain derived evidence rather than the sole
safety authority.

### M4.1b — Safe Parallel Execution & Integration

Goal:

> Allow bounded concurrent work only after planning independence has been proven.

Likely requirements:

- bounded concurrency count;
- per-run account admission/resource admission;
- deterministic integration queue;
- transformed candidates require fresh verification;
- no silent rebase/cherry-pick under old evidence;
- crash recovery for multiple active runs;
- revised auto-run report/state contracts.

---

## 6. Why M4.0a comes before Graphify

Graphify can improve context and eventually help estimate code/write scopes.

But it cannot solve the current account-global quota race.

Making context smarter while two projects can still independently over-admit one shared account
would optimize a layer above an unresolved correctness boundary.

Graphify remains a strong candidate before M4.1a if write-scope discovery needs it, but not before
M4.0a.

---

## 7. Why M4.0a comes before portfolio scheduling

A portfolio scheduler without an atomic admission primitive can decide which project *should* run
next but cannot stop another ProjectCTL process from independently starting work.

Decision without ownership is not coordination.

Therefore portfolio arbitration must sit on top of account-global admission rather than substitute
for it.

---

## 8. Why M4.0a comes before safe parallel runs

Parallelism multiplies the number of simultaneous quota decisions.

Without account-global admission, it makes the existing shared-account race worse.

Even after admission exists, same-project parallelism still needs exact-base and scoped-input work
before it can safely integrate.

---

## 9. Architecture health summary

### Green

- authority separation;
- task-provider boundaries;
- execution ownership;
- crash recovery;
- exact candidate evidence;
- local/direct/review delivery;
- quota observation authority;
- bounded autonomous execution;
- provider lifecycle safety.

### Yellow

- account-global admission;
- portfolio arbitration;
- context discovery;
- worker-provider diversity;
- telemetry/evaluation depth.

### Red if implemented naively

- multiple active runs in one project;
- concurrent same-account worker turns without admission;
- global ranking by directly comparing project-local scheduler scores;
- silent rebase/cherry-pick of verified candidates;
- Graphify becoming task/requirements authority.

---

## 10. Review decision

Freeze the next milestone as:

> **M4.0a — Account-Global Execution Admission**

M4.0a is a correctness milestone, not a throughput milestone.

It should create the global atomic primitive required by later portfolio scheduling and safe
parallelism while preserving the current bounded, fail-closed execution model.
