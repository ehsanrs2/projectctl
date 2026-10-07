# ADR-033: Scheduler Observation Is Not Execution Input Authority

Status: Accepted

## Context

Post-M4 review found that ProjectCTL currently has two overlapping definitions of execution input
stability.

Serial execution stores and revalidates the semantic digest of the complete TaskSnapshot.

Parallel planning instead uses a scoped digest of the selected task plus locally represented
transitive dependencies.

This duplication becomes unsafe/confusing around provider-native claims.

For example, Beads task-native ownership intentionally mutates the selected task from open/READY to
in_progress while assigning the claimant. That mutation is the expected consequence of ProjectCTL's
own durable claim, but a whole-snapshot post-claim comparison can interpret it as stale execution
context.

The full task snapshot is still useful for scheduler audit and reproducibility. It is simply too
broad to be the execution invalidation authority.

## Decision

ProjectCTL will separate:

1. **scheduler observation**, and
2. **execution input proof**.

### Scheduler observation

The scheduler may continue to observe and digest the complete normalized TaskSnapshot.

Its digest proves:

- what the scheduler saw;
- why candidates were eligible/ineligible;
- how deterministic ranking was reproduced.

It does not prove that every unrelated task must remain byte-for-byte semantically unchanged for a
selected run to stay valid.

### Execution input proof

Execution validity will use a first-class scoped proof.

At minimum it binds:

- project identity;
- project-state digest;
- selected task semantic state;
- relevant transitive dependency semantic state;
- exact Git base;
- execution-relevant task/spec references;
- explicit code input scope when configured;
- scope-policy digest when configured;
- durable claim transition identity.

The exact public schema may be introduced as an ExecutionInputManifest and referenced by a new
ExecutionPlan version.

### Claim transition

Task claim is an expected state transition, not ordinary external drift.

A valid claim-aware flow must prove both:

```text
pre-claim task state is eligible and matches the planned input
        ↓
exact durable claim request/claim is acquired
        ↓
post-claim selected-task change is compatible with that exact claim
        ↓
relevant dependency/project/base inputs are still unchanged
```

Provider-specific expected mutations remain behind task/ownership adapters.

ProjectCTL must not special-case Beads status strings inside generic execution logic.

Instead, the ownership/task-authority boundary must expose enough normalized evidence to prove that
the post-claim state is the expected consequence of this claim.

### Parallel proof

ParallelPlan must reference or extend the same execution-input proof.

It may add:

- write scopes;
- exclusive resource keys;
- pairwise conflict evidence.

It must not maintain a second independent definition of selected-task validity.

### Context

ContextManifest and WorkerRequest must reference the execution-input proof.

When explicit code input/write scopes exist, context should expose them to the worker as bounded
control-plane context/constraints.

Derived discovery may later suggest scopes, but does not become authority.

### Verification

Independent verification must enforce any execution write-scope authorization before evidence can
claim overall pass for a parallel-authorized run.

A candidate that violates its declared write authorization must not first receive an ordinary
passing EvidenceManifest and only fail at integration.

### Reapplication

A reapplication is a derived execution lineage event.

A transformed candidate must bind a new base and fresh verification while preserving explicit
lineage to the source plan/evidence.

Historical scheduler/quota/capability observations must not be presented as if freshly observed at
the transformed base.

### Compatibility

Existing ExecutionPlan v1/v2 and ContextManifest v1/v2 remain audit-readable.

The new contract should be additive.

## Consequences

Positive:

- provider-native ownership mutations no longer self-invalidate valid runs;
- unrelated task lifecycle changes do not invalidate a selected run;
- serial and parallel execution share one input authority;
- context and verification consume the same scope semantics;
- transformed execution provenance becomes explicit.

Tradeoffs:

- a new persisted/public schema version is required;
- claim adapters need explicit transition evidence semantics;
- legacy run artifacts require compatibility reads;
- cross-layer tests become more involved.

## Rejected alternatives

### Keep full TaskSnapshot as execution input and whitelist status changes

Rejected because status is provider-specific and claim may also change assignee/revision metadata.

### Use only ParallelRunBinding for parallel mode

Rejected because that preserves two execution-input authorities and leaves serial/provider claim
semantics unresolved.

### Ignore post-claim task state

Rejected because remote ownership or dependencies can change during claim acquisition.

### Let the worker decide whether the claim-related change is safe

Rejected because task ownership and execution validity are control-plane authorities.

## Implementation record

Implemented by M4.2a in ProjectCTL 0.37.0.

The accepted decision is realized through:

- `ExecutionInputManifest v1`
- `ClaimTransitionEvidence v1`
- `ExecutionPlan v3`
- `ContextManifest v3`
- `WorkerRequest v3`
- `ParallelPlan v2`
- `ParallelRunBinding v2`
- `ParallelReapplicationRequest v2`
- `ParallelReapplicationManifest v2`

Scheduler TaskSnapshot identity remains durable audit evidence but is excluded from the semantic
execution-input digest. Provider-specific claim transition semantics live behind TaskClaimer.
Explicit write scopes are enforced by independent verification as well as integration defense in
depth.

Legacy v1/v2 contracts remain exported and parseable.

## Follow-up

> **M4.2b — Unified Turn Orchestration**
