# ADR-012: Provider-neutral Task Authority Capability Layer

Status: Accepted

## Context

M3.0a added a real GitHub Issues reader, but the execution application layer still contained
historical Beads-specific imports and provider branches for claim, release, decision blocking, and
completion.

That structure was acceptable while Beads was the only executable task authority, but extending it
directly for GitHub, Linear, or Jira would duplicate lifecycle policy in application services and
make provider capability assumptions implicit.

The architecture review also identified two separate GitHub concerns that must not be collapsed
into one mutation milestone:

1. GitHub issue/label/assignee updates do not provide ProjectCTL a documented compare-and-swap
   claim primitive.
2. M1.4 performs local fast-forward integration but deliberately performs no push, so closing a
   remote GitHub issue immediately after local integration would allow remote task state to report
   completion before the verified code is team-visible.

## Decision

M3.0b1 introduces a provider-neutral Task Authority capability and resolver layer.

### Ports remain the lifecycle boundary

The existing ports remain authoritative:

- `TaskStoreReader`
- `TaskClaimer`
- `TaskCompletionWriter`

`TaskStoreReader` now explicitly includes deterministic `snapshot(...)` generation because
application scheduling already relies on that behavior.

### TaskAuthorityCapabilities v1

ProjectCTL exposes one versioned capability artifact describing adapter-supported lifecycle
operations:

- read
- claim
- release
- block_for_decision
- complete

Capability inspection is static with respect to adapter support. It must not require the provider
runtime to be installed or authenticated.

This mirrors the existing worker principle: provider/runtime availability and ProjectCTL adapter
support are different facts.

### Resolver

A single Task Authority resolver owns provider construction.

Application services obtain readers/writers/claimers through this resolver and must not import
Beads, GitHub, Linear, Jira, or future task-provider implementations directly.

An architecture test enforces this import boundary for `projectctl/application/*.py`.

### Current capabilities

Beads:

- read: supported
- claim: supported
- release: supported
- block_for_decision: supported
- complete: supported

GitHub:

- read: supported
- claim: unsupported
- release: unsupported
- block_for_decision: unsupported
- complete: unsupported

GitHub therefore remains non-executable after M3.0b1.

### Execution gate

Preparing a run requires the configured Task Authority to support the complete lifecycle needed by
the current execution pipeline.

Unsupported task authorities fail before a RunRecord, lease, claim, branch, or worktree is created.

### Architecture document

`docs/PROJECTCTL_BLUEPRINT.md` becomes the canonical high-level architecture/roadmap reference.

It is human-managed and worker-protected, while:

- `docs/PROJECT_STATE.yaml` remains the only active-milestone authority
- ADRs remain the authority for individual architecture decisions
- README remains user-facing documentation

## Consequences

Positive:

- application lifecycle code is provider-neutral
- future task providers extend one resolver instead of branching throughout application services
- capability inspection is explicit and machine-readable
- GitHub read support cannot accidentally imply execution support
- M3.0b2 can focus narrowly on claim ownership semantics
- remote publication can remain a separate completion concern

Tradeoffs:

- one additional abstraction exists between application services and provider adapters
- GitHub remains read-only for execution even though some individual write APIs are technically
  available
- full remote task execution requires more than merely implementing issue update calls

## Follow-up

M3.0b2 must validate and implement a real GitHub claim ownership primitive before enabling claim or
release capability.

The current leading design candidate is a deterministic reserved remote Git reference whose create
operation has create-or-conflict semantics. This is a candidate, not an implemented guarantee, and
must be tested against GitHub permissions, recovery, cleanup, and stale-claim behavior.

M3.0c must define remote publication semantics before GitHub `complete` can become supported.
