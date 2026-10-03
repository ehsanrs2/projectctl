# ADR-010: Budget-aware Checkpointing and Graceful Quota Stop

Status: Accepted

## Context

M2.1 gives ProjectCTL an authoritative account-global Codex quota observation path, but
M2.0 still checks quota mainly between tasks. A long worker turn can therefore cross a
budget boundary after scheduling has already admitted it.

Stopping a worker process abruptly is not acceptable. It can lose the provider thread,
leave partially edited files without a resumable identity, and turn a quota event into a
recovery incident.

The pinned Codex Python SDK exposes supported turn controls:

- \`Thread.turn(...)\`
- \`TurnHandle.interrupt()\`
- \`Codex.thread_resume(...)\`

ProjectCTL already has durable run checkpoint columns, isolated worktrees, run leases, and
a WorkerCheckpoint schema boundary.

## Decision

M2.2 makes direct/review Codex execution checkpoint-aware.

### Checkpoint trigger

While a worker turn is active, ProjectCTL periodically obtains a fresh account quota
snapshot. It requests a checkpoint when any of these becomes true:

- the quota snapshot is stale
- ordinary usage is explicitly denied or quota mode is critical
- the remaining effective budget no longer satisfies the current task's resource class

Conservation mode by itself is not a checkpoint trigger. A small task may continue when
its existing resource requirement is still satisfied.

### Safe interruption

Checkpoint-aware execution uses \`Thread.turn(...)\` and the public
\`TurnHandle.interrupt()\` method. ProjectCTL does not kill Codex or emulate interruption
with a prompt.

If the turn completes naturally during an interrupt race, the completed result wins.

### Durable checkpoint

A successful quota interruption writes WorkerCheckpoint v2 containing:

- run/task/worktree identity
- Codex thread and turn identity
- original context manifest digest
- checkpoint reason
- complete quota snapshot and its digest
- quota mode/staleness
- exact partial-workspace digest
- checkpoint time

The run remains \`RUNNING\`, keeps its canonical task claim, releases its process lease,
and records the checkpoint path in durable run state.

The worker may modify files before checkpointing but may never change Git HEAD/history.

### Workspace continuity

A checkpoint is resumable only if:

- the execution plan still matches
- the worktree still exists at the original base commit
- the durable checkpoint identity matches the run
- the quota snapshot payload matches its recorded digest
- the current worktree state matches the checkpoint workspace digest
- the original context/request digests still match
- the live worker capability/strategy surface is still compatible

External edits to the partial worktree after checkpointing fail closed as
\`RECOVERY_UNSAFE\`.

### Resume gate

\`projectctl run resume RUN_ID\` reads fresh quota before contacting Codex. Resume is
deferred when quota is stale or insufficient for the task's resource class.

When eligible, ProjectCTL calls \`thread_resume\` with the original Codex thread id and
continues the same authorized task from the preserved worktree. A resumed turn can finish
or checkpoint again.

### Autonomous behavior

The M2 auto loop recognizes a durable checkpoint as a planned stop:

- if quota permits, an expired-lease checkpointed run is resumed before new work
- if quota still does not permit resume, the loop stops with
  \`quota_checkpointed\`
- a new checkpoint produced during autonomous execution also stops with
  \`quota_checkpointed\`

This stop is graceful, not a worker failure or human-decision state.

### Recovery

Crash recovery recognizes intact WorkerCheckpoint v2 artifacts as
\`checkpoint_resume_ready\`. A checkpoint with a missing artifact, mismatched identity,
changed Git history, or changed workspace escalates fail-closed.

Legacy WorkerCheckpoint v1 remains schema-readable for audit but is not automatically
resumable because it lacks the M2.2 continuity evidence.

### Explicit abort

A checkpointed RUNNING run can be explicitly aborted. ProjectCTL removes its isolated
worktree, releases the task claim, records cancellation, and clears the active checkpoint
pointer.

### Quota preflight correction

Execution preflight now re-evaluates live quota semantically rather than requiring exact
QuotaSnapshot digest equality. Official snapshots have a fresh observation timestamp on
each read, so exact snapshot identity is not a valid staleness test.

### Scope boundary

M2.2 does not predict per-task token cost, checkpoint arbitrary providers without a
supported interrupt/resume surface, or remove the M2 bounded task limit.
