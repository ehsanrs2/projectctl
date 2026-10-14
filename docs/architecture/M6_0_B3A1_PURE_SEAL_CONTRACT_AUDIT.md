# M6.0 B3a1 — Private Verification Seal v1 Contract Audit

**Status: Experimental tests-first B3a sub-slice; not an authoritative Seal producer**
**Baseline:** `main@b1a4dd1bd550822d929f2b2448301aecdbc708f1` (ADR-040 Path A Accepted)
**Governing:** ADR-039 (no authority-changing export), ADR-040 (bounded Path A as-of Seal architecture)
**Code:** `projectctl/trace/seal_contract.py`
**Tests:** `tests/test_m60b3a1_pure_seal_contract.py`

## Scope and limits

B3a1 introduces a **pure Pydantic internal data contract**, deterministic
UTF-8 private serialization, an exact parser with duplicate JSON-field
refusal, and a fingerprint helper. It is the first **schema-model** step
toward the future writer-published Verification Seal.

The record is limited to one proposed future transition:
`VERIFYING -> READY_TO_INTEGRATE`, for a **successful non-review**
verification path. Other states and review strategy are not authorized.

It has these exact fields (no extras):
- `schema_kind=projectctl.verification_as_of_seal`, `schema_version=1`,
  `seal_protocol_version=1` and `artifact_digest_algorithm=sha256`;
- exact original `project_id`, `run_id` and `task_id` (validated
  without permitting whitespace normalization);
- strictly positive 64-bit integer `seal_sequence` and
  `event_prefix_id`;
- only `observed_status=ready_to_integrate` and
  `run_manifest_schema_version=2`;
- lower-case 64-character raw SHA-256 for the Run Manifest,
  explicitly selected Run row projection, Verification Manifest and
  Evidence Manifest.

The serializer uses sorted keys, compact separators, UTF-8 and a single
trailing newline. Its output is **private**, non-anonymous data containing
raw project/run/task identities and source digests: it is NOT a public
`ExecutionTraceBundle`. The helper-generated seal hash is **not** a
cryptographic signature or independent proof of source authenticity.

`parse_private_seal_json_bytes` is restricted to 4096 bytes, requires
explicit schema discriminators, refuses Unicode-decoded duplicate JSON
object keys including escaped duplicates and rejects unknown fields or
non-finite numeric tokens. Missing/ambiguous identity, version or digest
fields must fail closed rather than default to a different schema.

## What structural validation does NOT establish

1. This code neither reads, writes nor creates any SQLite database,
   WAL, SHM, file, task claim, worktree or worker process.
2. No `trace_seals` SQL table exists or is migrated by this PR;
   `PROJECT_STATE_DB_VERSION` remains 2.
3. It does not compute/check the **actual** raw artifact bytes, source
   identities against the RunStore row, semantic lineage, file durability
   or event-prefix existence. A valid model may hold completely invented
   SHA-256 strings — the trusted writer must prove them separately.
4. It does not atomically bind a Seal, status and transition event. That
   needs a future accepted writer transaction + migration/rollback gate,
   with exact same-run writer serialization and fsynced directory rename.
5. It does not solve live WAL reading or cross-file snapshot consistency.
   B2a's detached WAL probe remains `snapshot_proven=False`.
6. It does not introduce historical evidence archives: overwritten
   fixed-name leaves make a prior Seal's raw files `unavailable`.
7. No Collector/CLI or independently supported Verification/Delivery
   assessment is enabled. `assessments=[]` remains mandatory for B Slice.

## Why isolate this first

The accepted ADR-040 allows a *separately reviewed* tests-first
implementation, not an immediate production mutation. A small contract
PR exposes field, version, JSON ambiguity, raw-identity normalization,
digest and privacy assumptions before a state DB version bump changes
all ProjectCTL instances and test fixtures.

The subsequent **B3a2** Draft should explicitly design the `trace_seals`
table migration, trusted verifier integration with the existing
`RunStore.transition` transaction and correct event-prefix anchor;
it must not silently apply migrations or write Seals during unrelated
operations. The exact run record projection, dual raw/semantic digest
policy, WAL durability, interrupted commit recovery and filename
retention are independent review gates.

## Operator local verification (NOT YET REPORTED)

```bash
git fetch origin
git switch --track origin/feature/m6.0-b3a1-pure-verification-seal-contract
source .venv/bin/activate

python -m pytest -q \
  tests/test_m60b3a1_pure_seal_contract.py \
  tests/test_m60b2a_detached_wal_probe.py \
  tests/test_m60b1b_artifact_validation.py \
  tests/test_m60b1_readonly_snapshot.py \
  tests/test_m60b0_trace_format_policy.py \
  tests/test_m60a_trace_contract.py

python -m pytest -q
GIT_PAGER=cat git diff --check origin/main...HEAD
git rev-parse HEAD
python --version
```

Reviewers must record exact tested commit and any failure. Earlier
passing operator-local B2a/ADR checks do not imply these **new**
tests have run. Hosted Actions quota limitations are infrastructure
status, not green CI.

**Merge gate:** keep Draft until the focused and full regression tests
pass locally, the private parsing/version boundaries are reviewed, and
a separate owner merge decision is given. No worker/write authority,
public API, package version, project state milestone, SQLite migration
or release is changed by merging this pure contract.
