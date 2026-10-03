# ADR-006: Fast-Forward Integration and Deterministic Recovery

Status: Accepted

## Context

M1.3 produces a verified candidate commit and evidence bound to an exact execution base and exact candidate diff. Integration must not silently transform that artifact after verification.

The integration workflow also crosses multiple durable systems: Git, the canonical task authority, ProjectCTL run state, and disposable worktrees. A process crash can happen between any two mutations.

## Decision

M1.4 permits only fast-forward integration of a verified candidate onto the exact recorded base.

If the integration target has advanced since verification, ProjectCTL does not rebase, cherry-pick, or create a merge commit automatically. The run transitions to `NEEDS_DECISION / STALE_BASE`. A new execution/verification cycle is required for the new base.

The primary worktree must:
- be clean
- have the recorded target branch checked out
- resolve the target to either the verified base or, during recovery, the verified candidate

Before mutating Git, ProjectCTL revalidates the Evidence chain:
- Evidence must pass
- candidate must match durable Run state
- WorkerResult digest must match Evidence
- VerificationManifest digest must match Evidence
- verification-profile digest must match
- candidate must be a direct single-parent child of the verified base
- actual binary diff digest must match Evidence
- verified worktree must be clean and at candidate HEAD

Integration order is:
1. transition `READY_TO_INTEGRATE -> INTEGRATING`
2. `git merge --ff-only <candidate>`
3. close the canonical task with an EvidenceReference
4. persist IntegrationManifest v1
5. transition `INTEGRATING -> PASSED`
6. remove the ProjectCTL worktree and run branch

M1.4 performs no push.

Task completion is idempotent. For Beads, an already-closed task is treated as complete.

Recovery is based only on durable observable state. It never assumes an unavailable worker can be resumed.

Safe reconciliation cases include:
- RUNNING + durable implemented WorkerResult + unchanged base HEAD -> VERIFYING
- VERIFYING + passing Evidence + candidate HEAD -> READY_TO_INTEGRATE
- INTEGRATING + target still at base -> READY_TO_INTEGRATE
- INTEGRATING + target at candidate -> finalize task, PASSED, cleanup
- PASSED + residual worktree -> cleanup

A RUNNING execution with no trustworthy durable WorkerResult becomes `NEEDS_DECISION / RECOVERY_UNSAFE`.

Recovery never steals an unexpired lease.

## Consequences

- verified evidence is never invalidated by an automatic rebase
- partial integration is recoverable without duplicate code integration
- task closure happens only after Git integration is observed
- cleanup failure does not undo an already integrated/passed run
- M1 completes a local autonomous execution loop while remote push and broader team integration remain separate future concerns
