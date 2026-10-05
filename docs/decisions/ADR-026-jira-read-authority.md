# ADR-026: Jira Cloud Read Authority Boundary

Status: Accepted

## Context

M3.2 proved provider-neutral task, ownership, direct-delivery, and review-delivery
boundaries across Beads, GitHub Issues, Linear, GitHub and GitLab.

The next provider candidate is Jira. Before giving Jira an execution role, ProjectCTL
must prove the same sequence used for Linear rather than introducing provider-specific
application shortcuts.

Current Jira Cloud REST v3 exposes:

- project-scoped issue reads;
- enhanced JQL search with token pagination;
- issue workflow status and status-category metadata;
- parent, assignee, issue type, priority, labels, resolution and timestamps;
- separate transition endpoints for workflow mutation;
- issue entity properties for app/tool-owned metadata.

The transition API does not expose a ProjectCTL-grade compare-and-swap precondition
that would let a read-then-transition sequence safely overwrite workflow state in the
presence of concurrent human changes.

Issue properties are useful for a future ProjectCTL-owned lifecycle namespace, but a
blind property PUT is not treated as a substitute for an atomic ownership/precondition
primitive.

## Decision

### M3.3a is read-only

M3.3a introduces Jira Cloud as a project-scoped Task Authority with:

- read: supported
- claim: unsupported
- release: unsupported
- block_for_decision: unsupported
- complete: unsupported

Jira therefore remains fail-closed for autonomous execution.

### Supported host boundary

The built-in adapter supports canonical Jira Cloud sites only:

```text
<tenant>.atlassian.net
```

Jira Data Center, self-hosted Jira, and custom Atlassian API gateways are not inferred
as equivalent providers in this milestone.

### Persisted identity

ProjectConfig advances additively to v7.

Jira authority identity is credential-free:

```yaml
task_store:
  provider: jira
  site: acme.atlassian.net
  project: ENG
```

ProjectConfig v1-v6 remain readable and are migrated in memory without rewriting the
persisted file.

### Runtime authentication

M3.3a supports local script/bot authentication through:

```text
JIRA_EMAIL
JIRA_API_TOKEN
```

Both values are runtime-only and are never persisted in ProjectCTL config, state,
telemetry, review evidence, or task snapshots.

A future distributable integration may add OAuth 2.0 without changing the Jira task
identity contract.

### Enhanced JQL pagination

Project-scoped task enumeration uses:

```text
POST /rest/api/3/search/jql
```

with an explicit project JQL expression, selected fields, `isLast`, and
`nextPageToken`.

ProjectCTL:

- validates every returned issue still belongs to the configured project;
- rejects malformed pages;
- rejects missing continuation tokens when `isLast=false`;
- rejects repeated continuation tokens rather than looping;
- never silently broadens the project scope.

### Conservative workflow normalization

Jira status categories are not treated as scheduler policy.

M3.3a normalizes:

- done/completed category -> DONE, unless the resolution is cancellation-like
- cancellation-like resolution -> CANCELLED
- indeterminate/in-flight category -> RUNNING observationally
- new/to-do category -> PLANNED
- unknown category -> NEEDS_DECISION

A Jira "To Do" category is deliberately not mapped to READY. Jira projects may use
custom workflows where status-category membership does not prove that ProjectCTL is
allowed to start the work.

Explicit workflow/eligibility semantics are deferred to M3.3b.

### Task metadata

M3.3a normalizes:

- stable Jira issue id and key
- summary
- issue type
- priority
- assignee display name
- labels
- created/updated timestamps
- native terminal resolution
- parent/sub-task hierarchy
- browser URL

Jira due dates are date-only. M3.3a preserves the raw date as a Jira tag and does not
invent a timezone-aware `due_at` timestamp.

### Hierarchy is not dependency

The Jira parent field is observational hierarchy only.

M3.3a does not infer blocker/dependency semantics from parent/sub-task structure.

Issue links, blocker direction, cross-project blockers, dependency cycles, and
eligibility propagation are deferred to M3.3b.

### No lifecycle writes

M3.3a does not:

- transition Jira workflow state;
- assign/unassign issues;
- mutate labels;
- create lifecycle properties;
- claim Jira issues;
- mark completion or needs-decision remotely.

This keeps Jira readable without weakening ProjectCTL's human-intent boundary.

## Consequences

Positive:

- Jira Cloud can become the canonical read authority without a parallel tracker;
- ProjectCTL can inspect and normalize Jira project work safely;
- credentials remain outside durable state;
- the same TaskSnapshot/scheduler/reporting surfaces can consume Jira data;
- execution remains impossible until lifecycle semantics are independently proven.

Tradeoffs:

- Jira "To Do" work remains PLANNED rather than READY in M3.3a;
- dependencies are not yet represented;
- Jira lifecycle mutations remain unsupported;
- Jira Cloud basic authentication is intentionally a local-tool boundary, not a
  Marketplace/distributable app authentication architecture.

## Rejected alternatives

### Treat Jira To Do as READY automatically

Rejected because status category is provider workflow grouping, not ProjectCTL execution intent.

### Transition Jira directly to express ProjectCTL completion

Rejected until a concurrency-safe lifecycle contract is proven.

### Reuse task_store.repository or task_store.team for Jira identity

Rejected because Jira site/project identity is semantically distinct from GitHub repository and
Linear team identity.

### Persist Jira API tokens in project config

Rejected because credentials are runtime authority, not project state.

## Follow-up

M3.3b should prove Jira relationship and workflow eligibility semantics:

- issue-link blocker direction;
- pagination/read consistency for linked issues;
- cross-project dependency identities;
- cycle handling;
- explicit status/workflow readiness mapping.

Only after those semantics are proven should a later Jira lifecycle milestone evaluate
ProjectCTL-owned issue properties or another additive mutation strategy for completion and
needs-decision behavior.
