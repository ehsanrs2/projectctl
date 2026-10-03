# ADR-003: Worker Capability Negotiation and Strategy

Status: Accepted

## Context

Codex exposes multiple execution surfaces: sandbox and approval policies, persistent threads, Plan collaboration mode, Goals, skills, structured output, and lower-level protocol capabilities. These capabilities evolve independently across Codex runtime, Python SDK, and ProjectCTL's own adapter.

Treating "Codex supports feature X" as equivalent to "ProjectCTL can safely use X" would create hidden compatibility and permission failures. It would also couple task scheduling to whatever Codex version happens to be installed on one machine.

## Decision

ProjectCTL models worker capability as two independent facts:

1. runtime/provider support
2. ProjectCTL adapter support

A capability is usable only when both are explicitly supported.

Capability snapshots are versioned artifacts and include SDK version, runtime version, ProjectCTL adapter version, probe kind, modes, permission mappings, thread capabilities, and feature notes.

M1.2a provides a version-only Codex probe. It does not start app-server. Capabilities requiring live protocol discovery remain `unknown` rather than being guessed. M1.2b may add a live read-only probe.

Execution strategy belongs to ExecutionPlanner, not Scheduler. Scheduler remains deterministic over project/task/quota inputs and does not change task ranking because of locally installed worker capabilities.

ProjectCTL defines four strategies:

- `direct`: Default mode with workspace-write
- `plan_then_execute`: Plan mode with read-only, followed by Default mode with workspace-write
- `goal`: Goal mode with workspace-write and a bounded Goal budget
- `review`: Default mode with read-only

Plan mode is never considered a security control. The invariant is:

`PLAN => READ_ONLY`

Goal mode does not imply network, full access, or permission escalation. Those remain separate policy decisions.

The current public Codex Python SDK approval modes `deny_all` and `auto_review` are mapped explicitly. ProjectCTL's provider-neutral `EXPLICIT` approval policy is not silently mapped to another Codex mode.

Strategy downgrade is fail-closed. Goal → Plan or Plan → Direct fallback requires explicit policy.

M1.2a does not alter `ExecutionPlan v1`. When M1.2b makes capability negotiation a live execution input, ExecutionPlan will receive an explicit version bump rather than silently changing the v1 contract.

## Consequences

- capability mismatches become inspectable instead of runtime surprises
- provider features cannot bypass ProjectCTL policy by merely existing
- scheduler decisions remain independent from local Codex installation details
- Plan and Goal can be adopted incrementally without hard-coding provider checks throughout the worker
- unsupported/experimental features remain visible but unusable until the adapter explicitly supports them
- a future provider can expose the same capability contract without copying Codex-specific logic
