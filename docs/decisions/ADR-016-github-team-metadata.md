# ADR-016: GitHub Team Metadata Semantics

Status: Accepted

## Context

M3.1a made GitHub's structured dependency and sub-issue relationships visible to ProjectCTL.

The next integration question is how much of GitHub's team metadata should affect scheduling and
execution.

GitHub Issues expose stable issue-level metadata such as:

- assignees
- native issue type
- milestone metadata, including due date
- optional organization-level issue field values

GitHub Projects V2 is a separate project-management authority with its own item/field model.

Treating all of these values as equivalent scheduling inputs would be unsafe. In particular:

- assignee is not ProjectCTL claim ownership
- arbitrary custom fields such as "Priority" do not automatically share ProjectCTL priority
  semantics
- ProjectV2 fields may conflict with repository Issue metadata
- optional issue-field APIs are not universally available across repositories

## Decision

M3.1b normalizes only stable core Issue metadata into the main task snapshot.

### Team metadata

Current NormalizedTask includes TaskTeamMetadata:

- assignees
- native GitHub issue type
- native milestone metadata

Assignees are normalized as deterministic GitHub logins.

They are observational team context only. They do not:

- claim a ProjectCTL task
- make a task READY/BLOCKED
- change score
- select a worker
- grant permissions

### Native issue type

GitHub's native issue type is an explicit provider field.

ProjectCTL applies this precedence:

1. explicit ProjectCTL `type:` label
2. recognized native GitHub issue type
3. common generic labels such as bug/enhancement/documentation/security
4. UNKNOWN

If an explicit recognized ProjectCTL type and recognized native GitHub type disagree, the task
fails closed to NEEDS_DECISION.

Unknown/custom native issue-type names remain visible in team metadata but are not guessed into a
ProjectCTL TaskType.

### Milestone metadata

The native GitHub milestone remains the preferred milestone identity when present.

TaskTeamMetadata preserves:

- milestone number
- title
- state
- due date
- external URL
- open/closed issue counts

The milestone title continues to populate the existing `task.milestone` scheduling field.

A native milestone due date populates `task.due_at`, making GitHub's explicit milestone deadline
a real scheduler urgency input.

If a native milestone conflicts with an explicit `milestone:` ProjectCTL label:

- milestone scoring is disabled
- due_at is cleared
- the task becomes NEEDS_DECISION
- native milestone metadata remains available for audit/explanation

### Semantic vs observational metadata

Assignees and other TeamMetadata that do not affect scheduling are excluded from
`semantic_task_snapshot_digest` and from GitHub's semantic `source_revision`.

This means team-only changes remain visible in a fresh TaskSnapshot but do not invalidate an
already-built ExecutionPlan.

Fields that are intentionally mapped into semantic task properties, such as native issue type or
milestone due date, still affect the semantic digest through `type`, `milestone`, or `due_at`.

### TaskSnapshot versioning

Adding TeamMetadata changes the public nested task contract.

Therefore:

- TaskSnapshot v1 remains exported
- TaskSnapshot v2 remains exported
- current TaskSnapshot is v3
- NormalizedTaskV1 and NormalizedTaskV2 remain available for audit compatibility
- current NormalizedTask adds TeamMetadata

No existing public schema is modified in place.

### Custom issue fields

GitHub exposes a dedicated issue-field-values REST API for organization-level issue fields.

M3.1b deliberately does not make that optional API part of core snapshot construction.

Reasons:

- issue fields are not enabled for every repository
- field names/values are organization-defined
- a field named Priority, Risk, DRI, or Due Date does not automatically have ProjectCTL semantics
- making the endpoint mandatory would make an optional team feature a hard availability
  dependency for the task authority

Future support must be explicit/opt-in and must define field mapping policy before custom values
can affect scheduling.

### GitHub Projects V2

Projects V2 is a distinct authority surface.

M3.1b does not implicitly merge ProjectV2 fields into Issue authority state.

A future Projects integration must define:

- which project is bound to this ProjectCTL project
- field mapping policy
- conflict precedence with native Issue metadata
- freshness and pagination behavior
- whether fields are observational or semantic

Projects metadata must never become claim ownership merely because an Issue is assigned to a user
or project item.

## Consequences

Positive:

- ProjectCTL exposes useful team context without weakening ownership semantics
- GitHub milestone deadlines can participate in deterministic urgency scoring
- native Issue type is usable without prose inference
- assignee churn does not stop safe in-flight work
- public task contracts remain versioned additively

Tradeoffs:

- Projects/custom issue fields are intentionally deferred
- arbitrary organization-specific priority fields are not automatically understood
- users who want custom-field-driven scheduling will need an explicit mapping policy in a later
  milestone

## Follow-up

M3.1c should focus on efficient GitHub synchronization and freshness.

A later optional metadata-mapping milestone may add Issue Fields or Projects V2 only after explicit
bindings and conflict precedence are defined.
