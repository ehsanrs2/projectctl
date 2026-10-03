# ADR-002: Claims, Run State, and Isolated Worktrees

Status: Accepted

## Context

M1.0 defines the execution contracts but does not hold task claims or create execution workspaces. M1.1 must survive process crashes, reject duplicate local runs, coordinate with the canonical task authority, and guarantee that worker changes cannot land in the user's primary worktree by accident.

## Decision

Beads remains the task execution-state authority when configured. ProjectCTL uses Beads' atomic claim operation before execution and releases a prepared claim by clearing the assignee and reopening the task.

ProjectCTL also keeps operational run state in the project-local state database. This is not a second task authority. The run store records lifecycle, lease, worktree, worker identifiers, checkpoints, and append-only run events required for recovery.

The project state database moves from schema version 1 to version 2. Existing databases are never silently upgraded on read or init. The user must run `projectctl migrate`. Migration creates a consistent SQLite backup before changing the database.

Only one active local run may exist for a task. SQLite enforces this with a partial unique index over active run states.

Each run uses a dedicated Git branch named `projectctl/run/<run-id>`. The corresponding worktree is created outside the repository under `$PROJECTCTL_HOME/worktrees/<project-instance-id>/<run-id>/`.

The run is pinned to the exact `ExecutionPlan.base_commit`. Preparing a run requires a clean primary worktree. ProjectCTL revalidates task, project state, quota snapshot, and target Git commit before claiming.

If worktree creation fails after a successful claim, ProjectCTL compensates by releasing the task. If compensation itself fails, the run becomes `needs_decision` with `recovery_unsafe`.

M1.1 exposes preparation and abort operations only. No worker is started.

## Consequences

- task coordination remains atomic at the canonical task store
- local crash recovery has durable run/lease state
- worker filesystem changes are isolated from the primary checkout
- database upgrades become explicit and auditable
- preparing a run is intentionally conservative when the repository is dirty
- stale or partially compensated runs are visible instead of being silently retried
