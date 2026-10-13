# M6.0 — Read-only Trace & Evaluation Export: Bounded Implementation Plan

**Status: Slices A, B0, B1a, B1b and feasibility-only B2a merged after operator-reported local regression passes; ADR-039 Accepted. ADR-040 cross-store consistency design is Proposed, not implemented; no Collector/CLI or proven coherent live-WAL snapshot exists.**
**Active goal:** `docs/PROJECT_STATE.yaml` — M6.0
**Architecture decision:** ADR-039 (Accepted as bounded design on acceptance PR merge; implementation still gated)
**Inherited safety decisions:** ADR-037, ADR-038 (Accepted)

## Source inventory (verified in repository)

| Existing evidence | Read-only access point | M6.0 concern |
| --- | --- | --- |
| Run/event database | `.projectctl/state.sqlite` through a **new read-only** single-snapshot connection; do not reuse `RunStore.get/manifest/events` | No DB/sidecar mutations, WAL/concurrency, durable ordering |
| Current/historical run manifests | `projectctl/schemas/run.py` | Version-aware parsing and run identity |
| Execution/claim evidence | `projectctl/schemas/execution_input.py` | Original digest, policy source, claim lineage |
| Context manifest | `projectctl/schemas/run.py` | Resource/file references must be redacted |
| Verification outcome | `projectctl/schemas/verification.py` | Distinguish independent verification from worker report |
| Evidence manifest | `projectctl/schemas/evidence.py` | Version-specific validity, candidate and changed paths |
| Integration/delivery receipts | `projectctl/schemas/integration.py`, `delivery.py` | Completion evidence is separate from local pass |
| Public JSON schema registry | `projectctl/schema_export.py` | Additive new schema only; no generated schema mirror |
| CLI registration | `projectctl/cli/entry.py` | New read-only command; no runtime/mutation dependency |

## Implementation slices

### A. Explicit model, provenance rules and privacy threat model

1. Finalize ADR-039 and `ExecutionTraceBundle v1` shape and reason enums.
2. Enumerate allowed source artifact kinds and historical readers.
3. Specify consistent SQLite/file snapshots, source SHA-256, semantic
   hash distinction, deterministic ordering and missing/invalid states.
4. Approve a field-level allowlist. Exclude secrets, provider payloads,
   prompts, environment variables, stdout/stderr and machine-specific
   absolute paths by default.
5. Tests first: schema validation, historical samples, unknown versions,
   redaction, invalid source paths and stable serialization.

**Gate A:** the proposed `projectctl/schemas/trace.py` and `execution-trace-bundle.v1.schema.json` must be reviewed against `docs/architecture/M6_0_TRACE_CONTRACT_V1.md`; local tests, schema export, privacy and source-snapshot design decisions must pass before ADR-039 acceptance. No export CLI until this gate is accepted.

### B1 — Experimental read-only source snapshot primitives (Draft)

PR #57 merged B1a: a POSIX descriptor-anchored artifact reader and a
single-transaction SQLite `mode=ro` run snapshot for **quiescent
rollback-journal databases only**. Operator-reported local tests and patch
hygiene passed. Live WAL remains deliberately refused before SQLite
connects. The proposed B1b follow-up adds **pure versioned evidence parsing
and an always-incomplete, no-assessments Trace builder**, without a Collector
or CLI. Its parser registry now has tests for all nine allowlisted evidence
families and rejects JSON exponent-overflow Infinity and escaped duplicate
keys. The updated tests still require an operator-run acceptance report. See `docs/architecture/M6_0_SLICE_B1_READER_AUDIT.md` and
`docs/architecture/M6_0_SLICE_B1B_ARTIFACT_VALIDATION.md`. Safe live-WAL
reads and cross-source snapshot consistency remain separate blockers.

### B2a — Experimental detached WAL feasibility, not a source of authority

PR #58's versioned B1b validator and conservative derived bundle merged.
`docs/architecture/M6_0_B2A_WAL_FEASIBILITY.md` now proposes a bounded
test-only candidate that copies DB/WAL bytes by no-follow reads to an
owner-private staging directory, opens **only the detached copy** with
SQLite, rejects observed source changes and always declares
`snapshot_proven=False`. Two matching samples and a passing detached
`integrity_check` **cannot establish one atomic instant** with the run
JSON files or even a latest-commit DB/WAL pair during checkpoints. Do not
wire the probe into an operational exporter. Choose and test an explicit
atomic/cooperative snapshot strategy or fail closed.

### B2b — Cross-store consistency architecture review (Proposed)

PR #59 merged the feasibility-only B2a probe with reported local passing
focused/full-suite regression evidence. Its result still declares
`snapshot_proven=False` and cannot be a trustworthy Collector input.
`docs/architecture/M6_0_B2B_SNAPSHOT_CONSISTENCY_REVIEW.md` audits the
production writer order: JSON file replacements and SQLite lifecycle/event
commits occur in **distinct transactions**.

ADR-040 is **Proposed**. It compares a trusted writer-published,
monotonic **as-of seal** (preferred to investigate, but requires explicit
authorization to modify trusted writer paths) against a supported atomic
filesystem snapshot or continued safe refusal. Neither B2a nor SQLite
`integrity_check` proves a combined DB/WAL/file instant. **No chosen
implementation, reader authority promotion or CLI** is authorized until
the operator accepts an architecture with crash/replay/concurrency tests.

### B. Bounded local trace collection and export

1. Implement a read-only collector over one explicitly selected project/run.
2. Read only whitelisted current/historical artifacts and the pre-existing
   SQLite run data through the dedicated side-effect-free snapshot reader;
   **never** call the existing potentially mutating `connect_db` or any claim,
   resume, worker, verification or integration operation.
3. Record `present|missing|invalid|unsupported|stale` evidence with typed
   reasons and never infer absent evidence as pass.
4. Implement a deterministic JSON encoder, stdout by default. Optional
   file output requires explicit opt-in and safe destination handling.
5. Prove non-mutation of SQLite, `.projectctl`, task authority, Git state
   and worktrees under success, error and interrupt conditions.

**Gate B:** exact fixture roundtrip, repeated-export byte identity, corrupt/
symlink/cross-project rejection and no-action proofs.

### C. Explainable read-only evaluation

1. Add narrowly defined metrics only when backed by independently
   validated source evidence (e.g. verification artifact lineage).
2. Each assessment includes evidence references and one of
   `supported|unavailable|indeterminate` — never unsupported certainty.
3. Do not assign a single quality score, modify a Run status, rate workers
   by unverified claims or adjust future admission/quota decisions.
4. Test historical and partial runs, missing evidence and conflicting
   statuses; provenance must outrank self-reported worker result.

**Gate C:** externally inspectable evidence basis for each evaluation field.

### D. Independent closure

1. Run unit/property/adversarial privacy and read-only tests, historical
   replay, CLI verification, full regression suite and schema export checks.
2. Audit resource limits and race conditions; document residual limitations.
3. Update README, Blueprint, ADR, `docs/PROJECT_STATE.yaml` and version only
   according to accepted milestone and release decisions.
4. Retain the GitHub Actions quota exception as an infrastructure status;
   rerun hosted jobs when quota is available.

**Gate D:** reviewed local/hosted evidence, explicit architecture acceptance,
and no widening of worker authority.

## Immediate next architecture decision

B2b presents ADR-040 as **Proposed** only. The owner must decide whether
modifying trusted ProjectCTL writer paths to publish a derived, immutable,
versioned as-of seal is within M6.0's authority contract. If yes, the
next approved PR designs one bounded writer seal, exact DB commit/event
anchor, recovery and adversarial fixtures; if no, use only a demonstrably
atomic filesystem snapshot or continue fail-closed. No public exporter
until its cross-store proof and no-source-mutation tests pass. No new
Worker permission, provider, release or version change is implied.

## Non-goals

No dashboard, network API, cloud upload, external telemetry, live Codex
execution, autonomous reviewer, score-driven scheduling, database schema
migration or new permission surface in M6.0's initial slice.
