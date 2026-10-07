# ADR-031: Parallel Planning Requires Explicit Independence Proof

Status: Accepted

## Context

M4.0a introduced account-global worker-turn admission and M4.0b added cross-project portfolio
arbitration. Neither milestone permits multiple active runs inside one project.

That restriction cannot be lifted by changing the auto-loop alone.

The pre-M4.1 execution contract has three important global assumptions:

1. `ExecutionPlan v2` binds the complete semantic `TaskSnapshot` digest.
2. verified candidates are exact-base artifacts.
3. integration mutates one target ref and refuses to silently rebase a stale verified candidate.

Therefore two otherwise unrelated tasks may invalidate each other's plan merely because an
unrelated task changed state, and two verified candidates from one shared base cannot both be
integrated under their original evidence after the first target advancement.

M4.1a must define the proof boundary before M4.1b changes runtime concurrency.

## Decision

M4.1a introduces a separate, non-executing **Parallel Planning Safety Contract**.

It does not change `ExecutionPlan v2`, remove the one-active-run guard, or execute workers in
parallel.

### Scope authority

Parallel safety may not be inferred solely by an LLM.

A task is eligible for parallel planning only when it has an explicit human-managed declaration in:

```text
projectctl.parallel.yaml
```

The file is verification-protected and versioned as `ParallelScopeCatalog v1`.

A task declaration must contain:

- one or more **input scopes**;
- one or more **write scopes**;
- zero or more exclusive **resource keys**.

Missing scope declaration fails closed.

### Path scope model

Path scopes use repository-relative paths and one of two meanings:

```text
exact -> exactly one tracked file/path
tree  -> the complete tracked subtree rooted at the path
```

Inputs are hashed from the recorded Git base commit, not from mutable working-tree bytes.

Write paths may describe files/subtrees that do not exist yet because a task may create them.

### Scoped task-authority digest

A parallel plan does not use the complete task snapshot as its task-authority proof.

Instead, `semantic_task_scope_digest` covers:

- the selected task;
- every locally represented transitive dependency of that task.

Unrelated task lifecycle movement does not invalidate this scoped digest.

The selected task and each included dependency still retain their provider identity/revision,
status, scheduling-relevant metadata and dependency identities in the semantic payload.

### ParallelPlan

`ParallelPlan v1` records:

- project id;
- task id;
- integration target ref;
- exact base commit;
- project-state digest;
- scoped task/dependency digest;
- the ids included in that digest;
- scope declaration digest;
- Git-base input evidence;
- explicit write scopes;
- exclusive resource keys.

A plan is proof material only. It is not a Run and grants no execution authority.

### Revalidation

Before a future M4.1b runtime may rely on a `ParallelPlan`, ProjectCTL must be able to revalidate:

- project identity;
- integration target still resolves to the recorded base;
- project-state digest;
- scoped task/dependency digest;
- scope declaration digest;
- recorded input evidence.

Any drift fails closed.

### Pairwise independence

Two parallel plans are independent only when all deterministic checks pass.

Conflict reasons include:

- same task;
- project mismatch;
- project-state mismatch;
- dependency relationship between the two tasks;
- write/write scope overlap;
- either task writing an input scope of the other;
- exclusive resource-key overlap;
- same integration target planned from different base commits.

Unknown/missing scope never becomes an optimistic success.

### Path overlap semantics

Path overlap is conservative:

- exact/exact conflicts on identical path;
- tree/exact conflicts when the exact path is at or below the tree;
- tree/tree conflicts when either tree is equal to or contains the other.

This does not depend on code-graph inference.

### Shared target and exact-base evidence

Two plans may be execution-independent while sharing the same target and same base.

That does **not** mean both verified candidates can later be integrated using their original
evidence.

If independent plans share one integration target, the safety decision records:

```text
integration_requires_reverification = true
```

After one candidate advances the target, M4.1b must either:

- keep the other candidate unintegrated; or
- deterministically reapply/transform it onto the new target and perform fresh verification.

Old evidence may not be reused for transformed code.

### Graph-derived evidence

Future Graphify/context-discovery output may contribute additional derived read/write relationships.

It may not become the sole authority that makes an otherwise undeclared task parallel-safe.

Explicit human scope plus deterministic repository/task evidence remains the minimum safety
boundary until a later ADR deliberately changes that authority model.

### Artifacts

Parallel planning artifacts live under:

```text
.projectctl/parallel/plans/
.projectctl/parallel/decisions/
```

They are operational proof/audit artifacts and are protected by the existing `.projectctl/**`
verification rule.

### CLI

M4.1a exposes inspection only:

```bash
projectctl parallel plan TASK_ID
projectctl parallel assess TASK_A TASK_B
```

Neither command creates a Run, claims a task, contacts a worker provider, or enables parallel
execution.

## Consequences

Positive:

- unrelated task lifecycle changes no longer need to invalidate future parallel plans;
- code/input invalidation has an explicit deterministic contract;
- write and resource conflicts are auditable;
- same-target exact-base limitations remain visible instead of being hidden behind optimistic
  rebasing;
- M4.1b gets a concrete gate rather than a boolean feature flag.

Tradeoffs:

- users must declare scopes before parallelism can be proven;
- conservative path trees may reject work that could theoretically run concurrently;
- scope declarations can become stale and therefore are themselves digest/revalidation inputs;
- the first contract does not infer scopes automatically.

## Rejected alternatives

### Remove the multiple-active-run guard now

Rejected because runtime concurrency without an independence proof would violate current
task-input and exact-base evidence assumptions.

### Compare only changed files after workers finish

Rejected because conflicts must be prevented before concurrent work begins; post-hoc diff
comparison cannot protect one worker from another invalidating its inputs.

### Ask an LLM whether tasks conflict

Rejected as a sole authority because the answer is not a deterministic ownership/proof primitive.

### Use only write/write overlap

Rejected because one task can invalidate another by writing a file/tree that the other task reads.

### Reuse old verification after rebasing the second candidate

Rejected because transformed code is not the code covered by the old evidence.

## Follow-up

The next milestone is:

> **M4.1b — Safe Parallel Execution & Integration**

M4.1b may use M4.1a proofs to enable bounded multiple active runs, but must preserve:

- account-global admission;
- run/task ownership;
- deterministic integration ordering;
- fresh verification after transformed/reapplied candidates;
- fail-closed crash recovery for multiple active runs.
