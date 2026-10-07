# Post-M4 Architecture Review

Status: **Accepted architecture review**
Date: **2026-10-07**
Reviewed baseline: `main@b165a1c9088bf874d2516522a8098509a9343838`

## Executive conclusion

M4 materially improved ProjectCTL.

The control plane now has real account-global worker admission, cross-project portfolio arbitration,
explicit same-project independence proofs, bounded multi-run active sets, deterministic integration
ordering, and fresh verification after candidate transformation.

Those are meaningful safety primitives, not placeholders.

However, the review found that the M4 layers are **not yet one coherent execution contract**.

The main issue is no longer "parallelism is unsafe." The main issue is that serial execution,
parallel proof, portfolio arbitration, context assembly, verification and reapplication currently
carry partially different definitions of "the inputs that authorize this run."

Two closure milestones are therefore required before ProjectCTL should move to Graphify, additional
workers, skills, or richer autonomous product behavior:

1. **M4.2a — Execution Input Contract Unification**
2. **M4.2b — Unified Turn Orchestration**

After those two milestones, the next major feature review may select context discovery / derived
code graphs as the leading M5 candidate.

---

## 1. Review scope

This review examined the current authority map and the runtime paths introduced through M4:

- M4.0a account-global execution admission;
- M4.0b portfolio scheduling;
- M4.1a parallel planning safety;
- M4.1b bounded parallel runtime and deterministic reapplication;
- task claim semantics, including Beads task-native claims;
- ExecutionPlan validation;
- ContextManifest assembly;
- independent verification;
- integration and reapplication;
- crash recovery;
- project and account-global status surfaces;
- tests that claim the M4 contracts.

Primary code paths reviewed include:

```text
projectctl/application/execution.py
projectctl/application/portfolio.py
projectctl/application/recovery.py
projectctl/application/status.py
projectctl/application/verification.py
projectctl/context/assembler.py
projectctl/parallel/service.py
projectctl/parallel/runtime.py
projectctl/quota/admission.py
projectctl/storage/runs.py
projectctl/integrations/beads/claim.py
projectctl/integrations/beads/task_store.py
```

Architecture authorities reviewed:

```text
docs/PROJECTCTL_BLUEPRINT.md
docs/PROJECT_STATE.yaml
ADR-029
ADR-030
ADR-031
ADR-032
POST_M3_ARCHITECTURE_REVIEW.md
```

---

## 2. What M4 got right

### 2.1 Account-global ownership is now real

Before M4, quota observation was global but execution admission was effectively project-local.

M4.0a fixed that mismatch with one atomic account-global admission record per quota account.

Important properties are now explicit:

- account-scoped ownership;
- project/run identity;
- heartbeat and expiry;
- exact-owner release;
- stale lease reclamation;
- fresh quota check after admission;
- no account admission held during verification/integration/review waiting.

This remains a sound authority boundary.

### 2.2 Portfolio arbitration correctly avoids comparing local scheduler scores

M4.0b made a good architectural choice by choosing projects/actions rather than treating
project-local scheduler scores as globally comparable utilities.

That separation should remain.

### 2.3 Parallel safety is explicit rather than LLM-inferred

M4.1a correctly rejects the idea that an LLM can be the sole conflict authority.

The human-managed parallel catalog provides a deterministic minimum proof:

- input scopes;
- write scopes;
- exclusive resources;
- task/dependency scope;
- exact Git base;
- project-state identity.

This is conservative but architecturally sound.

### 2.4 Exact-base verification semantics survived concurrency work

M4.1b did not weaken the evidence model merely to gain throughput.

A candidate transformed onto a new target requires fresh verification.

That is one of the strongest properties of the current design and should not be relaxed.

### 2.5 Integration ordering is explicit

The integration queue uses deterministic creation order rather than worker completion speed.

This preserves reproducibility and prevents "fastest worker wins" from becoming an implicit
integration authority.

---

## 3. Findings

### Finding A — execution input authority is split across two incompatible proof models

**Severity: critical / next milestone blocker**

Serial execution still treats the semantic digest of the **whole TaskSnapshot** as an execution
input:

```text
ExecutionPlan.task_snapshot_digest
        ↓
_validate_plan_inputs()
        ↓
semantic_task_snapshot_digest(all tasks)
```

Parallel planning introduced a different, more appropriate execution-safety input:

```text
selected task
    +
locally represented transitive dependencies
        ↓
semantic_task_scope_digest()
```

Both now exist simultaneously.

The full snapshot digest is still written into ExecutionPlan and ContextManifest, while
ParallelRunBinding uses the scoped task/dependency digest.

This creates two different answers to the same question:

> What task-authority state must remain stable for this run to be valid?

The architecture should have one answer.

**Decision:** scheduler observation and execution-input proof must become separate concepts.

The scheduler may retain a full snapshot digest for audit/reproducibility. Execution validity must
use a task-scoped semantic proof.

---

### Finding B — provider-native claim mutation can invalidate the plan's own pre-claim snapshot

**Severity: critical correctness defect**

`prepare_next_run()` does this:

```text
build ExecutionPlan from READY task snapshot
        ↓
_validate_plan_inputs(plan)
        ↓
claim task
        ↓
_validate_plan_inputs(the same pre-claim plan)
```

For Beads, `claim_issue()` uses:

```text
bd update <task> --claim
```

and durable ownership validation explicitly requires:

```text
status == in_progress
and assignee == claim.actor
```

Therefore the expected ownership mutation itself changes the normalized selected task from READY to
RUNNING and can change its provider revision.

The second whole-snapshot validation can interpret ProjectCTL's own successful claim as external
`CONTEXT_INVALID` drift.

The execution tests currently use a FakeClaimer that does not mutate the fake task store, so this
cross-layer case is not represented by the test suite.

**Decision:** claim mutation must have an explicit before/after transition contract. ProjectCTL must
distinguish:

- expected mutation caused by this exact durable claim;
- unrelated or unauthorized task/dependency drift.

This is the first requirement of M4.2a.

---

### Finding C — ParallelPlan is a safety sidecar rather than the execution input contract

**Severity: high**

M4.1a deliberately avoided changing ExecutionPlan v2. That was appropriate for a proof milestone,
but M4.1b now executes from both contracts:

```text
ExecutionPlan v2
  - full task snapshot digest
  - project state
  - quota snapshot
  - capability snapshot
  - base

ParallelRunBinding
  - scoped task/dependency digest
  - explicit input evidence
  - write scopes
  - resources
  - old base
```

The runtime must reason about both artifacts and know which field is authoritative in which phase.

That is a transitional architecture, not the desired steady state.

**Decision:** M4.2a must introduce one first-class execution-input proof referenced by execution,
context, verification and parallel admission.

---

### Finding D — portfolio arbitration and parallel active sets are not integrated

**Severity: high orchestration defect**

M4.0b currently excludes a project whenever:

```text
len(active_runs) > 1
```

with:

```text
multiple_active_runs
```

M4.1b intentionally creates exactly that state.

Therefore a project with a valid M4.1b active set becomes ineligible for the M4.0b portfolio
orchestrator.

At the same time, `projectctl parallel run` directly starts/resumes worker turns through the local
runtime. M4.0a still prevents simultaneous same-account worker consumption, so this is not a quota
safety violation.

But it means account-global portfolio fairness is not the orchestration authority for automated
parallel work.

A project running a local parallel batch can repeatedly acquire/release account admission without
the portfolio deciding whether another registered project should receive the next turn.

**Decision:** M4.2b must make the portfolio active-set-aware and route automated worker turns
through one account-global turn dispatcher.

Manual direct run commands may remain safe escape hatches, but automated orchestrators must not
compete as separate fairness authorities.

---

### Finding E — current "parallel runtime" is bounded concurrent WIP, not concurrent worker turns

**Severity: medium; documentation/product semantics**

For one configured quota account, M4.0a admits one quota-consuming worker turn.

In addition, `run_parallel_batch()` advances active runs synchronously.

Therefore current M4.1b parallelism means:

- multiple durable active runs;
- multiple isolated worktrees;
- multiple candidates in lifecycle;
- independent verification/integration states;

but normally not multiple simultaneous worker turns for one account.

This is a reasonable design because ProjectCTL has no trustworthy per-turn cost reservation model.

The problem is terminology: "Safe Parallel Execution" can easily be read as actual simultaneous
worker execution.

**Decision:** documentation should describe the current implementation as **bounded parallel
active-set / concurrent work-in-progress**, with worker-turn concurrency explicitly serialized per
account.

Future true multi-turn concurrency requires a separate quota/capacity authority, not a wider
semaphore.

---

### Finding F — declared code scope is not yet connected to context or verification authority

**Severity: high product/coherence gap**

M4.1a requires human-managed input/write scopes, but context assembly still emits:

```text
ContextManifest.code_paths = []
graph_revision = None
```

The worker request does not receive the declared input/write scope as a first-class execution
constraint.

Also, write-scope enforcement occurs after ordinary verification, immediately before integration.

That means a worker can:

1. spend quota changing out-of-scope code;
2. pass the normal VerificationManifest;
3. produce `overall_pass = true`;
4. only then be rejected by the parallel integration policy.

Safety is preserved because integration fails closed, but evidence semantics and cost efficiency are
poor.

**Decision:** M4.2a must connect execution scopes to ContextManifest/WorkerRequest and move the
parallel write-scope check into independent verification evidence.

The worker still must not become the authority; the scope is human/control-plane policy.

---

### Finding G — reapplication provenance is safe enough to fail closed, but not yet cleanly modeled

**Severity: medium-high**

M4.1b archives old evidence, reapplies a patch and updates the existing ExecutionPlan's base commit
before fresh verification.

That preserves the critical rule "old evidence is not reused."

However, the updated ExecutionPlan still contains scheduler/quota/capability digests originating
from the older planning event.

This makes the object semantically mixed:

- current transformed base;
- historical scheduler/quota/capability inputs.

The reapplication manifest records lineage, but ExecutionPlan itself does not express that it is a
derived/transformed plan.

Additional recovery concerns:

- reapplication directories use random UUIDs;
- `_latest_reapplication_request()` selects by lexicographic path order rather than durable
  request time;
- an ambiguous transformation raises RecoveryError but does not itself durably transition the run
  to NEEDS_DECISION;
- the patch digest is durable, but patch bytes are not persisted as a first-class artifact.

**Decision:** M4.2a should introduce explicit execution-plan lineage / derived-plan semantics and
make reapplication recovery selection/order deterministic.

Ambiguous transformation must leave durable human-decision state rather than only returning an
error.

---

### Finding H — global and project-local observability lag behind the new control plane

**Severity: medium**

`collect_status()` still primarily reports:

- task counts;
- quota mode;
- next scheduler task/model;
- source digests.

It does not provide one coherent view of:

- active runs;
- parallel bindings;
- active-set capacity;
- integration queue head;
- account admission owner;
- project portfolio eligibility;
- blocked reapplication/recovery state.

The data exists but is spread across commands and artifact directories.

This increases operator effort precisely when the system becomes more concurrent.

**Decision:** M4.2b should provide a derived orchestration-status surface. It must remain
non-authoritative.

---

### Finding I — M4.1b test coverage is strong at component boundaries but weak at cross-layer runtime composition

**Severity: high test gap**

The current suite validates many important primitives:

- queue order;
- path-scope rejection;
- rebind clearing candidate;
- reapply→verify→integrate call ordering;
- scoped task digest behavior.

But it does not run a realistic two-task lifecycle where:

- task authority mutates selected-task ownership on claim;
- two real execution plans are prepared;
- both receive parallel bindings;
- worker turns use the actual account admission boundary;
- first integration advances the target;
- second candidate is truly reapplied and independently reverified;
- crash recovery is injected at each reapplication mutation boundary.

This allowed Findings A/B/D to survive a green suite.

**Decision:** M4.2a and M4.2b require cross-layer scenario tests, not only mocked unit composition.

---

### Finding J — the canonical architecture diagram is now behind the implementation

**Severity: documentation drift**

The Blueprint's primary architecture diagram still describes a mostly single-project/single-run
pipeline.

It does not visibly model:

- project registry;
- portfolio arbitration;
- account-global admission;
- parallel active-set proof;
- deterministic integration queue;
- reapplication lineage.

The text later describes those components, but the top-level diagram should reflect the current
control plane after M4.2 closes the identified contract gaps.

---

## 4. Revised authority model

The review freezes the following distinction.

### Scheduler observation

Purpose:

- rank work;
- explain why a task was selected;
- preserve scheduling reproducibility.

May include the complete task snapshot.

It is **not** the execution invalidation boundary.

### Execution input proof

Purpose:

- prove the inputs that make one run semantically valid;
- survive unrelated task lifecycle changes;
- distinguish expected claim mutation from external drift;
- bind context and verification.

Minimum semantic content:

```text
project identity
project-state digest
selected task semantic digest
transitive relevant dependency digests
exact Git base
task/spec references used by execution
declared/derived code input scope when available
scope-policy digest when applicable
claim transition identity
```

### Parallel safety proof

Purpose:

- prove two execution input proofs can coexist;
- add write/resource exclusivity constraints.

It should extend/reference the execution-input proof rather than maintain a second independent task
input definition.

---

## 5. Frozen remediation sequence

## M4.2a — Execution Input Contract Unification

**Next implementation milestone.**

Required outcomes:

1. introduce one first-class execution-input artifact/contract;
2. separate scheduler full-snapshot audit digest from execution invalidation digest;
3. make task claim a modeled expected state transition;
4. prove Beads READY→in_progress claim does not self-invalidate while unrelated relevant mutation
   still fails closed;
5. make serial and parallel execution consume the same task/dependency input proof;
6. reference that proof from ExecutionPlan and ContextManifest;
7. populate code-path context from explicit scope when available;
8. expose input/write scope in WorkerRequest constraints;
9. enforce declared write scope as part of independent verification evidence;
10. model reapplication lineage explicitly instead of silently mixing old planning provenance with
    a new base;
11. make reapplication recovery ordering deterministic and persist ambiguous recovery as
    NEEDS_DECISION;
12. add end-to-end claim-aware and two-run scenario tests.

M4.2a should prefer additive schema evolution (for example ExecutionPlan v3 and/or a dedicated
ExecutionInputManifest) rather than rewriting historical artifacts.

## M4.2b — Unified Turn Orchestration

**Immediately after M4.2a.**

Required outcomes:

1. portfolio inspection understands zero, one, or multiple valid active parallel runs;
2. one project-local turn arbiter represents:
   - resume checkpointed run;
   - start claimed run;
   - optionally admit a new independent parallel slot;
3. the account-global portfolio chooses between project-level turn envelopes;
4. automated serial/parallel paths request worker turns through the same dispatcher;
5. M4.0a remains the final atomic admission authority;
6. non-quota phases (verify/recover/integrate/review reconcile) are modeled separately from
   quota-consuming worker turns;
7. account fairness cannot be bypassed merely by selecting a different autonomous CLI mode;
8. derived status exposes account owner, active set, queue head and next eligible turn;
9. manual direct commands remain safe but are explicitly documented as manual execution paths, not
   portfolio-fair orchestration.

---

## 6. What should *not* be next

### Not Graphify yet

Derived code graphs are still useful.

They can improve:

- suggested read scopes;
- impact analysis;
- context selection;
- human scope authoring.

But adding them before M4.2a would create a smarter producer of scope evidence while the execution
contract consuming that evidence is still split.

### Not more worker providers yet

Additional worker adapters increase capability surface but do not solve the current orchestration
and execution-input coherence problem.

### Not true same-account multi-turn concurrency yet

ProjectCTL still lacks an authoritative cost/capacity model.

Do not infer safe simultaneous worker capacity from quota percentages.

### Not an always-on daemon yet

A daemon would amplify the current divergence between portfolio and local parallel orchestrators.

Unify orchestration first.

---

## 7. Candidate M5 direction after M4.2

If M4.2a and M4.2b close successfully, the leading M5 candidate should be:

> **M5.0 — Context Discovery & Scope Assistance**

Likely shape:

```text
repository structure / AST / optional Graphify
        ↓
derived code relationships
        ↓
scope suggestions + confidence/evidence
        ↓
human-reviewed explicit scope
        ↓
ExecutionInputManifest
        ↓
bounded worker context
```

The graph remains derived evidence, never task/requirements authority.

M5 should improve the cost and quality of scope authoring without weakening the M4.2 authority
model.

---

## 8. Architecture state after this review

The accurate statement is now:

> **M4.0–M4.1 safety primitives are implemented, but M4 requires M4.2 contract closure before the
> global/parallel control plane should be considered architecturally complete.**

This is not a rollback of M4.

It is the expected purpose of an architecture review: identify where independently correct
milestones did not yet compose into one clean system.

The immediate next milestone is therefore:

> **M4.2a — Execution Input Contract Unification**
