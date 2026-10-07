# Post-M5 Architecture Review

Status: **Accepted architecture review**
Date: **2026-10-07**
Reviewed baseline: `main@ddba491672029312505b9cee8a2c2ac368960e4f`

## Executive conclusion

M5 established a sound first vertical slice from derived repository context to reviewed
human-managed execution scope.

The strongest property is that **derived evidence never silently becomes execution authority**.

The current chain is explicit:

```text
Git-base repository/task evidence
        ↓
ContextDiscoveryReport
        ↓
ContextScopeSuggestion
        ↓
ContextScopeReview
        ↓
exact review-digest approval
        ↓
ContextScopeAdoptionRequest
        ↓
projectctl.parallel.yaml
        ↓
ContextScopeAdoptionReceipt
        ↓
ExecutionInputManifest / ParallelPlan
```

Graphify remains advisory. AST/repository heuristics remain advisory. The worker cannot modify the
scope catalog under normal verification policy. M4.2 execution-input semantics consume the resulting
human-managed scope and verification enforces declared writes when such scope exists.

That is a meaningful architecture improvement.

However, this review found one **critical concurrency defect** and two **high-severity contract
gaps** that should be closed before ProjectCTL expands into broader context automation, more language
providers, skills, or stronger autonomy:

1. **M5.2a — Execution Authority Mutation Serialization**
2. **M5.2b — General Execution Scope Policy & Enforcement Mode**

The critical defect is a TOCTOU race: M5.1 checks that no run is active while holding
`context-scope-adoption.lock`, but new run admission is serialized by a different
`run-prepare.lock`. A run can therefore become active after the quiescence check and before
`projectctl.parallel.yaml` is replaced.

The first high-severity gap is semantic: scope governance is still optional for ordinary serial
execution. A task without a scope declaration receives no write boundary, and the reserved
`execution-write-scope` verification check passes by construction.

The second high-severity gap is architectural naming/ownership drift:
`projectctl.parallel.yaml` and `ParallelScopeCatalog` are now used by serial execution context,
serial verification, M5 review/adoption, and parallel conflict proof. They are no longer merely a
parallelism policy.

The M5 safety boundary is therefore good, but its authority contract needs one more closure sequence
before the next major product expansion.

---

## 1. Review scope

This review followed the complete M5 authority path and its downstream consumers.

Primary M5 paths reviewed:

```text
projectctl/context/discovery.py
projectctl/context/adoption.py
projectctl/cli/m50.py
projectctl/schemas/context_discovery.py
projectctl/schemas/context_adoption.py
docs/decisions/ADR-035-context-discovery-derived-evidence.md
docs/decisions/ADR-036-reviewed-context-scope-adoption.md
```

Downstream execution paths reviewed:

```text
projectctl/application/execution.py
projectctl/application/execution_inputs.py
projectctl/application/turns.py
projectctl/application/verification.py
projectctl/context/assembler.py
projectctl/parallel/catalog.py
projectctl/parallel/service.py
projectctl/parallel/runtime.py
projectctl/project/locking.py
projectctl/git/worktrees.py
projectctl/schemas/parallel.py
projectctl/schemas/verification.py
```

Architecture authorities reviewed:

```text
docs/PROJECTCTL_BLUEPRINT.md
docs/PROJECT_STATE.yaml
ADR-033
ADR-034
ADR-035
ADR-036
POST_M4_ARCHITECTURE_REVIEW.md
```

The review concentrated on:

- derived evidence versus authority;
- stale evidence;
- policy mutation atomicity;
- crash recovery;
- run admission races;
- serial versus parallel scope semantics;
- verification write enforcement;
- reapplication;
- operator approval semantics;
- portability/audit semantics.

---

## 2. What M5 got right

### 2.1 Derived evidence is kept out of the authorization path

M5.0 correctly makes both:

```text
ContextDiscoveryReport v1
ContextScopeSuggestion v1
```

explicitly non-authoritative.

Neither artifact is automatically fed into `ExecutionInputManifest`.

Neither artifact mutates `projectctl.parallel.yaml`.

This is the correct boundary.

### 2.2 Built-in discovery is reproducible against a Git base

The built-in provider reads tracked content through Git object access at the selected base.

Dirty working-tree code does not become discovery evidence for that base.

This prevents a local uncommitted edit from silently changing the proposed scope for an otherwise
stable task/base pair.

### 2.3 Graphify is supplemental evidence, not a hidden execution dependency

ProjectCTL reads an existing `graphify-out/graph.json` only when explicitly enabled.

It does not invoke Graphify or an LLM in the execution critical path.

The graph digest/provenance are recorded, while Graphify freshness is deliberately not promoted to
Git-base authority.

This is a sound integration boundary.

### 2.4 Write suggestions are more conservative than navigation suggestions

M5.0 does not treat every related path as a write candidate.

Inferred/ambiguous graph edges cannot independently create write scope.

Write candidates require stronger evidence such as explicit action-bearing path mentions, concrete
Python symbol matches, or conventional test companions.

This distinction should remain.

### 2.5 M5.1 introduces an actual human review boundary

The adoption path is not a disguised auto-apply.

A review persists:

- exact base;
- exact task digest;
- exact suggestion digest;
- exact pre-policy bytes/digest;
- selected additions;
- exact proposed catalog bytes/digest.

The operator must then supply the exact review digest to adoption.

This is strong **content binding**.

### 2.6 Adoption is additive and stale-safe

M5.1 does not silently remove existing scope.

It rejects no-op reviews and revalidates task/base/suggestion/catalog state before mutation.

Concurrent/stale catalog edits invalidate the review.

This is appropriate for a derived-evidence workflow.

### 2.7 Crash recovery distinguishes before/after/ambiguous states

Persisting `ContextScopeAdoptionRequest` before mutation is the correct pattern.

The recovery model:

```text
exact before-state → safe retry
exact reviewed after-state → reconstruct receipt
anything else → fail closed
```

is much stronger than inferring success from process history.

### 2.8 The final Git boundary remains visible

ProjectCTL does not commit the changed human-managed policy.

The main repository becomes dirty after adoption, and normal execution preparation requires a clean
repository.

This creates a useful visible checkpoint:

```text
adopt
  ↓
inspect git diff
  ↓
human commit
  ↓
future execution
```

### 2.9 Worker-side policy mutation is protected

`projectctl.parallel.yaml` is in the default protected-path policy.

A worker cannot normally rewrite the authority that constrains its own writes and still receive
passing verification evidence.

This is an important invariant.

### 2.10 M4.2 execution-input unification successfully consumes adopted scope

When a task scope is present, `build_execution_input_manifest()` binds:

- semantic task-scope digest;
- Git-base code input evidence;
- write scopes;
- resource keys;
- semantic scope-policy digest.

Context assembly exposes those scopes to the worker request, and independent verification enforces
the write boundary.

ParallelPlan v2 is derived from the same execution-input authority.

This means M5 did not create a second execution proof model.

---

## 3. Findings

### Finding A — scope-authority mutation is not atomic with new run admission

**Severity: critical / next-milestone blocker**

M5.1 intends to mutate human-managed execution scope only at a quiescent project boundary.

The adoption path does:

```text
acquire context-scope-adoption.lock
        ↓
assert no active runs
        ↓
revalidate review/catalog
        ↓
write projectctl.parallel.yaml
```

But new run preparation uses a different lock:

```text
run-prepare.lock
```

Therefore these operations are not mutually exclusive.

A valid race is:

```text
Process A: adopt-scope
  acquire context-scope-adoption.lock
  assert no active runs  ← true

                                Process B: prepare run
                                  acquire run-prepare.lock
                                  create PREPARING/active run
                                  bind old scope/execution inputs

Process A:
  write new projectctl.parallel.yaml
```

The statement “scope authority cannot change while a run is active” is therefore not atomically
enforced.

The later semantic scope checks may detect some changes before worker execution, but the architecture
must not rely on post-hoc staleness detection for a boundary M5.1 explicitly claims to serialize.

**Decision:** introduce one shared **project execution-authority mutation gate**.

At minimum:

- new run admission must enter the shared gate before the no-active→active transition;
- reviewed scope adoption must enter the same gate before the active-run check and hold it through
  the authoritative catalog write/validation;
- once a durable active run exists, adoption will observe it and fail closed;
- the gate must have a documented lock order relative to run lease, worker-turn, integration and
  recovery locks.

This is **M5.2a**.

---

### Finding B — scope governance is optional for ordinary serial execution

**Severity: high / contract gap**

Current execution-input construction deliberately treats scope as optional:

```text
_optional_scope(root, task_id)
        ↓
None is allowed
        ↓
ExecutionInputManifest
  code_inputs = []
  write_scopes = []
  resources = []
  scope_policy_digest = None
```

Verification then explicitly does:

```python
if execution_input is None or not execution_input.write_scopes:
    return []
```

Therefore a serial task with no scope declaration can execute with no execution write boundary other
than generic protected-path/diff policy.

Parallel execution correctly fails closed without an explicit scope catalog entry.

M5 now provides a safe workflow for discovering and adopting scope, but the project has no explicit
policy answering:

> Is execution scope optional or required for this project?

Today, the answer is implicit:

- serial: optional;
- parallel: mandatory.

That behavior is backward compatible, but it is not an explicit governance contract.

**Decision:** introduce a project-level **scope governance mode**.

The minimum supported semantics should be explicit and durable, for example:

```text
optional
required
```

Compatibility migration may map existing projects to `optional`; existing behavior must not change
silently.

When mode is `required`:

- new execution admission fails closed if the selected task has no valid execution scope;
- worker request always receives an explicit write boundary;
- verification always has a meaningful execution-write-scope contract;
- parallel planning continues to require scope regardless of mode.

No hidden “manual command bypass” should silently weaken the selected project policy.

This belongs in **M5.2b**.

---

### Finding C — generic execution scope is still named and versioned as parallel scope

**Severity: high architecture/coherence gap**

The human-managed authority is still:

```text
projectctl.parallel.yaml
projectctl.parallel_scope_catalog
ParallelScopeCatalog
ParallelTaskScope
ParallelPathScope
```

But the same contract is now consumed by:

- serial `ExecutionInputManifest`;
- serial worker context;
- serial verification write scope;
- M5 context suggestion coverage;
- M5 reviewed adoption;
- parallel planning/conflict proof;
- reapplication safety.

The semantic role is now **execution scope policy**, not merely parallel policy.

Continuing to add generic scope features to a parallel-named schema will create increasing conceptual
coupling and make operator intent unclear.

**Decision:** M5.2b must define one generic **Execution Scope Policy** contract.

Recommended target:

```text
projectctl.scope.yaml
ExecutionScopeCatalog v1
ExecutionTaskScope
ExecutionPathScope
```

Backward compatibility must be fail-closed and non-ambiguous:

- the existing `projectctl.parallel.yaml` remains readable as a legacy source during migration;
- no silent merge of two scope authorities;
- if both legacy and canonical files exist without an explicit migration state, fail closed;
- exported historical `parallel-scope-catalog.v1` remains readable;
- ParallelPlan continues to consume generic execution scope rather than defining its own scope
  authority.

The exact migration UX can be implemented in M5.2b, but the steady-state architecture should have one
generic scope authority.

---

### Finding D — catalog snapshot construction is safe at apply time but not single-read consistent

**Severity: medium**

M5.1 `_catalog_state()` currently:

1. reads raw bytes;
2. calls `load_parallel_scope_catalog()`;
3. that loader reads the file again.

A concurrent manual edit between those reads can produce a review where:

- `catalog_before_digest` describes one byte snapshot;
- parsed task scopes came from another snapshot.

Adoption will normally fail closed later because the before-digest/reconstructed proposal no longer
matches, so this is not currently an authorization bypass.

But the review artifact/diff shown to the operator can be internally inconsistent.

**Decision:** M5.2a should make catalog snapshot parsing single-read:

```text
read bytes once
  ↓
digest same bytes
  ↓
parse same bytes
```

and perform mutation-critical snapshots under the shared authority gate.

---

### Finding E — review-digest approval is content-bound, not human-identity attestation

**Severity: medium / scope-of-guarantee clarification**

The exact review digest is a strong content-binding mechanism.

It proves:

> the adoption command supplied the digest of this exact review artifact.

It does **not** cryptographically prove which human approved it.

`ContextScopeAdoptionRequest.actor` is currently process identity:

```text
projectctl:<hostname>:<pid>
```

For ProjectCTL's current local-first, single-operator assumptions this is acceptable.

But documentation should not describe this as a signed human identity or non-repudiable approval.

**Decision:**

- retain digest-bound operator approval for the current local product;
- describe it as **content-bound operator approval**, not authenticated human signature;
- if ProjectCTL later supports shared/multi-user control-plane operation, add an identity/signature
  layer as a separate authority feature.

This is not a blocker for M5.2.

---

### Finding F — adoption provenance is durable locally but not portable with the repository

**Severity: medium / audit portability**

Review/request/receipt artifacts live under:

```text
.projectctl/context/
```

and `.projectctl/` is operational state, normally Git-ignored.

After adoption, the portable repository preserves:

- the final `projectctl.parallel.yaml`/future scope policy change;
- Git history of that policy change.

But another clone does not automatically receive:

- ContextDiscoveryReport;
- ContextScopeSuggestion;
- ContextScopeReview;
- ContextScopeAdoptionRequest;
- ContextScopeAdoptionReceipt.

Therefore “auditable” currently means **locally durable + final Git policy history**, not portable
end-to-end provenance.

This is not an execution-safety blocker because the final human-managed policy is the authority.

**Decision:** keep operational adoption evidence local for now, but do not claim repository-portable
approval provenance.

A future optional provenance export may bind a committed policy change to review/adoption digests,
but it must remain non-authoritative.

---

### Finding G — manual human edits remain outside ProjectCTL's transactional lock model

**Severity: medium / accepted boundary**

A human can directly edit `projectctl.parallel.yaml` without using M5.1.

ProjectCTL cannot force an editor to acquire its lock.

This is expected for a human-managed repository authority.

The existing defenses are appropriate:

- execution preparation requires a clean repository;
- execution-input scope digest detects semantic current-task scope changes;
- target/base movement invalidates exact-base planning;
- worker modifications to the policy are protected.

M5.2a must serialize **ProjectCTL-controlled** mutation/admission paths, but it should not pretend to
atomically lock arbitrary external editors.

---

## 4. End-to-end authority analysis

### 4.1 Discovery stage

Authority classification:

```text
ContextDiscoveryReport      derived
ContextScopeSuggestion      derived
Graphify graph               derived/external evidence
```

No execution authority is granted here.

**Result: sound.**

### 4.2 Review stage

`ContextScopeReview` freezes the exact proposed mutation and stale inputs.

It is still not authority because the human-managed catalog is unchanged.

**Result: sound, subject to Finding D consistency hardening.**

### 4.3 Adoption intent stage

`ContextScopeAdoptionRequest` durably records explicit digest-bound operator intent before policy
mutation.

**Result: sound.**

### 4.4 Policy mutation stage

After successful write and post-write validation, the catalog content is human-managed execution
scope authority.

**Result: conceptually sound, but the transition is not atomically excluded from new run admission
(Finding A).**

### 4.5 Git boundary

The repository remains dirty until the policy change is deliberately committed.

Execution planning refuses dirty repositories.

**Result: sound and worth preserving.**

### 4.6 Execution-input stage

When scope exists, `ExecutionInputManifest` consumes one task scope semantically and hashes code
inputs from the recorded Git base.

It does not use M5 discovery artifacts as execution authority.

**Result: sound.**

### 4.7 Worker context stage

Declared inputs/writes are surfaced into ContextManifest/WorkerRequest constraints.

The worker is told paths outside declared writes are read-only.

**Result: sound when scope exists.**

### 4.8 Verification stage

Independent verification enforces `execution-write-scope` when writes are declared.

When no write scope exists, that check passes.

**Result: correct implementation of current optional semantics, but Finding B requires the optionality
to become an explicit project policy.**

### 4.9 Parallel stage

Parallel planning always requires a declared scope and derives ParallelPlan v2 from the same
ExecutionInputManifest semantics.

**Result: sound.**

### 4.10 Reapplication stage

Parallel reapplication validates target-advance overlap against recorded input/write scopes, proves
new-base declared inputs remain byte-equivalent, derives an execution input with explicit lineage,
and requires fresh verification.

**Result: sound.**

---

## 5. Required closure milestones

### M5.2a — Execution Authority Mutation Serialization

**Priority: immediate / critical**

Goal:

> Make ProjectCTL-controlled execution-scope mutation and the no-active→active run admission
> transition mutually exclusive.

Required contract:

1. Introduce one shared project-level authority gate used by:
   - run preparation/admission;
   - reviewed scope adoption.
2. Adoption must hold the shared gate while:
   - reading the final catalog snapshot;
   - checking no active runs;
   - persisting/validating mutation state;
   - atomically writing/validating the policy.
3. Run preparation must hold the same gate until a durable active run state exists.
4. Define lock ordering to avoid deadlock with:
   - worker-turn-dispatch;
   - run lease;
   - integration;
   - recovery;
   - parallel recovery.
5. Parse catalog snapshots from one byte read.
6. Add deterministic concurrency tests reproducing:
   - adoption wins, then run prepare sees new policy;
   - run prepare wins, then adoption observes active run and fails;
   - no state where an active run is admitted under old authority while adoption completes new
     authority.
7. Preserve fail-closed crash recovery.

M5.2a should not rename scope schemas or change optional/required semantics.

That separation keeps the critical race fix small and reviewable.

---

### M5.2b — General Execution Scope Policy & Enforcement Mode

**Priority: next after M5.2a**

Goal:

> Promote the current parallel-named task scope into one explicit project-wide execution-scope
> policy with a durable governance mode.

Required contract:

1. Define generic public models:
   - `ExecutionScopeCatalog`;
   - `ExecutionTaskScope`;
   - generic path scope type.
2. Define one canonical human-managed file, recommended:
   - `projectctl.scope.yaml`.
3. Provide fail-closed migration/read compatibility for `projectctl.parallel.yaml`.
4. Never merge two simultaneous scope authorities implicitly.
5. Add explicit project config policy:
   - `scope_governance.mode = optional|required` or equivalent.
6. Existing projects migrate without silently becoming stricter.
7. When mode is required, every new execution admission must have valid task scope.
8. Parallel execution continues to require explicit scope regardless of optional mode.
9. M5 discovery/review/adoption targets the generic execution-scope contract.
10. ExecutionInputManifest remains the runtime execution authority; the catalog is the human policy
    source that feeds it.
11. Verification behavior for “no scope” becomes an explicit consequence of project policy rather
    than an implicit fallback.
12. Historical public ParallelScopeCatalog v1 remains readable for audit/backward compatibility.

---

## 6. Findings that are not blockers

The following should **not** delay M5.2a:

- Python-first AST depth in M5.0;
- optional Graphify freshness;
- absence of signed human identity;
- local-only review/request/receipt provenance;
- broader multi-language graph extraction;
- automatic suggestion quality scoring;
- richer UI for scope review;
- Obsidian or other cockpit integrations.

Those are later product concerns.

---

## 7. Architecture invariants after the review

These invariants remain accepted:

1. **Derived context is never execution authority.**
2. **Graphify is evidence, not authorization.**
3. **Only reviewed human-managed scope may feed code/write/resource policy.**
4. **ExecutionInputManifest is the runtime execution-input authority.**
5. **ParallelPlan derives from ExecutionInputManifest rather than defining separate inputs.**
6. **Worker output cannot modify human-managed authority and still pass ordinary verification.**
7. **Exact-base candidate transformations require fresh verification.**
8. **M4.0a remains final account-global worker admission authority.**
9. **Project scope policy mutation must become atomic with new run admission in M5.2a.**
10. **Scope optionality must become explicit project policy in M5.2b.**
11. **The generic execution-scope contract must not remain permanently hidden behind a parallel-only
    name.**

---

## 8. Recommended roadmap

```text
M5.0  Context Discovery & Scope Assistance
  ✓
M5.1  Context Review & Adoption Workflow
  ✓
POST-M5 Architecture Review
  ✓
  ↓
M5.2a Execution Authority Mutation Serialization
  ↓
M5.2b General Execution Scope Policy & Enforcement Mode
  ↓
Post-M5.2 closure check
  ↓
Next major product direction
```

Only after M5.2a/b should the project select the next major direction from:

- broader language-aware context discovery;
- additional worker providers;
- governed skills registry;
- Research / Hypothesis / Experiment / Evidence / Decision flows;
- richer trace/evaluation export;
- non-authoritative human cockpit UI.

---

## 9. Review decision

**Accepted with required closure milestones.**

M5.0/M5.1 are not rejected.

Their core authority design is good and should remain.

But ProjectCTL should not treat the M5 scope architecture as complete until:

- M5.2a closes the policy-mutation/run-admission race; and
- M5.2b makes generic execution-scope governance explicit.

The next implementation milestone is:

> **M5.2a — Execution Authority Mutation Serialization**
