# ADR-001: ProjectCTL Owns the Execution Boundary

Status: Accepted

## Context

M0.5 can deterministically select a task and recommend a model/reasoning profile, but it does not execute code. M1 introduces autonomous execution. Directly connecting a scheduler decision to a worker would let provider-specific behavior, permission escalation, Git mutations, and self-reported verification become implicit authorities.

ProjectCTL requires reproducible execution, fail-closed permissions, evidence-driven completion, crash recovery, and a provider-agnostic worker boundary.

## Decision

ProjectCTL inserts an immutable `ExecutionPlan` between scheduling and execution.

The control plane owns:

- preflight revalidation
- task claiming
- execution policy
- worktree lifecycle
- Git history mutations
- deterministic verification
- evidence generation
- integration
- task completion

Workers receive a bounded `WorkerRequest` and return a structured `WorkerResult`. Worker output is not authoritative for changed files, test success, Git state, or task completion.

The default execution policy is:

- sandbox: `workspace_write`
- network: disabled
- approval: `deny_all`
- worker commit/merge/rebase/push: forbidden

A worker may request additional capability, but the request becomes policy evidence; it does not grant itself permission.

Run checkpoints are events/properties, not lifecycle states. Run lifecycle and terminal reasons are explicit and versioned.

Legacy `RunManifest v1` and `ContextManifest v1` remain readable. M1 uses version 2 contracts.

Verification commands are represented as argv arrays and come from trusted ProjectCTL configuration. A worker may suggest additional checks but cannot weaken required verification or cause arbitrary shell strings to be executed as verification.

A task is not DONE when the worker reports completion. Completion requires candidate verification, integration, post-integration verification, evidence, and then the TaskStore completion write.

## Consequences

Positive:

- provider-specific worker behavior stays behind an adapter
- execution is reconstructible from immutable inputs
- permissions and Git operations have one authority
- recovery can reason about run state without trusting worker narration
- M2 automation can reuse the same execution contracts

Tradeoffs:

- M1 has more artifacts and state transitions than a direct agent loop
- ProjectConfig will require an explicit future schema migration before execution/verification policy becomes configurable
- integration remains conservative until later milestones add rebase/conflict automation
