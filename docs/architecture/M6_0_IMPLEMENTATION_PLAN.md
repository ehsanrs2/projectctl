# M6.0 — Read-only Trace & Evaluation Export: Bounded Implementation Plan

**Status: Slice A merged and locally tested (PR #54); Slice B snapshot/security gate proposed. ADR-039 remains Proposed; no collector/CLI exists.**  
**Active goal:** `docs/PROJECT_STATE.yaml` — M6.0  
**Architecture proposal:** ADR-039 (Proposed)  
**Inherited safety decisions:** ADR-037, ADR-038 (Accepted)

## Source inventory (verified in repository)

| Existing evidence | Read-only access point | M6.0 concern |
| --- | --- | --- |
| Run/event database | `projectctl/storage/runs.py`: `RunStore.get/manifest/events` | SQLite consistency, durable event ordering |
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

### B. Bounded local trace collection and export

1. Implement a read-only collector over one explicitly selected project/run.
2. Read only whitelisted current/historical artifacts and `RunStore`;
   never call claim, resume, worker, verification or integration services.
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

## Immediate next development task after closure PR

Slice A is proposed in `feature/m6.0-slice-a-trace-contract`: it contains only the output model, additive schema registry, tests and the source/privacy review. The first subsequent implementation branch should resolve the remaining source/snapshot/privacy questions and then implement **Slice B** only after explicit ADR-039 acceptance. No export CLI or new evaluation scoring is yet authorized.

## Non-goals

No dashboard, network API, cloud upload, external telemetry, live Codex
execution, autonomous reviewer, score-driven scheduling, database schema
migration or new permission surface in M6.0's initial slice.
