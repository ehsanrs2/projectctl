# ADR-036: Derived Scope Enters Authority Only Through Digest-Bound Human Review

Status: Accepted

## Context

M5.0 introduced non-authoritative context discovery and scope suggestions.

Those artifacts are deliberately derived evidence. They can help a user understand likely code
inputs and writes, but they cannot safely become execution authority merely because ProjectCTL
generated them.

M5.1 needs a path from useful derived evidence to the human-managed
`projectctl.parallel.yaml` catalog without weakening the authority boundary established in M4.2.

The transition must be:

- explicit
- reviewable as a concrete diff
- bound to exact evidence
- stale-safe
- crash-safe
- auditable
- non-destructive by default

## Decision

M5.1 introduces three public artifacts:

- `ContextScopeReview v1`
- `ContextScopeAdoptionRequest v1`
- `ContextScopeAdoptionReceipt v1`

### Review is not adoption

A review is created only from an exact persisted `ContextScopeSuggestion` id.

The review binds:

- project identity
- task identity and semantic digest
- integration target ref and exact base commit
- discovery digest
- suggestion id and digest
- exact pre-review catalog bytes/digest
- existing task scope digest when present
- selected suggested inputs/writes
- explicit human-added resource keys
- proposed task scope
- exact proposed catalog YAML and digest

The review is durable under:

```text
.projectctl/context/reviews/<task-id>/<review-id>.json
```

Creating a review does not mutate human-managed policy.

### Additive-only mutation

M5.1 adoption is intentionally additive.

It may add:

- reviewed input scopes
- reviewed write scopes
- explicit human resource keys

It does not remove existing inputs, writes or resources.

If an existing tree scope already covers an exact suggested path, the redundant exact scope is not
added.

Scope reduction remains a direct human policy edit rather than a derived-evidence workflow.

A review that adds no semantic authority is rejected as a no-op.

### Exact review digest is the approval token

The CLI prints the digest of the exact `ContextScopeReview`.

Adoption requires that exact value:

```bash
projectctl context adopt-scope TASK_ID \
  --review REVIEW_ID \
  --approve-digest REVIEW_DIGEST
```

The digest binds operator approval to the exact reviewed artifact and proposed policy bytes.

A boolean `--yes` or implicit interactive confirmation is insufficient because it would not bind
approval to a stable proposal identity.

### Staleness checks before authority mutation

Before applying a review, ProjectCTL revalidates:

- project identity
- integration target still resolves to the reviewed base
- task semantic digest is unchanged
- persisted suggestion still matches the reviewed suggestion digest
- suggestion/discovery/base identities still match
- current catalog bytes equal the reviewed before-digest
- proposed catalog reconstructs exactly from the reviewed before-state
- no active project run exists

Any mismatch fails closed and requires a fresh review.

### No active runs during policy mutation

`projectctl.parallel.yaml` is execution authority.

M5.1 refuses to mutate it while any project run is active.

This is intentionally more conservative than task-local invalidation. Scope-policy adoption is rare,
and changing authority only at a quiescent project boundary avoids ambiguous interactions with
already-admitted runs.

### No symlink authority writes

M5.1 refuses to mutate `projectctl.parallel.yaml` when that path is a symlink.

Even a repository-contained symlink introduces avoidable ambiguity about which human-managed file is
being approved and modified.

### Durable adoption request before mutation

Explicit approval is persisted before changing the policy:

```text
ContextScopeReview
       |
       | exact review digest approval
       v
ContextScopeAdoptionRequest
       |
       | authoritative catalog write
       v
projectctl.parallel.yaml
       |
       v
ContextScopeAdoptionReceipt
```

The request records:

- review identity/digest
- approval digest
- actor
- project/task/base/task digest
- expected catalog before digest
- exact proposed catalog digest
- exact proposed task-scope digest

### Crash recovery

If the process crashes after the durable request:

- catalog still equals the before-digest -> retry may revalidate and continue
- catalog exactly equals the proposed after-digest -> retry reconstructs the receipt
- catalog equals neither -> fail closed as ambiguous and require manual audit

An existing receipt must match the exact request digest and review identity.

This avoids guessing whether authority mutation completed.

### Atomic write and rollback

The catalog is written through an atomic replace.

Immediately after the write ProjectCTL parses the resulting catalog and validates:

- exact proposed catalog digest
- exact proposed task-scope digest

If post-write validation fails, ProjectCTL restores the reviewed before-bytes or removes the newly
created catalog when the before-state was absent.

### Human-managed Git boundary remains visible

M5.1 does not commit `projectctl.parallel.yaml`.

After adoption, the repository contains an explicit human-managed policy change. The operator is
expected to inspect the Git diff and commit it deliberately before autonomous execution.

ProjectCTL's existing clean-repository execution preflight therefore provides an additional visible
boundary after adoption.

### YAML normalization is review-visible

PyYAML does not preserve comments/formatting during model serialization.

When an existing catalog's raw bytes differ from the deterministic canonical form, the review emits
a warning that adoption will normalize formatting/comments. The exact byte-level unified diff is
shown before approval.

This behavior is explicit rather than hidden.

## CLI

Review:

```bash
projectctl context review-scope TASK_ID \
  --suggestion SUGGESTION_ID

projectctl context review-scope TASK_ID \
  --suggestion SUGGESTION_ID \
  --input src/a.py \
  --write src/a.py \
  --resource parser-registry
```

The command prints:

- review id
- review digest
- accepted additions
- warnings
- exact catalog diff
- exact adoption command

Adopt:

```bash
projectctl context adopt-scope TASK_ID \
  --review REVIEW_ID \
  --approve-digest REVIEW_DIGEST
```

### Derived evidence remains non-authoritative until adoption

Graphify, AST and other M5.0 evidence do not gain authority merely by appearing in a suggestion or
review.

Authority changes only when:

1. an exact review is created,
2. a human approves that exact review digest,
3. stale checks pass,
4. the catalog write succeeds and validates.

After that point the resulting `projectctl.parallel.yaml` content is ordinary human-managed scope
authority.

## Consequences

Positive:

- derived evidence can become useful policy without silent auto-application;
- approval is cryptographically bound to exact proposal bytes;
- concurrent policy edits invalidate stale reviews;
- active execution cannot overlap authority mutation;
- crash recovery can distinguish before/after/ambiguous states;
- existing scope is never silently removed;
- adoption remains auditable even though operational artifacts are not committed.

Tradeoffs:

- adoption is deliberately multi-step;
- users must regenerate review after target/task/catalog drift;
- catalog formatting/comments may be normalized after explicit diff review;
- scope reduction remains manual;
- the operator still needs to commit the human-managed catalog change.

## Rejected alternatives

### Auto-apply M5.0 suggestions

Rejected because derived evidence would become authority without review.

### Boolean confirmation only

Rejected because `--yes` does not bind approval to exact proposal bytes.

### Allow adoption while unrelated runs are active

Rejected for M5.1. A quiescent project boundary is simpler and safer for authority mutation.

### Replace the task scope wholesale with the suggestion

Rejected because discovery incompleteness could silently remove valid human declarations.

### Automatically commit the catalog

Rejected because the final Git diff/commit should remain a visible human-managed policy boundary.

### Recover ambiguous crash states by assuming success

Rejected. Only exact before-state or exact reviewed after-state is recoverable automatically.

## Implementation record

Implemented in M5.1.

Public contracts:

- `ContextScopeReview v1`
- `ContextScopeAdoptionRequest v1`
- `ContextScopeAdoptionReceipt v1`

No ProjectConfig schema bump is required.

## Follow-up

M5.0 and M5.1 complete the first context-discovery / reviewed-adoption vertical slice.

Before expanding derived context into more languages/providers or adding stronger automation, perform:

> **Post-M5 Architecture Review**

The review should verify that discovery, human approval, policy authority and execution-input
consumption still form one non-circular authority chain.
