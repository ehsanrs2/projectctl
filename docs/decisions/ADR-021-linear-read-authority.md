# ADR-021: Linear Read Authority Before Lifecycle Writes

Status: Accepted

## Context

M3.0b1 established a provider-neutral Task Authority boundary so additional task systems can be
integrated without reintroducing provider branches into application services.

GitHub subsequently proved a complete lifecycle only after several separate milestones:

- read authority
- distributed claim ownership
- publication-gated completion
- dependency/hierarchy semantics
- team metadata
- bounded cache/freshness behavior

M3.2 begins additional task-authority support. The first question is whether another provider
should be declared execution-capable immediately or integrated incrementally.

Linear exposes a public GraphQL API, team-scoped issues, personal API-key and OAuth authentication,
Relay-style cursor pagination, workflow state types, issue relations, and webhooks. These
capabilities do not imply that Linear has the same claim, compare-and-swap, publication, or
completion semantics as GitHub.

ProjectCTL must therefore avoid translating "the provider can mutate issues" into "ProjectCTL has
proven safe autonomous ownership."

## Decision

M3.2 starts with **M3.2a — Linear Read Authority**.

Linear is registered through the existing provider-neutral Task Authority resolver with:

- read: supported
- claim: unsupported
- release: unsupported
- block_for_decision: unsupported
- complete: unsupported

As a result, Linear is readable but not execution-ready.

### Provider selection

Linear is the first additional provider before Jira.

This is not a claim that Linear is universally preferable. It is an implementation-sequencing
decision:

- one public GraphQL endpoint provides the read surface;
- team UUIDs provide a narrow explicit authority scope;
- cursor pagination is explicit;
- authentication can be injected without persisting provider secrets;
- read support can be proven independently from mutations.

Jira remains in M3.2 scope but is deferred until the shared provider boundary has been exercised
with one additional remote authority.

### Authentication boundary

ProjectCTL does not persist Linear credentials.

The adapter accepts exactly one runtime credential source:

- `LINEAR_API_KEY` for a personal API key, sent as `Authorization: <API_KEY>`;
- `LINEAR_ACCESS_TOKEN` for OAuth, sent as `Authorization: Bearer <ACCESS_TOKEN>`.

If both are present, the adapter fails closed because credential precedence would otherwise be
ambiguous.

Secrets do not enter ProjectConfig, Project State, task snapshots, telemetry, adoption manifests,
or run artifacts.

### Team scope

Linear issues are team-scoped.

ProjectConfig is additively versioned to v4 and adds:

```yaml
task_store:
  provider: linear
  team: <TEAM_UUID>
```

The configured Linear team identity must be a UUID and is normalized canonically.

ProjectConfig v1-v3 remain readable through in-memory upgrade. Existing config files are not
rewritten automatically.

Brownfield AdoptionPlan and AdoptionManifest are additively versioned to v3 so an approved
adoption can durably record the selected Linear team scope.

### Read protocol

The adapter uses:

```text
POST https://api.linear.app/graphql
```

Team issues are read through GraphQL cursor pagination.

For every page ProjectCTL validates:

- the response is valid JSON;
- the GraphQL response has a data object;
- the `errors` array is absent/empty;
- the returned team ID equals the configured team;
- the issue connection contains object nodes;
- `hasNextPage` is boolean;
- when `hasNextPage=true`, `endCursor` is non-empty and advances.

A GraphQL response containing partial data plus errors is an error, not a partial task snapshot.

### Task identity

ProjectCTL displays Linear task IDs as:

```text
lin-<LINEAR_IDENTIFIER>
```

For example:

```text
lin-ENG-123
```

The stable Linear UUID is retained separately as `TaskSource.external_id`.

If the human-readable identifier changes, an existing execution plan would no longer resolve the
same ProjectCTL task ID. That is acceptable in M3.2a because Linear cannot enter autonomous
execution yet. A later execution-capable Linear protocol must explicitly revisit durable task
identity before enabling claims.

### Workflow-state normalization

Linear workflow state categories are observed conservatively:

- completed -> DONE
- canceled -> CANCELLED
- started -> RUNNING
- backlog -> PLANNED
- unstarted -> PLANNED
- unknown/missing -> NEEDS_DECISION

A started issue is observationally running; ProjectCTL does not claim ownership of that work.

### Readiness is withheld

Linear supports blocking/blocker relations. M3.2a does not yet normalize those relations into
ProjectCTL dependency edges.

Therefore no non-terminal Linear issue is exposed as READY.

Backlog and unstarted issues are PLANNED even if their Linear status name resembles "Todo" or
"Ready".

`list_ready()` is deliberately empty.

This avoids scheduling an issue that may be blocked by another Linear issue that ProjectCTL has not
yet represented.

M3.2b owns relationship normalization and scheduler eligibility.

### Delivery policy is non-authoritative until execution is enabled

The resolver provides a structurally valid local-only TaskDeliveryPolicy for Linear so a complete
TaskAuthority object can exist.

This does **not** prove that local integration is sufficient delivery for a future Linear
execution lifecycle.

Because claim/release/completion capabilities are unsupported, ProjectCTL's execution gate stops
before publication/completion policy can become authoritative.

Delivery semantics must be revisited before Linear write capability can be marked supported.

### Polling and future synchronization

M3.2a uses direct GraphQL reads for explicit ProjectCTL snapshot operations.

Linear recommends avoiding polling for continuously synchronized integrations and provides
webhooks for issue changes. M3.2a does not introduce a daemon, webhook receiver, or second task
authority cache.

If Linear becomes a frequently refreshed team authority, a later milestone must choose a bounded
synchronization design that respects webhook authentication/replay safety and does not create a
second authoritative task store.

## Consequences

Positive:

- Task Authority abstraction is exercised by a third provider without application-layer branching;
- Linear tasks are visible through existing ProjectCTL task/status surfaces;
- credentials remain outside persisted project state;
- GraphQL partial failures cannot silently become incomplete snapshots;
- autonomous execution cannot start on Linear before dependency and ownership semantics are
  proven;
- config and adoption contracts remain additively versioned.

Tradeoffs:

- no Linear issue is scheduler-ready yet;
- repeated explicit snapshot reads contact Linear directly;
- issue labels/projects/cycles/due dates are not normalized in M3.2a;
- issue relations are not yet represented;
- no Linear lifecycle mutation is supported;
- Jira remains deferred.

## Rejected alternatives

### Mark unstarted Linear issues READY immediately

Rejected because Linear has native blocker relations. Ignoring them could make ProjectCTL select
work that the canonical task authority says is blocked.

### Reuse GitHub claim semantics

Rejected because Git remote-ref ownership is a GitHub/repository transport property, not a generic
Linear task mutation primitive.

### Store the Linear API key in ProjectConfig

Rejected because ProjectConfig is project policy/state, not a credential store.

### Add Linear and Jira in the same milestone

Rejected because provider-specific auth, identity, dependency and mutation semantics would become
harder to review and easier to conflate.

### Build webhook synchronization before basic reads

Rejected because M3.2a first proves normalization and authority boundaries. A webhook receiver adds
signature verification, replay protection, delivery retry/reconciliation and operational hosting
concerns that are unnecessary for the first safe read adapter.

## Follow-up

M3.2b should normalize Linear issue blocking/blocker relationships and any hierarchy required for
safe scheduler eligibility.

Only after read semantics are complete should a later M3.2 milestone investigate:

- mutation actor identity;
- claim/release ownership or a safe alternative;
- concurrent human edits;
- lifecycle transitions;
- needs-decision representation;
- remote-visible delivery/completion semantics;
- crash recovery and durable evidence.

Jira integration should follow the same proof sequence rather than assuming parity with either
GitHub or Linear.
