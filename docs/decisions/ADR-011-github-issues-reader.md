# ADR-011: GitHub Issues Reader and Authority Discovery

Status: Accepted

## Context

ProjectCTL's broader M3 direction is integration with team/project-management systems such
as GitHub, Linear, and Jira. The existing execution path assumes Beads is the canonical
task authority whenever it needs to claim, release, block, or complete a task.

Brownfield inspection already recognizes GitHub Issues as a possible task system, but
before M3.0a selecting `task_store.provider: github` produced a configured provider with
no runtime adapter.

GitHub Issues is not a drop-in replacement for Beads mutation semantics. In particular,
ordinary labels and assignees do not provide a documented compare-and-swap primitive for
a distributed ProjectCTL claim. Enabling execution writes without an explicit concurrency
protocol could allow two runners to believe they own the same task.

## Decision

M3.0a adds a **read-only GitHub Issues task-store adapter** and authority discovery.

### Runtime boundary

ProjectCTL uses the authenticated GitHub CLI `gh api` surface and pins
`--hostname github.com`.

ProjectCTL does not store GitHub tokens or implement a second credential store.
Authentication and host credentials remain owned by GitHub CLI.

The adapter is intentionally split into:

- repository identity parsing/inference
- a narrow GitHub Issues client
- normalization into ProjectCTL `NormalizedTask`
- application-level provider routing

### Repository identity

A GitHub task authority is pinned as `owner/repository`.

For brownfield adoption, ProjectCTL may infer this identity from a github.com `origin`
remote. Supported forms include HTTPS, SCP-style SSH, and `ssh://` GitHub URLs.

The origin remote is included in the adoption repository fingerprint. A remote change
between preview and apply therefore invalidates the adoption plan.

Explicit repository overrides remain possible through onboarding, but are validated as
exact `owner/repository` identities. Repository overrides are rejected for non-GitHub
task stores.

### Contract versioning

Adding repository identity changes persisted/public onboarding and project configuration
contracts, so M3.0a does not mutate v1 schemas in place.

- `ProjectConfig v1` remains readable; the loader upgrades it to v2 in memory without
  rewriting the existing file.
- new ProjectCTL configs are `ProjectConfig v2`
- `ProjectInspection v1`, `AdoptionPlan v1`, and `AdoptionManifest v1` remain
  exported for audit compatibility
- current onboarding artifacts use v2 and add repository identity fields

### Read semantics

M3.0a reads GitHub Issues through the REST issue endpoint and filters pull requests out of
the result.

Normalized task IDs use `gh-<issue-number>`. The original issue number remains available
as `TaskSource.external_id`, and the issue URL is retained as `external_url`.

Open issues are READY by default unless explicit ProjectCTL lifecycle labels say
otherwise. Closed issues normalize to DONE, except `state_reason=not_planned`, which
normalizes to CANCELLED.

### Metadata convention

The adapter recognizes:

- `projectctl:planned`
- `projectctl:running`
- `projectctl:blocked`
- `projectctl:needs-decision`
- `type:<task-type>`
- `priority:p0..p4`
- `resource:<resource-class>`
- `risk:<risk-level>`
- `info-gain:0..5`
- `milestone:<value>`

GitHub's native milestone title is also understood. If the native milestone and explicit
milestone label disagree, milestone scoring is disabled for that issue.

Common GitHub labels `bug`, `enhancement`, `documentation`, and `security` are used
as type fallbacks only when there is no explicit `type:` label.

Conflicting ProjectCTL scheduling metadata fails closed: the issue becomes
`NEEDS_DECISION` and is not automatically eligible.

M3.0a does not infer dependency edges from issue prose.

### Read-only execution boundary

GitHub-backed projects may use:

- `projectctl tasks`
- status/dashboard reads
- scheduler evaluation
- `projectctl next` / `explain-next`

They may not prepare an execution run yet.

`projectctl run prepare` checks task-store execution capability before creating any run
record, claim, lease, branch, or worktree. For a GitHub authority in M3.0a it fails with an
explicit read-only error.

Spec Kit import also refuses to create Beads tasks when GitHub is configured, preserving
the single-authority rule.

### Doctor behavior

`projectctl doctor` requires:

- GitHub CLI in PATH
- a valid `owner/repository` identity
- readable repository metadata through the authenticated CLI

A healthy GitHub reader is reported as a warning rather than full pass because remote
mutation/claim support is intentionally unavailable in M3.0a.

## Consequences

M3.0a gives ProjectCTL a real external team-task reader without pretending that GitHub
provides Beads-equivalent execution locking.

M3.0b must define and test a concurrency-safe GitHub mutation protocol before enabling:

- claim
- release/retry
- needs-decision transitions
- verified completion
- autonomous execution against GitHub Issues

The same separation between read normalization and write authority should be reused by
future Linear/Jira adapters.
