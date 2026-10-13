# ADR-039: Read-only Execution Trace & Evaluation Export

**Status: Accepted — 2026-10-13 (effective upon merge of the ADR-039 acceptance PR). This accepts a bounded design, not an implemented collector, passing CI or a release.**
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

## Accepted design decisions (implementation remains gated)

### 1. An explicitly non-authoritative derived artifact

`ExecutionTraceBundle v1` has been introduced in Slice A with schema kind
`projectctl.execution_trace_bundle`. It is a **deterministic local export**
derived from a bounded set of existing run artifacts. It is never an input to
run admission, human scope approval, scheduler eligibility, worker permission,
quota calculation, verification, integration or delivery.

The bundle should include, subject to redaction:

- export contract version and *source* project/run identity;
- ordered source descriptors: allowlisted artifact kind, historical schema
  version where known, content SHA-256 and validation state. Raw source
  filename/path is **not** a v1 output field;
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

- Read authoritative SQLite run data through a **dedicated**, tested,
  read-only connection rather than existing `RunStore.get/manifest/events`
  convenience readers, which use a potentially side-effecting connection.
  Read only fixed whitelisted artifacts; do not create a writable run store
  or mutate any historical manifest.
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

### 4. Accepted initial CLI shape (not implemented)

Planned bounded form, executable only after Slice B test acceptance:

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

## Accepted detailed boundaries for Slice B

These constraints were reviewed as the initial read-only execution trace
design in `docs/architecture/M6_0_SLICE_B_SNAPSHOT_SECURITY_SPEC.md`. They
do not imply that the SQLite/filesystem safety properties have already been
demonstrated by an operational collector.

### Snapshot and no-mutation invariant

- Use a separate, pre-existing SQLite `.projectctl/state.sqlite`
  connection in `mode=ro` with `query_only=ON`, validated application ID and
  DB version, and a bounded **single read transaction** for the run record,
  stored run manifest and ordered event metadata. Select by bound run ID.
- **Do not call** ProjectCTL's existing `connect_db` for export: it creates
  directories and sets WAL journal mode. Do not initialize, migrate, repair
  or attach databases, or acquire an execution/claim/verification lock.
- Reading SQLite WAL can create or interact with sidecar files. Before
  enabling a collector, test cold DB, active WAL, absent sidecars and
  concurrent writers, and establish that no ProjectCTL operation state or
  database/sidecar content is modified. Do **not** apply `immutable=1` to
  live WAL state to bypass the safety check. On unsupported environments,
  **fail closed**.
- A read transaction protects DB consistency, **not** an atomic snapshot
  across the DB and separately persisted files. A bounded pre/post source
  identity check and at most one retry are allowed; changed or unverifiable
  observations must become typed `inconsistent_snapshot` or a safe refusal.
  `PRAGMA data_version` alone is insufficient proof.

### Source allowlist and historical identity

- Database source kinds are exclusively the selected `runs` row,
  `runs.manifest_json` and ordered `run_events` for that same run ID.
  Never read/export the `run_events.payload_json` field.
- File source kinds use **only** the explicitly listed leaf names under
  `.projectctl/runs/<validated_run_id>/`; no recursive search, absolute
  payload-derived references or symlink traversal. For POSIX, use
  directory-relative no-follow descriptor reads and `fstat` checks;
  platforms without comparable guarantees fail closed.
- Initial hard limits: **2 MiB per artifact** and **512 events**. Exceeding
  bounds must fail safely or show explicit incompleteness; no silent
  truncation and no leakage of raw error messages.
- Deserialize each known historical schema with its **matching versioned
  model**. Unknown versions must be marked `unsupported`, never coerced to
  `present`. Do not trust the presence of a file as proof that its
  `run_id`/`task_id` or parent-digest lineage matches the database.
- Missing future-phase artifacts are expected for partial runs; their
  absence is not automatically an inconsistency or a failed verification.

### Local privacy decision and deliberate limits

- The initial **local-only** output may expose bounded `project_id`,
  `run_id` and artifact SHA-256 identities so an operator can reconcile
  it with the local run. This is an explicit **non-anonymous** design choice:
  identities and content digests can facilitate correlation and should not
  be redistributed casually.
- Omit raw prompts, stdout/stderr, worker/provider messages, event payloads,
  task IDs, review URLs, paths, lease ownership, environment variables and
  arbitrary free-form failure strings. Event categories come only from the
  exact allowlist in `projectctl/trace/format.py`.
- Default output goes to stdout only. Any file destination must be an
  explicit safe no-clobber operator choice **outside protected authority
  paths**. No network transfer, cloud API or automatic telemetry.
- Optional pseudonymization, remote sharing or raw/sensitive export needs
  a **new explicit security decision**, not a silent extension of this ADR.

### Evidence support boundary

- Slice B **always emits `assessments=[]`**. `observed_run_status`
  remains an observation, even if it equals `passed`.
- A `present` source or structurally valid v1 `ExecutionTraceBundle`
  does **not** by itself prove raw-byte identity, semantic digest,
  verification independence or delivery. Collectors must downgrade
  unverifiable evidence, never manufacture a `supported` assessment.
- Deterministic UTF-8 JSON uses sorted keys, UTC timestamps, stable
  source/event order and one trailing newline. No generated export-time
  timestamp or host-specific paths.

### Implementation gate and scope of acceptance

Acceptance of this **architecture decision** allows a separate Slice B
implementation PR to be developed and tested. It does not approve its
merge or claim a complete, side-effect-free collector until the safety
tests below pass on supported systems. Unsupported filesystems or SQLite
WAL modes must fail closed instead of weakening the non-mutation contract.

## Acceptance criteria

No M6.0 exporter is accepted before tests show: identical-source
reproducibility; no state mutations or Worker start; canonical/historical
parsing; corrupt and missing evidence semantics; concurrent-modification
behavior; redaction of secret-bearing fixtures; symlink/path traversal
rejection; cross-project isolation; schema-export compatibility; JSON CLI
roundtrip; and no false `verified` state from Worker-only claims.

## Decision outcome and provenance

**ADR-039 accepted as the bounded design** on merge of the acceptance PR,
following merged Slice A PR #54, Slice B0 PR #55 and operator-reported
passing local targeted/full-suite tests. The PR #55 whitespace issue was
corrected before its merge.

This decision selects the initial local, non-anonymous identity disclosure
and read-only snapshot contract **subject to the explicit fail-closed
implementation tests**. A collector, CLI command and live-source lineage
evaluation have **not** been implemented or accepted. The package remains
at version `0.41.0`; no tag or release is implied.

GitHub Actions hosted CI remains unavailable following the owner's
exhausted-quota report. Its failure records must not be relabeled as green;
rerun tests when quota returns. `docs/PROJECT_STATE.yaml` continues to
identify M6.0 as the active milestone.

See `docs/architecture/M6_0_TRACE_CONTRACT_V1.md`,
`docs/architecture/M6_0_SLICE_B_SNAPSHOT_SECURITY_SPEC.md` and
`docs/architecture/M6_0_IMPLEMENTATION_PLAN.md`.
