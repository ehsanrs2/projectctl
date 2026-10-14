# M6.0 B3a3 — Project-state v2→v3 Seal Migration Rehearsal

**Status: Experimental on DISPOSABLE real ProjectCTL v2 SQLite databases.**
**Base:** `main@a76d0dd3272090358eaa124e868405e02101132c` (PR #63 merged).
**Governing ADRs:** ADR-039 (Accepted) and ADR-040 Path A (Accepted).
**Production runtime remains `PROJECT_STATE_DB_VERSION=2`.**

## Motivation

B3a2 showed a minimal in-memory `runs` + `run_events` + `trace_seals`
atomic commit/rollback experiment. It did **not** exercise the actual
ProjectCTL project database schema and its `schema_migrations` table.
B3a3 rehearses the next step on an isolated, disposable database
created by the real `initialize_project_state_db` at schema version 2.

## New isolated candidate

`projectctl/trace/seal_migration_lab.py` defines
`rehearse_v2_v3_in_open_transaction(conn, applied_at=...)`. It:

1. Requires an **already open caller-owned transaction**, ProjectCTL
   `application_id`, `user_version=2`, `PRAGMA foreign_keys=ON`,
   existing v2 base tables and recorded migration versions 1 and 2.
2. Refuses a preexisting `trace_seals` table or conflicting triggers,
   duplicate/unsupported version or malformed timestamp **before DDL**.
3. Uses individual `conn.execute` calls, **NOT `executescript`**,
   because `executescript` can implicitly commit an open transaction.
4. Creates a private append-only candidate `trace_seals` table with
   per-run sequence and run/event foreign keys, uniqueness constraints
   and UPDATE/DELETE rejection triggers.
5. Records an explicit migration-history row for version 3 and sets
   `PRAGMA user_version=3` **inside the same caller transaction**.
6. Never begins/commits/rolls back, connects/opens a database, writes
   a backup, initializes a project, starts a Worker or changes any
   existing command. The caller controls rollback on every exception.

The file is **not imported** by `storage/sqlite.py`, `RunStore`,
`projectctl migrate`, `verification.py`, the Collector or CLI.
Importing the module does not execute any DDL. It should never be
called on an authoritative ProjectCTL project. Test fixtures use only
`tmp_path/.projectctl/state.sqlite` with newly initialized v2 state.

## Tests on disposable real v2 schema

`tests/test_m60b3a3_seal_migration_rehearsal.py` validates:
- A realistic initialized ProjectCTL v2 schema upgrades under caller
  `BEGIN IMMEDIATE` and one COMMIT, preserving run/event data.
- Caller ROLLBACK restores **SQLite schema objects, migration history
  and `PRAGMA user_version`** to the exact v2 baseline.
- Fault at every prototype DDL/history/version statement, followed by
  caller rollback, does not leave partially migrated schema.
- Wrong app ID, missing version history, no transaction, unsupported
  timestamp and disabled foreign keys fail without upgrades.
- Replay of an already v3 candidate database is refused.
- Candidate rows reject UPDATE and DELETE.
- Old v2 `RunStore` **rejects** a v3 candidate. This protects against
  silent compatibility claims, but shows why the migration must not be
  enabled until the entire production runtime is version-aware.
- Merely importing and initializing ProjectCTL still produces v2;
  `GLOBAL_STATE_DB_VERSION` remains 2.

## What this DOES NOT prove or authorize

- **No backup, migration command or rollback/recovery contract exists in
  this candidate.** A future production migration must have an explicit
  durable snapshot/backup with permission/privacy and power-loss tests.
- No real v2→v3 migration has been wired to `initialize_project_state_db`,
  `migrate_project_state_db` or `RunStore`. Any customer/owner source
  project remains untouched.
- No approved `trace_seals` schema version for operational use yet;
  constraints, key relationships and accepted Seal protocol need a
  separate schema threat review. In particular, a standalone FK from
  `event_prefix_id` to `run_events.id` does not prove that the event
  belongs to the **same run**; the trusted B3a2 transaction gate is
  a separate check, and SQL-level protection should be considered.
- No evidence-file fsync/dir-fsync proof, same-run filesystem writer
  serialization, trusted Verification writer integration or
  independently validated SHA provenance.
- No cross-store atomicity: single SQLite COMMIT does not atomically
  publish separately written JSON artifacts.
- No sealed live-WAL reader, operational Trace Collector/CLI, runtime
  assessment, worker privileges, external provider action or public
  schema change. B2a `snapshot_proven=False` and Slice B
  `assessments=[]` remain essential.

## Gate to an actual migration PR

1. Review `trace_seals` durable schema, composite event/run FK, keys,
   append-only claims and permissible deletion/maintenance semantics.
2. Design an operator-invoked backup and v2→v3 migration on the real
   `projectctl migrate` path, with v1→v2→v3 chain and v3 initialization
   for brand new projects; reject stale binaries and unexpected schema.
3. Add crash/power-loss and concurrent writer/WAL backup recovery tests,
   double migration/restart/restore tests, disk-full and permission
   failure paths; keep user authority untampered on refusal.
4. Upgrade `RunStore` compatibility **only when** the production
   migration is approved; do not surprise-upgrade a user's DB on read.
5. In a separate PR, bind the vetted Seal to the real verifier and
   one SQLite transition transaction with source-file durability proofs.
6. Separately prove safe non-mutating WAL reader Gate R. No Collector or
   `projectctl trace export` before both gates pass.

## Validation

Because GitHub Actions runs the full suite, compile checks, schema
export and pinned Codex SDK jobs on PRs, exact-head green CI is
mandatory. A local focused test run is recommended; full local
`pytest` is optional for this laboratory slice while exact-head CI
is green. Real filesystem/durability tests will require additional
environment-specific local gates later.

```bash
git fetch origin
git switch --track origin/experiment/m6.0-b3a3-v2-v3-schema-migration-rehearsal
source .venv/bin/activate
python -m pytest -q \
  tests/test_m60b3a3_seal_migration_rehearsal.py \
  tests/test_m60b3a2_seal_transaction_lab.py
GIT_PAGER=cat git diff --check origin/main...HEAD
git rev-parse HEAD
python --version
```

**Merge only after exact-head CI, review and explicit operator Merge
decision.** Even if merged, B3a3 remains a disposable migration rehearsal,
not a production authorization.
