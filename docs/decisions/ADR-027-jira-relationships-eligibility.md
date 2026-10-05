# ADR-027: Jira Relationship and Workflow Eligibility Policy

Status: Accepted

## Context

M3.3a established Jira Cloud as a conservative project-scoped read authority but deliberately
kept all to-do/new issues PLANNED and ignored issue-link dependency semantics.

Jira Cloud issue-link types are administrator-configurable. A link type has a stable id plus a
name and separate inward/outward display labels. The REST issue payload exposes one of
`inwardIssue` or `outwardIssue`, but those field names do not themselves define ProjectCTL
dependency direction. Direction must be interpreted together with the configured link-type
semantics.

Jira workflow status categories are likewise provider groupings, not ProjectCTL scheduler intent.
A project may have multiple custom statuses in the same to-do category and not all are necessarily
safe for autonomous pickup.

## Decision

### Persist explicit Jira scheduler policy

ProjectConfig advances additively to v8.

Jira-specific scheduler semantics live under:

```yaml
task_store:
  provider: jira
  site: acme.atlassian.net
  project: ENG
  jira_policy:
    ready_statuses:
      - id: "10000"
        name: Ready
    link_rules:
      - type_id: "10001"
        name: Blocks
        inward_label: is blocked by
        outward_label: blocks
        inward: dependency
        outward: blocks
```

The policy is explicit human intent. ProjectCTL does not auto-write it from provider metadata.

### READY status identity is pinned

A Jira issue may become READY only when:

- its status category is still a to-do/new category;
- its stable status id is present in `ready_statuses`;
- the current status name still equals the pinned name;
- no unresolved dependency remains;
- no other fail-closed normalization condition applies.

If a configured READY status moves to an in-progress/terminal/unknown category or changes name,
ProjectCTL marks the issue NEEDS_DECISION rather than silently accepting provider drift.

Unconfigured to-do/new statuses remain PLANNED.

### Issue-link semantics are allowlisted and bidirectional

Each configured Jira link type pins:

- stable type id;
- type name;
- inward label;
- outward label;
- ProjectCTL semantic for each side: `dependency`, `blocks`, or `ignore`.

Provider metadata must still match the pinned policy exactly.

An unconfigured link type present on a task is not guessed. The task becomes NEEDS_DECISION.

For a configured link:

- `dependency` means the linked issue blocks the current task;
- `blocks` means the current task blocks the linked issue;
- `ignore` is an explicit human decision that this side has no scheduling meaning.

For local project issues, either visible side of a configured link is sufficient to materialize
both canonical edges. This prevents a partial/asymmetric Jira read from leaving the blocked task
falsely READY.

### Terminal blockers are satisfied

A configured blocker is satisfied when its current Jira status category is terminal.

Local blocker state is taken from the project snapshot and checked against embedded linked-issue
metadata when that metadata is present.

Cross-project blockers are independently re-read from Jira before eligibility is decided. The
embedded `issuelinks` status is not treated as authoritative for cross-project scheduler release.
Stable issue id/key must match the link payload after revalidation.

An inaccessible or identity-ambiguous external blocker cannot be proven safe and therefore fails
closed.

### Cross-project identity

Open blockers outside the configured Jira project are represented as:

```text
jira:<site>:<stable-issue-id>
```

This avoids confusing mutable/display issue keys with stable provider identity.

### Hierarchy remains separate

Parent/sub-task hierarchy remains observational.

It never creates a dependency edge by itself.

Dependency cycles and hierarchy cycles are detected separately. Tasks participating in either cycle
become NEEDS_DECISION.

### Metadata discovery and Doctor

`projectctl jira-metadata` exposes current Jira status ids/names/categories and issue-link
type ids/names/inward/outward labels so a human can author the policy deliberately.

Doctor verifies that every configured READY status and link rule still exists and still matches
the pinned provider metadata.

### Lifecycle boundary

M3.3b does not add Jira lifecycle writes.

Capabilities remain:

- read: supported
- claim: unsupported
- release: unsupported
- block_for_decision: unsupported
- complete: unsupported

Autonomous Jira execution therefore remains fail-closed even though scheduler eligibility can now
be computed correctly for reporting/planning.

## Consequences

Positive:

- Jira readiness is explicit rather than inferred from status categories;
- custom/admin-edited link types cannot silently change dependency direction;
- local and cross-project blockers have deterministic identities and resolution semantics;
- asymmetric link reads cannot create a false READY result;
- provider metadata drift is visible and fail-closed;
- hierarchy remains distinct from dependency authority.

Tradeoffs:

- Jira policy requires explicit human configuration;
- projects with many non-scheduling link types must explicitly mark them `ignore` if they appear
  on tasks that ProjectCTL should schedule;
- cross-project blockers add targeted provider reads;
- Jira remains non-executable until safe lifecycle mutation semantics are proven.

## Rejected alternatives

### Infer READY from Jira status category alone

Rejected because provider workflow grouping is not execution intent.

### Infer blocker direction from link type name

Rejected because Jira link types are configurable and inward/outward labels define displayed
semantics.

### Ignore unknown link types automatically

Rejected because a custom link could represent a scheduling dependency.

### Trust embedded external blocker status

Rejected because scheduler release requires a current read of the external blocker, not a possibly
stale linked-issue projection.

### Treat parent/sub-task as dependency

Rejected because hierarchy and blocking semantics are independent authorities.

## Follow-up

The next Jira milestone should first review current Jira issue-property and workflow-transition
concurrency semantics before freezing an execution/lifecycle design.

A future lifecycle design must remain additive, avoid overwriting native human workflow state, bind
durable completion evidence, and fail closed across every crash/concurrency window.
