# M6.0 M0a — Unified v3 Schema Contract for Fencing and As-of Seal

**Status:** test-only, experimental SQL candidate; **NO operational migration**.
**Baseline:** `main@6dca99f8bcd6a1a406da5bdf9e468abe558b2572` (PR #70 merged).
**Authority:** ADR-039 and ADR-040 Path A Accepted; W0 and W1a/W1b are
accepted *source evidence* but not live writer migration authority.
**Implementation:** `tests/test_m60m0a_unified_v3_schema_contract.py`.

## Why a single candidate version matters

Earlier B3a3 experimented with `trace_seals` alone; W1a modeled a
separate, disposable `w1a_epochs` table. Combining them into production
would produce competing v3 meanings and could let legacy v2 RunStore
mutate Run state without respecting Seal/lease authority.

This candidate therefore tests ONE possible **v2→v3 project-state**
schema contract covering both *fenced writer epochs* and the
*Verification as-of Seal*. It is **not applied by any executable
ProjectCTL path** and does not assert that the design is yet complete.

## Exact disposable candidate

The test fixture calls the **real**
`initialize_project_state_db(tmp_path/.projectctl/state.sqlite)` and
starts with ProjectCTL project-state v2; it adds no production source
files. Each candidate SQL statement is run with `conn.execute` inside
the caller-owned `BEGIN IMMEDIATE`, never `executescript`. Candidate:

1. `runs.lease_generation INTEGER NOT NULL DEFAULT 0` with an exact
   SQLite storage-class requirement `typeof(...)='integer'`, a
   nonnegative value, and a rejected int64-overflow increment.
   This is a storage-level constraint; caller-side validation must
   reject Python booleans before binding because SQLite binds them
   as INTEGER 0/1;
2. `runs.lease_token TEXT` limited to NULL or exactly 32 lowercase
   hex characters **stored as SQLite TEXT** (never a BLOB), representing
   a *future* unpredictable per-acquisition token; the value and
   generation must remain PRIVATE;
3. a `UNIQUE` index on `run_events(run_id,id)` to support a
   **composite same-run** event FK;
4. a private append-only `trace_seals` with a single pilot
   `seal_sequence=1`, `seal_protocol_version=1`, bounded JSON bytes
   stored as TEXT (not BLOB), a lowercase-hex SHA-256-shaped TEXT
   fingerprint (not BLOB), and
   `FOREIGN KEY(run_id,event_prefix_id) REFERENCES
   run_events(run_id,id) ON DELETE RESTRICT`;
5. an INSERT trigger requiring `run.transition` for the same Run and
   current Run status `ready_to_integrate`, plus UPDATE/DELETE
   rejection triggers for the Seal itself;
6. three additional event-prefix protection triggers: after sealing
   Run R at boundary E, **UPDATE and DELETE of existing Run R events
   whose IDs are at or before E are refused**, including attempts to
   reassign another Run's earlier event into R. The event INSERT
   check is an **AFTER INSERT / RAISE(ABORT)** trigger so even explicit
   negative IDs and `INSERT OR REPLACE` into the already sealed prefix
   are rejected atomically; a normal automatically allocated ID after E
   and unrelated Runs remain writable. These triggers
   protect SQLite event rows, not separately stored artifacts and not
   cryptographic historical authenticity;
7. one `schema_migrations` entry and `PRAGMA user_version=3` in
   the same transaction.

All twelve statements are explicit in the test file. Candidate preflight
requires existing v2 application ID, exact migration-history versions
1+2, foreign keys ON, expected tables/absence of conflicting schema
objects and **no run with non-NULL legacy lease_owner**. This last
check is a necessary but NOT sufficient maintenance-quiescence proof:
another process can still start unless a trusted maintenance gate
blocks it.

Neither `PROJECT_STATE_DB_VERSION=2` nor
`GLOBAL_STATE_DB_VERSION=2` is changed. Existing RunStore must
**reject** the candidate v3 database before it can write.

## What the tests establish

- Combined candidate can be applied atomically to disposable v2,
  preserves existing Run/event rows and defaults generation=0/token=NULL.
- Rollback restores all DDL, `schema_migrations` and
  `PRAGMA user_version`; error injection at every one of the twelve
  statements must also restore the original v2 state.
- Legacy non-NULL owner refuses upgrade; no transaction, foreign keys
  disabled and wrong application ID fail closed.
- The composite event/run FK rejects a cross-run reference; the
  preinsert trigger rejects a non-transition event. Post-Seal
  event-prefix tests reject changes to anchor fields and earlier event
  rows, deletions, explicit ID backfill and cross-run relocation, while
  allowing legitimate later and unrelated events.
- Duplicate/non-v1 Seal, update/delete, referenced event deletion and
  parent Run deletion fail. Hash/JSON size/version and SQLite TEXT
  storage-class constraints reject malformed values and BLOB payloads.
  Generation must be SQLite INTEGER, nonnegative and cannot silently
  overflow into REAL. The lease token must be NULL or lowercase-hex
  TEXT; tests reject BLOB credentials.
- A SHA-shaped fingerprint plus an arbitrary private JSON string can
  still be inserted directly by a sufficiently privileged SQL caller.
  Thus SQL structure is **not a proof of historical byte authenticity,
  same-transaction event creation, protected writer provenance or
  independent Verification**. The future trusted constructor must
  revalidate canonical `VerificationAsOfSealV1` and actual published
  bytes, and the Reader must revalidate everything it consumes.
  Even the guarded SQL event-prefix rows are not an authenticated
  audit log against arbitrary privileged modification of the
  database, SQL schema, or filesystem.

## Explicit decisions needed BEFORE production M0/W1

**1. Legacy lease quiescence.** Design an exclusive maintenance gate
coordinating `RunStore.acquire_lease`, `LeaseHeartbeat`,
Execution/Integration/Recovery and all other paths. A legacy owner
string cannot be silently upgraded to a trustworthy epoch. The
actual migration must refuse if the project has live or unresolved
legacy leases, including stale processes outside SQLite. Define how
an owner may explicitly stop/reconcile before retrying.

**2. Per-grant fencing.** The DDL only constrains *shape*. Python
booleans are bound as SQLite integers; the trusted application must
validate strict integer inputs separately rather than relying on
`typeof()` to detect original Python types. A trusted writer must
atomically increment generation, mint a new unpredictable
token on every grant/regrant (including same-owner ABA), enforce
expiry/time source, and CAS-check both values on heartbeat, release
and authority-bearing transitions. It must use the same supported
per-run artifact mutex for every participating lease grant/takeover
and evidence writer.

**3. Seal consistency.** The candidate protects previously sealed
event-prefix rows from ordinary UPDATE/DELETE and explicit ID backfill,
but SQL cannot require that the event was *created in the same
transaction*, that previous status was VERIFYING,
that all digests came from the same actual byte files, or that the
manifest/candidate lineage is semantically correct. The real
Verification writer must own status + `verification.passed` +
`run.transition` + Seal in ONE transaction after no-follow,
fsync-file/fsync-parent durable JSON. An ambiguous commit must be
reconciled by exact epoch, not blind retry.

**4. Historical data and epoch policy.** A `seal_sequence=1` schema
allows only the pilot successful non-review phase. Re-verification,
rebind and later overwriting fixed-name JSON may render historical
raw bytes unavailable; do not silently claim old Seals still
readable. Before production, approve whether this exact pilot
restriction is sufficient or v3 must support multiple sequences.

**5. Migration and restore.** No production `projectctl migrate`
wiring, backup, rollback command or operator-approved restore is
added here. The final upgrade must be explicit, backed up, fail
closed on ambiguity, coordinate every writer, support fresh v3
initialization and v1→v2→v3, and reject older v2 clients without
mutation. Path-swap, full disk, concurrent writers, crash after
commit and power loss remain untested in this candidate.

**6. Runtime/API compatibility.** `RunStore.transition` has many
Execution/Verification/Recovery/Integration/Task Lifecycle
callers. A dedicated Seal-bearing API cannot bypass these existing
mutators. A complete **call-site inventory and dispatch design** is
a prerequisite to enabling v3, with token protection (never logged
or serialized to public schema).

**7. Read-only Trace independent.** R0 is not a proven WAL Reader;
do not reuse SQLite backup or the production `connect_db` in the
exporter. Keep `snapshot_proven=False`, `assessments=[]` and
Collector/CLI disabled until independent R1 proof.

## Validation and disposition

Exact-head GitHub Actions must pass the full pytest/compile/public
schema checks and pinned SDK tests. Local full pytest duplication
is optional for this disposable test-only candidate. **This is a
contract test, not approval to apply its SQL on a real project.**

Operator smoke if desired:

```bash
git fetch origin
git switch --track origin/experiment/m6.0-m0a-unified-v3-fencing-seal-schema
source .venv/bin/activate
python -m pytest -q tests/test_m60m0a_unified_v3_schema_contract.py
GIT_PAGER=cat git diff --check origin/main...HEAD
git rev-parse HEAD
```

**Disposition:** review as the proposed *single v3 layout* and make a
separate explicit production M0 design/implementation decision. No
automatic schema migration, live DB modification, trusted writer
authorization, worker permission, release or PR merge is implied.
