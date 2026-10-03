# ADR-007: M1 Production Hardening Before Autonomous Orchestration

Status: Accepted

## Context

The completed M1 flow has durable run state, isolated worktrees, bounded Codex execution, independent verification, evidence, integration, and recovery.

An end-to-end architecture review before M2 found four cross-cutting lifecycle hazards that are not visible in isolated milestone tests:

1. Long worker or verification operations can exceed the five-minute run lease TTL.
2. Per-run leases do not serialize two different runs mutating the same integration target.
3. Terminal run states can leave the canonical task claimed/in-progress.
4. File-existence project locks survive process crashes indefinitely.

These hazards become substantially more dangerous once an autonomous loop can start/recover multiple operations without a human between steps.

## Decision

### Lease heartbeat

Long synchronous worker and verification operations run inside a `LeaseHeartbeat`.

The heartbeat periodically renews the existing owner lease. If renewal fails, lease loss is treated as a stronger safety failure than the wrapped operation. The old owner must stop durable state mutation.

### Project-wide integration serialization

Integration acquires the existing run lease and a project-wide `integration` lock. The run lease protects run ownership; the project lock protects the shared Git target across different runs.

### Task/run reconciliation

ProjectCTL treats canonical task state as part of run finalization:

- `FAILED`, `CANCELLED`, `ABANDONED` release the task for a future retry.
- `NEEDS_DECISION`, `BLOCKED_POLICY` clear worker assignment and block the task.
- `PASSED` remains closed only after verified integration, as defined by M1.4.

A reconciliation failure changes the run to `NEEDS_DECISION / RECOVERY_UNSAFE`. Silent task-store drift is not accepted.

Recovery invokes the same reconciliation rule for terminal runs so older partial failures can be repaired.

### Crash-safe project locks

Project lock files contain:
- PID
- hostname
- unique ownership token
- acquisition timestamp

A lock can be reclaimed only when it is valid metadata, belongs to the same host, and its PID is no longer alive. Ambiguous or remote-host ownership is fail-closed.

Lock release removes the file only when the token still matches the current owner.

## Consequences

- a five-minute TTL no longer makes long worker turns recoverable by a competing process while they are still alive
- two verified runs cannot concurrently mutate one primary target worktree
- terminal failures no longer permanently strand Beads tasks as running
- a process crash no longer permanently bricks ProjectCTL project-level operations
- M2 can build an autonomous loop on top of explicit ownership rather than timing assumptions
