# ADR-005: Independent Verification, Evidence, and Candidate Commits

Status: Accepted

## Context

M1.2b can execute a bounded Codex worker and returns a structured WorkerResult. Worker self-report is not sufficient evidence that the implementation is correct, policy-compliant, or safe to integrate.

Verification must also avoid a second authority inversion: a worker must not be allowed to choose the commands that prove its own work correct.

## Decision

M1.3 introduces a deterministic verification control plane.

Verification commands come from the human-managed `projectctl.verification.yaml` catalog or a narrow deterministic built-in resolver. `WorkerResult.suggested_verification` is advisory only.

Verification has three independent gates:

1. Diff / ownership policy
2. Configured verification commands
3. Workspace stability

The diff gate inspects tracked, staged, deleted, and untracked changes. System-protected paths cannot be modified by a worker even if a verification profile omits them. These include ProjectCTL operational state, evidence/generated output, AGENTS instructions, Project State, specs, architecture decisions, and the verification catalog.

Symlink changes are denied by default and escaping symlinks are always reported.

Verification commands are argv arrays and are executed with `shell=False`. Each command has a timeout. Stdout/stderr is written to run-local log files and represented in the manifest by content digest.

ProjectCTL compares the workspace state and HEAD before and after verification commands. Required command failure, timeout, policy violation, or tracked workspace mutation prevents candidate creation.

A worker remains forbidden from committing. After all verification gates pass, ProjectCTL itself stages the verified changes and creates one candidate commit with exactly the execution base as its parent. Git hooks and commit signing are disabled for this control-plane commit.

`VerificationManifest` advances to schema v2. V1 remains readable. V2 records base commit, verification-profile digest, changed paths, policy violations, and the full check result set.

`EvidenceManifest` advances to schema v2. V1 remains readable. V2 records workspace/diff digests and verification-profile digest and permits a null candidate commit for failed or policy-blocked evidence.

Passing implementation runs transition to `READY_TO_INTEGRATE`. M1.3 does not merge, push, or close the task. Those responsibilities remain M1.4.

Review-mode runs are non-mutating. A review run that remains clean and passes its configured checks may transition directly to `PASSED`, using the base commit as its candidate reference.

## Consequences

- Worker confidence is no longer a completion signal.
- Worker-proposed tests cannot become authoritative automatically.
- Accepted and rejected runs are both auditable.
- Candidate commits are created only from a verified, stable workspace.
- Integration remains a separate authority boundary.
