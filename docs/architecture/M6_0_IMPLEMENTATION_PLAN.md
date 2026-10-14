# M6.0 — Read-only Trace & Evaluation Export: Bounded Implementation Plan

**Status: Slices A/B0/B1a/B1b and feasibility-only B2a merged; ADR-039 and ADR-040 Path A Accepted (PR #61). B3a1 pure private Seal contract/tests are experimental Draft work; NO production writer/migration, Collector/CLI, or coherent live-WAL read exists.**
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

Following the owner's explicit selection of **Path A**, a distinct
ADR-040 acceptance PR now documents a bounded trusted-writer **as-of seal**.
Its initial scope is only the successful non-review Verification transition
`VERIFYING -> READY_TO_INTEGRATE`. Neither B2a nor SQLite `integrity_check`
proves a combined DB/WAL/file instant; no Collector or CLI is authorized.

### B3 — Verification-only Seal v1: approved architecture on merge, code gated

`docs/architecture/M6_0_B3_SEAL_V1_DESIGN_GATE.md` defines a tests-first
contract for publishing a versioned local-as-of Seal **inside the same
trusted-writer SQLite transaction** that advances a non-review Verification
run to `READY_TO_INTEGRATE` and appends its transition event. Files must
already be safely and durably published, and same-run writers serialized;
failure cannot leave a falsely accepted Seal.

The first implementation adds **no raw historical evidence archive**; old
Seals become unavailable when their referenced leaf bytes are overwritten.
Design acceptance is **not** permission to merge code, change database
schema or turn on export. A separate schema+writer implementation PR and
local failure/concurrency proofs are required. The independent safe
live-WAL Reader gate remains blocked and mandatory.

### B3a2 — In-memory transaction lab (Draft, NOT a writer)

After the B3a1 pure private Seal contract merged in PR #62, a dedicated
`projectctl/trace/seal_transaction_lab.py` prototype and in-memory
SQLite tests explore the next atomic **row + transition event + Seal**
boundary. The private candidate DDL is **not an approved v2->v3
migration** and is never executed on ProjectCTL project authority.
The helper neither creates DB connections nor begins/commits transactions.
It requires an already opened caller-owned transaction and validates the
fixed run projection/manifest digest and event boundary before inserting
one experimental Seal.

See `docs/architecture/M6_0_B3A2_TRANSACTION_LAB.md`. This can prove
specific SQLite failure/rollback behavior only. It does not prove
durable file publication, actual verifier orchestration, same-run writer
serialization, independent WAL reading, or a complete trace. Next
production PR must separately address and test **all** those gaps.

### B3a3 — Real-v2 schema migration rehearsal (experimental only)

After B3a2's isolated transaction laboratory merged in PR #63, the
B3a3 experiment creates **disposable real ProjectCTL v2 SQLite**
fixtures and rehearses a proposed v2->v3 Seal table upgrade entirely
within a caller-owned transaction. Its tests verify rollback of DDL,
migration history and user_version under injected faults. No production
`projectctl migrate` hook, database-version bump or authority change
is added. The existing runtime **must reject** the candidate v3 database.

See `docs/architecture/M6_0_B3A3_SCHEMA_MIGRATION_REHEARSAL.md`.
The real migration still requires a separately approved backup and
recovery protocol, full v1/v2/v3 compatibility, trusted verifier
integration, file and directory fsync, same-run writer coordination
and independently proven WAL Reader safety.

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

## Next independent implementation review

After the operator reviews and merges the ADR-040 Path A acceptance PR,
design **one** separate tests-first code/schema PR for the successful
non-review Verification as-of Seal v1. Its merge requires explicit operator
approval and fault-injection proof. Do not silently migrate old projects,
upgrade the B2a probe, or expose a trace exporter. WAL-read coherence and
no-source-mutation remain another separately reviewed gate. No new Worker
permissions, provider, package release or milestone promotion are implied.

## Non-goals

No dashboard, network API, cloud upload, external telemetry, live Codex
execution, autonomous reviewer, score-driven scheduling, database schema
migration or new permission surface in M6.0's initial slice.
