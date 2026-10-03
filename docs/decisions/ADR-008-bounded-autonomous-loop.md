# ADR-008: Bounded Autonomous Loop

Status: Accepted

## Context

M1 now provides independently testable lifecycle operations for scheduling, task claiming, isolated worktree execution, Codex strategy negotiation, verification, evidence, fast-forward integration, recovery, lease heartbeats, task reconciliation, and crash-safe locks.

M2 must compose those operations without turning ProjectCTL into an opaque agent or weakening the authority boundaries established by M1.

A naive `while True` around the M1 functions would be unsafe because it could:
- start new work while a recoverable run already exists
- continue after human-decision or policy boundaries
- reuse stale scheduler/quota/project-state snapshots
- repeatedly retry deterministic failures
- consume an unbounded amount of model quota
- continue after the human changes project intent

## Decision

M2.0 introduces a bounded, synchronous autonomous orchestrator.

### Bound

Each invocation has an explicit `max_tasks` attempt cap. The CLI default is one. There is no unbounded daemon loop in M2.0.

### Recovery first

Before scheduling new work, the orchestrator inspects active durable runs.

- more than one active run: stop fail-closed
- active unexpired lease: stop; do not compete
- RUNNING/INTEGRATING with expired lease: invoke deterministic recovery
- CLAIMED: resume worker start
- VERIFYING: resume verification
- READY_TO_INTEGRATE: resume integration
- PLANNED/PREPARING crash state: stop as recovery-required because M2.0 cannot prove the partial prepare side effects

### Fresh decision input per iteration

Every new task iteration calls the existing status/scheduler pipeline again, obtaining fresh:
- Project State
- TaskSnapshot
- QuotaSnapshot
- SchedulerDecision

No scheduler decision is reused across task boundaries.

### Quota policy

Autonomous mode stops by default when the quota snapshot is stale or the quota mode is critical.

The current provider remains `ManualQuotaProvider`. M2.0 therefore does not fabricate token/time usage estimates. The explicit task cap remains part of the safety boundary until automatic quota accounting is implemented.

### Retry policy

Only failures classified as transient/control-plane retry candidates are eligible:
- infrastructure error
- timeout
- worker error
- claim lost
- stale base
- context invalid

Retries are bounded by `max_attempts_per_task`.

Verification failure, policy block, unexpected Git history, cancellation, recovery-unsafe state, and human-decision states stop the loop.

### Material project-state change

The Project State digest is captured before a task and read again after the lifecycle completes. If it changes, autonomous continuation stops by default.

This treats a human change to current goal/milestone as an intent boundary. The completed task is not rolled back; the next autonomous invocation replans from the new state.

### Audit

Each invocation writes `AutoRunReport v1` to `.projectctl/auto/<auto-run-id>.json`. The report records every autonomous step and the typed stop reason.

### Serialization

The entire autonomous invocation acquires the crash-safe project lock `auto-loop`. Existing run leases and the M1 integration lock remain independently enforced.

## Consequences

- M2 composes existing deterministic services instead of duplicating their logic
- autonomous execution is finite by construction
- unfinished work is handled before new work
- human-decision and policy boundaries remain authoritative
- scheduler/quota/project intent are refreshed between tasks
- a future M2.1 quota-accounting layer can replace the current manual limitation without changing the loop contract
