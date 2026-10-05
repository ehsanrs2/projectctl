# ADR-022: Linear Relationship Direction and Scheduler Eligibility

Status: Accepted

## Context

M3.2a added Linear as a read-only Task Authority, but deliberately withheld READY eligibility
because Linear has native issue blockers and parent/sub-issue relationships that were not yet
represented in ProjectCTL.

That boundary was necessary: treating an unstarted Linear issue as runnable while ignoring a
canonical blocker could cause ProjectCTL to schedule work that the task authority says cannot
proceed.

M3.2b must answer four separate questions without enabling provider mutations:

1. which Linear relation direction means "this task is blocked by another task";
2. which relation types affect scheduling;
3. how cross-team/missing relation nodes behave;
4. whether parent/sub-issue hierarchy implies dependency.

Linear exposes directional IssueRelation records through an issue's `relations` and
`inverseRelations` connections. For a `blocks` relation, the source `issue` blocks the target
`relatedIssue`.

Linear also exposes a parent pointer and child/sub-issue hierarchy. Linear documents parent and
sub-issues separately from blocking relationships, and team-level workflow automation may
optionally close parent/sub-issues. That automation does not make hierarchy itself a dependency
edge.

## Decision

### Canonical dependency source

ProjectCTL uses the requested issue's **incoming `inverseRelations`** connection as the canonical
Linear blocked-by source.

For every relation whose type is `blocks`:

```text
relation.issue        -> blocker/source
relation.relatedIssue -> blocked target/current issue
```

Before accepting the edge, ProjectCTL verifies that the relation target UUID and team identity
match the requested task.

ProjectCTL does not independently read outgoing `relations` to build a second blocks graph.
Local reverse `blocks` edges are derived from the canonical dependency graph.

This mirrors the existing GitHub design principle: one authoritative direction, reverse edges
derived.

### Relation types

Only `blocks` affects scheduler dependency semantics.

The currently known non-blocking relation types:

- `related`
- `duplicate`
- `similar`

do not create ProjectCTL dependencies.

An unknown or missing relation type fails closed to `NEEDS_DECISION`. ProjectCTL does not assume
that a newly introduced provider relation type is non-blocking.

### Blocker completion semantics

A blocker whose workflow state type is:

- `completed`
- `canceled`

is considered satisfied and is not emitted as an unresolved dependency.

Any other known non-terminal blocker remains unresolved.

This remains safe even if Linear still returns a historical `blocks` relation after the blocker
has become terminal.

### Local blocker identity

If the blocker UUID exists in the configured team snapshot, ProjectCTL maps the dependency to that
task's local ProjectCTL ID:

```text
lin-<current Linear identifier>
```

The UUID is the matching key. The human-readable Linear identifier is not trusted as the relation
join key because issue identifiers can change when issues move teams.

If the relation says that a UUID found in the configured-team snapshot belongs to another team,
ProjectCTL fails closed to `NEEDS_DECISION`.

### External and missing blockers

An unresolved blocker outside the configured team snapshot is represented with a stable external
identity:

```text
linear:<UUID>
```

If relation metadata explicitly says the blocker belongs to another team, the task is safely
blocked by that external dependency.

If the blocker says it belongs to the configured team but is absent from the authority snapshot,
ProjectCTL fails closed to `NEEDS_DECISION`. This may indicate visibility/filtering drift or
another incomplete snapshot condition.

If blocker team identity is missing, ProjectCTL also fails closed.

### Workflow eligibility

Linear workflow categories map to scheduler state as follows:

```text
completed -> DONE
canceled  -> CANCELLED
started   -> RUNNING (observational, not ProjectCTL ownership)
backlog   -> PLANNED
unstarted -> candidate READY
unknown   -> NEEDS_DECISION
```

An `unstarted` task becomes:

- `READY` only when no unresolved blocker exists and no human-decision condition exists;
- `BLOCKED` when one or more unresolved dependencies exist.

A `backlog` issue remains `PLANNED` even when unblocked. Backlog is planning intent rather than
an implicit signal that ProjectCTL should schedule the work.

A backlog issue with unresolved blockers may still appear in the blocked view through its
dependency edges, while its normalized lifecycle remains PLANNED.

### Hierarchy is not dependency

The issue's Linear parent pointer is normalized into `TaskHierarchy.parent`.

For parents present in the configured team snapshot, ProjectCTL uses the parent's local task ID.
For parents outside the team snapshot, ProjectCTL uses `linear:<UUID>`.

Local `sub_issues` are derived by reversing parent pointers.

Parent/sub-issue relationships do not create dependencies and do not change READY eligibility.

This avoids conflating optional Linear parent/sub-issue workflow automation with ProjectCTL
dependency semantics.

### Cycles

ProjectCTL detects cycles independently in:

- the local dependency graph;
- the local parent/sub-issue hierarchy.

Tasks participating in either cycle fail closed to `NEEDS_DECISION`.

### Pagination

Incoming relation connections are paginated independently per issue.

ProjectCTL validates:

- issue response identity;
- connection shape;
- object relation nodes;
- boolean `hasNextPage`;
- non-empty and advancing `endCursor`.

Nested relation data is not assumed complete merely because the outer team issue page was
complete.

### Capability boundary

M3.2b changes read/scheduler semantics only.

Linear capability states remain:

- read: supported
- claim: unsupported
- release: unsupported
- block_for_decision: unsupported
- complete: unsupported

Therefore a Linear issue may now be selected by the scheduler as READY, but ProjectCTL's execution
gate still refuses to start a run because the task authority is not execution-ready.

Scheduler eligibility and autonomous execution capability are intentionally separate contracts.

## Consequences

Positive:

- Linear blockers become real scheduler dependencies;
- unblocked unstarted Linear issues can participate in prioritization;
- cross-team blockers remain safe without inventing local task nodes;
- ambiguous/missing relation state fails closed;
- hierarchy remains useful context without accidentally blocking work;
- the provider-neutral scheduler receives the same NormalizedTask dependency model used by Beads
  and GitHub;
- no Linear write authority is implied by read-side eligibility.

Tradeoffs:

- current snapshots make one independently paginated inverse-relation read per Linear issue;
- outgoing external `blocks` edges are not separately enumerated because local reverse edges are
  derived from canonical incoming dependencies;
- external child issues are not invented from a team-scoped snapshot;
- no Linear cache/webhook synchronization is introduced yet;
- human-readable `lin-IDENTIFIER` task IDs remain unsuitable as a future claim identity without
  revisiting M3.2a's durable-identity caveat.

## Rejected alternatives

### Treat every unstarted issue as READY without reading blockers

Rejected because it ignores canonical provider dependency state.

### Read both outgoing and incoming relations as independent authorities

Rejected because two independently fetched graph directions can disagree transiently and create a
dual-source dependency model.

### Treat parent/sub-issue as an implicit blocker

Rejected because hierarchy and dependency are separate Linear concepts and parent/sub-issue
auto-close behavior is configurable workflow automation.

### Treat backlog as READY when unblocked

Rejected because backlog indicates planned/future work, not sufficient scheduling intent.

### Ignore unknown relation types

Rejected because a future provider relation type could carry scheduling significance.

### Enable Linear mutations now that READY exists

Rejected because readiness proof does not prove task claim ownership, concurrency safety,
delivery evidence, or non-destructive completion semantics.

## Follow-up

M3.2c must investigate Linear claim ownership and delivery feasibility before any write capability
is implemented.

The preferred direction is to determine whether ProjectCTL's existing exact Git remote-ref lease
can be generalized into a provider-neutral code-work claim that is bound to the Linear task UUID,
run identity and candidate/publication evidence.

The milestone must also define how concurrent human Linear changes are revalidated and what
non-destructive provider mutation, if any, can safely represent completion or needs-decision.

Jira should be evaluated only after this sequence is explicit enough to reuse without importing
Linear-specific assumptions.
