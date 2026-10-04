# ADR-015: GitHub Structured Dependencies and Sub-issue Hierarchy

Status: Accepted

## Context

After M3.0c, GitHub Issues can participate in the full ProjectCTL execution lifecycle under the
current direct-publication policy.

However, M3.0a deliberately normalized GitHub tasks with empty `dependencies` and `blocks`.
That means the scheduler could consider an Issue READY even when GitHub's native dependency model
said the Issue was blocked by another Issue.

GitHub now exposes dedicated REST endpoints for:

- dependencies an Issue is blocked by
- dependencies an Issue is blocking
- parent/sub-issue hierarchy

These are structured provider relationships and are preferable to parsing Issue prose.

Dependency and hierarchy semantics must remain separate. A sub-issue relationship is
organizational hierarchy; GitHub does not make it equivalent to a blocking dependency.

## Decision

M3.1a consumes GitHub's structured relationship APIs and normalizes them into ProjectCTL task
state.

### Dependency authority

For each GitHub Issue, ProjectCTL reads the native `dependencies/blocked_by` relation.

This is the canonical dependency input.

ProjectCTL derives reverse `blocks` edges from the normalized blocked-by graph rather than
maintaining a second independent provider representation.

ProjectCTL does not parse Issue title/body/comments for dependency phrases.

### Scheduler semantics

For same-repository Issues:

- a native blocker becomes `dependencies=["gh-N"]`
- reverse `blocks` edges are derived
- an open/unresolved blocker makes a default READY Issue BLOCKED
- once the dependency is DONE, the scheduler may consider the dependent Issue eligible
- a dependency that is CANCELLED/not-planned is not treated as successfully satisfied

For cross-repository dependencies:

- open/unresolved relations use a stable external id such as
  `github:owner/repository#N`
- that id is intentionally absent from the local snapshot, so the existing scheduler blocks
  automatically
- a closed/completed external dependency is treated as satisfied and recorded in normalization
  notes rather than inserted as a missing edge

Pull-request dependencies, if returned by GitHub, use a distinct external identity and are not
silently converted into local Issue tasks.

### Missing/ambiguous relations

If GitHub proves a same-repository dependency exists but that Issue is absent from the authority
snapshot, ProjectCTL fails closed to `NEEDS_DECISION`.

Malformed relationship records also require human decision.

ProjectCTL does not invent a completed state for inaccessible or ambiguous dependency nodes.

### Dependency cycles

ProjectCTL independently checks the local normalized dependency graph for cycles.

Tasks participating in a cycle become `NEEDS_DECISION` and are not auto-eligible.

This remains true even if the provider normally prevents such cycles; ProjectCTL does not assume
remote invariants without validating its own normalized snapshot.

### Sub-issue hierarchy

Sub-issues are represented separately through `TaskHierarchy`:

- `parent`
- `sub_issues`

Sub-issues do **not** become scheduler dependencies implicitly.

Parent pointers are derived from the provider's sub-issue lists for tasks visible in the current
repository snapshot.

Cross-repository sub-issues may remain external hierarchy identifiers but do not affect scheduler
eligibility.

Conflicting multiple parents or hierarchy cycles fail closed to `NEEDS_DECISION`.

### TaskSnapshot versioning

Adding hierarchy metadata changes the public nested task contract.

Therefore:

- `TaskSnapshot v1` and `NormalizedTaskV1` remain exported for audit compatibility
- current snapshots use `TaskSnapshot v2`
- `NormalizedTask` v2-compatible current shape adds `TaskHierarchy`
- existing scheduler semantics continue to consume `dependencies` and `blocks`

### Provider failures

Relationship reads are authoritative reads.

If a GitHub dependency/sub-issue endpoint fails, ProjectCTL does not reinterpret the failure as an
empty relationship set. The task read fails instead.

This prevents an API/auth/rate-limit problem from making blocked work appear runnable.

### Performance boundary

M3.1a prioritizes correctness and performs structured relation reads while building the GitHub
snapshot.

It does not introduce a cache whose freshness could become a new source of truth.

M3.1c is responsible for incremental/cached synchronization with explicit freshness and
invalidation semantics.

## Consequences

Positive:

- the autonomous scheduler respects native GitHub blocked-by relationships
- hierarchy is visible without conflating it with execution order
- cycles and missing dependency nodes fail closed
- no prose parsing or LLM relation inference is required
- the generic scheduler does not gain GitHub-specific code

Tradeoffs:

- GitHub snapshot construction performs additional API reads
- cross-repository unresolved dependencies block local automation until their state is observable
- hierarchy metadata requires TaskSnapshot v2
- efficient synchronization remains future work

## Follow-up

M3.1b should add richer GitHub team metadata only where it has explicit stable semantics.

M3.1c should reduce API cost with a derived cache/incremental synchronization layer while keeping
GitHub as the remote authority and preserving freshness evidence.
