# ADR-004: Deterministic Context and Stable Codex Worker Surface

Status: Accepted

## Context

M1.2a models Codex features but does not run a worker. M1.2b must execute code without allowing provider defaults, repository content, or experimental APIs to silently change ProjectCTL's authority model.

The documented high-level Codex Python SDK currently exposes persistent threads, Default turns, sandbox overrides, approval overrides, structured output, ExternalMessage, and thread resume. Native Plan collaboration mode is an experimental app-server turn field. Goal lifecycle operations exist in the lower-level client/runtime surface and are not part of the documented high-level Thread API.

## Decision

M1.2b implements a stable-surface `CodexWorkerAdapter` using the documented high-level Python SDK.

The adapter explicitly sets:

- approval: `deny_all`
- sandbox: `read_only` or `workspace_write`
- workspace-write network access: disabled
- persistent thread: enabled
- structured final output: required
- cwd: the isolated ProjectCTL worktree

The task request is sent as Codex `ExternalMessage` content so repository/task/spec text remains below developer authority. ProjectCTL execution restrictions are provided as developer instructions.

Native Plan and Goal are not emulated with ordinary prompts. They remain represented in `WorkerCapabilities`, but the stable M1.2b adapter reports them as adapter-unsupported. A future dedicated bridge may enable them after protocol-specific tests and policy enforcement exist.

ExecutionPlan moves to schema v2 because capability and strategy digests are now execution inputs. ExecutionPlan v1 remains readable. WorkerRequest similarly moves to v2 while v1 remains readable.

Capability comparison uses an execution-semantic digest. Observation timestamps, probe labels, and human-readable notes do not create false drift; runtime/SDK/adapter versions and effective support states do.

Context assembly is path-based:

- applicable AGENTS files are discovered and scoped
- configured knowledge bindings are recorded by path and digest
- task references are recorded by path and digest
- configured source content is not dumped wholesale into the worker prompt

Before a worker starts, ProjectCTL live-probes Codex and compares the effective capability digest with the prepared plan. Drift fails closed with `needs_decision / capability_changed`.

After the worker returns, ProjectCTL compares Git HEAD with the pre-worker commit. Hidden worker history mutation fails the run with `unexpected_git_history`.

A structured worker result is not verification evidence. `implemented` transitions only to `verifying`; M1.3 owns independent verification.

## Consequences

- the first real Codex execution path is available without weakening the ProjectCTL authority model
- provider/task content cannot authorize broader permissions
- context is auditable without prompt bloat
- experimental Plan/Goal surfaces are visible instead of silently approximated
- capability changes between prepare and start are explicit operational events
- worker self-report remains separated from evidence-driven completion
