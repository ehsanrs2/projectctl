# ADR-039: Read-only Execution Trace & Evaluation Export

**Status: Proposed — M6.0 architecture candidate; not accepted or implemented**  
**Milestone:** M6.0 — Read-only Trace & Evaluation Export  
**Precondition:** Accepted M5.2b execution-scope architecture (ADR-038)  
**Decision scope:** A derived local observability/export contract, **not** run authority

## Context

ProjectCTL already persists authoritative run and review evidence in several
independent artifacts: `RunStore` / `RunManifest v2`, versioned
`ExecutionInputManifest` (v1 and v2), `ClaimTransitionEvidence`,
`ContextManifest`, `VerificationManifest`, `EvidenceManifest`, and
delivery/integration receipts. These sources have different ownership,
historical versions, and validity boundaries. The operator needs to inspect
what happened to a run and why it was considered valid without granting an
observer the ability to alter its execution or invent missing evidence.

M6.0 must not create a new source of truth that overrides any of those
artifacts or treat worker-provided claims as independent verification.

## Proposed decisions for review

### 1. An explicitly non-authoritative derived artifact

Propose `ExecutionTraceBundle v1` with schema kind
`projectctl.execution_trace_bundle`. It is a **deterministic local export**
derived from a bounded set of existing run artifacts. It is never an input to
run admission, human scope approval, scheduler eligibility, worker permission,
quota calculation, verification, integration or delivery.

The bundle should include, subject to redaction:

- export contract version and *source* project/run identity;
- ordered source descriptors: artifact kind, historical schema version where
  known, relative reference (only if safe to disclose), content digest and
  validation state;
- run life-cycle status and structured, timestamped event categories;
- independent verification outcome **only if its artifact and identity
  lineage can be proven**;
- completeness and inconsistency findings with stable typed reason codes;
- policy/version provenance (including whether a manifest was historical)
  without copying sensitive execution inputs;
- deterministic evaluations restricted to metrics justified by surviving
  verified evidence, each marked `supported | unavailable | indeterminate`
  rather than treating missing information as failure or success.

`ExecutionTraceBundle` must not reuse the label `EvidenceManifest` for its
derived content; any exported digest identifies only the export, not a newly
granted authority.

### 2. Read-only source handling and provenance

- Read from existing `RunStore` read APIs and whitelisted, validated local
  artifacts. Do not duplicate a writable run store or mutate old manifests.
- Versioned historical readers must remain version-specific. Unknown schema
  versions become explicit `unsupported` evidence, not coerced into current
  models.
- Inspect source bytes once where possible, record the same-byte hash, and
  parse that snapshot. Preserve lineage distinctions between content digest,
  semantic digest, Git revision and external provider assertion.
- Verify artifact `run_id`/`task_id`, declared parent references and
  cross-artifact links before claiming an independently supported conclusion.
- Missing/stale/corrupt/unauthorized artifacts are recorded with safe,
  non-sensitive reason codes; no implied passing evaluation.
- Establish a bounded SQLite read transaction/snapshot strategy so a run
  changing during export cannot produce a falsely coherent mixed trace.
  Define a non-blocking retry/fail policy without acquiring execution locks.

### 3. Privacy and explicit export boundary

- Default export contains **no prompts, raw stdout/stderr, source files,
  worker messages, full provider payloads, secrets, token values, lease-owner
  identities or absolute worktree paths**.
- No arbitrary path reads, following artifact symlinks, network calls, remote
  uploads, or plugin/provider connections during export.
- Default destination: stdout, with optional explicit user-selected file
  outside mutable run authorities. No change to `.projectctl/` operation
  state, Git worktree, tasks or project scope policy.
- Output ordering and normalization deterministic for identical source
  snapshots. Wall-clock export timestamps, machine paths or local hostnames
  must not affect the deterministic bundle identity.
- Any future opt-in sensitive/raw export mode is a **separate security
  decision**, not implied by this ADR.

### 4. Proposed CLI, not yet public

Tentative bounded form:

```text
projectctl trace export --run RUN_ID --project PATH --format json
projectctl trace export --run RUN_ID --project PATH --format json --output FILE
```

The command should not execute, resume, claim, verify or repair the run.
Output file creation must be explicit, safe against traversal/symlink
replacement, and must not overwrite human-managed project policy or original
operational evidence. Machine-readable JSON output has a public schema
registry entry; CLI stdout remains suitable for scripting.

### 5. Conservative evaluation semantics

For v1, prefer observable facts: artifact presence, lineage consistency,
verification-check completeness, and the independently supported terminal
result. Do **not** implement a single arbitrary quality score or presume that
a `RunStatus.PASSED` alone proves correct delivery. A failed or indeterminate
trace must remain exportable for diagnosis without presenting its claims as
trusted. Separate **observed**, **derived**, **asserted**, and **verified**
statements.

## Rejected approaches

1. Exporting full `.projectctl/` or all event payloads: secrets/privacy risk.
2. Recomputing or overwriting historical run/evidence manifests: authority
   confusion, incompatible digests and audit destruction.
3. Asking a Worker/LLM to summarize a run and using its summary as truth:
   violates independent evidence boundaries.
4. Automatically exporting to cloud services or third-party analytics:
   changes the privacy and trust model without operator approval.
5. Adding new scoring to the scheduler or verifier as part of export:
   would grant the observer authority beyond the selected M6.0 scope.

## Open questions requiring acceptance before implementation

- Exact artifact locator/whitelist and secure root-relative path resolution.
- Consistent SQLite read snapshot plus file-snapshot strategy under
  concurrent writes; how to mark an export as `incomplete`.
- Exact `ExecutionTraceBundle v1` public field set, stable ordering and
  hash/version semantics.
- Per-field redaction allowlist and adversarial tests against accidental
  absolute-path, environment, provider payload and secret disclosure.
- Handling run histories with older missing/unsupported artifact versions.
- Output destination policy and explicit creation/overwrite semantics.
- What minimum independent evidence is sufficient for each proposed
  evaluation metric.

## Acceptance criteria

No M6.0 exporter is accepted before tests show: identical-source
reproducibility; no state mutations or Worker start; canonical/historical
parsing; corrupt and missing evidence semantics; concurrent-modification
behavior; redaction of secret-bearing fixtures; symlink/path traversal
rejection; cross-project isolation; schema-export compatibility; JSON CLI
roundtrip; and no false `verified` state from Worker-only claims.

**The selected M6.0 goal is accepted as a roadmap choice. This ADR remains
Proposed until its specific data, privacy and concurrency contracts are
reviewed.**
