# M6.0 B3a2 — Isolated Seal Transaction Laboratory

**Status:** Experimental prototype; **no ProjectCTL DB version migration or trusted-writer integration**
**Baseline:** `main@d8bba537b2f86be316748f76ac508afc737d90ea` (PR #62 merged)
**Governing:** Accepted ADR-039 and ADR-040 Path A; B3 Seal v1 Design Gate
**Code:** `projectctl/trace/seal_transaction_lab.py`
**Tests:** `tests/test_m60b3a2_seal_transaction_lab.py`

## Problem to isolate

The approved initial Seal must bind a non-review successful Verification
`VERIFYING -> READY_TO_INTEGRATE` status transition, its `run.transition`
event, and a versioned Seal inside **one SQLite transaction**. It must not
permit a post-commit Seal insert or a half-successful transition if
inserting the Seal fails.

This branch tests a **narrow SQL substrate** before authorizing changes
to the live SQLite v2 migration and ProjectCTL `RunStore.transition`
code paths. The helper cannot write project authority unless future
trusted code explicitly calls it against an already-migrated connection;
no current production caller exists.

## Prototype shape (NOT a migration)

`EXPERIMENTAL_TRACE_SEALS_DDL` is a non-executed-by-production schema
candidate; the isolated tests apply it only to `sqlite3.connect(':memory:')`.
It proposes an append-only `trace_seals` table with:

- `PRIMARY KEY(run_id, seal_sequence)` and unique run/event-prefix pairing;
- foreign keys referencing existing `runs` and `run_events`;
- private canonical versioned Seal JSON and its SHA-256 fingerprint;
- SQL triggers rejecting UPDATE and DELETE from the table.

The tests deliberately simulate the **minimum SQL columns** rather
than claiming to run the real ProjectCTL writer. The actual stored
RunManifest validation, SQLite v2->v3 migration, mixed historical DB
versions, semantic evidence digests, user state authority and file-write
durability are **not proven** by this laboratory.

`insert_verification_seal_in_open_transaction(conn, seal, expected_project_id)`
requires `conn.in_transaction`, an already updated
`runs.status='ready_to_integrate'`, matching run/task/project
arguments, the exact persisted `manifest_json` digest, a fixed
non-secret row projection digest, a `run.transition` event for the
same run which is the latest event at inspection time, and no previous
pilot Seal. It refuses `seal_sequence!=1`.

**It NEVER executes BEGIN, COMMIT, ROLLBACK or DDL, and never opens a
connection.** The trusted future caller would have to place its
RunStore UPDATE, transition-event INSERT and Seal INSERT under its own
single explicit transaction and roll back on any error.

These checks do **not** demonstrate that the event was newly inserted
inside this transaction (rather than preexisting), nor that the source
artifacts were file-system-durable and serialized against other writers.
Those remain explicit next gates before integration.

## Negative cases and fail-closed tests

- One happy-path commit makes all three changes visible atomically.
- Explicit rollback restores the original status/event count and leaves
  no Seal.
- Trigger-injected Seal insertion error followed by caller rollback
  likewise leaves no partial DB transition.
- Wrong run/task/project, unsupported second epoch, forged manifest/row
  digest, missing/non-transition event and stale event-prefix fail.
- Updating/deleting an existing Seal is prohibited in the prototype.
- A second pilot Seal for the same run is refused.
- No transaction, or an unchanged VERIFYING state, is refused.
- No `.projectctl`, real project database, WAL/SHM or Git files are
  opened or created by the fixture.

## Critical limitations before a real writer implementation

1. **A SQL transaction is not an atomic filesystem snapshot.** Directory
   durability after `os.replace`, pinned no-follow artifact bytes and
   same-run writer serialization are not implemented here.
2. **Schema migration:** ProjectCTL's current project DB version remains
   exactly `2`. The DDL is not invoked from `connect_db`, initialization
   or `projectctl migrate`. The real future upgrade requires a safely
   backed-up explicit v2->v3 migration plus independent compatibility
   tests for historical and new DBs, all schema assertions and reader
   version contracts.
3. **End-to-end transactional coupling:** this helper inspects but does
   not call `RunStore.transition`; production code needs a reviewed
   orchestration which verifies the transition event belongs to the
   *same* new transaction and does not change observed business behavior.
4. **No proof of digest provenance:** the four SHA-256 values in the
   pure model can be forged. Writer must hash actual authorized sources
   and prove their identity and phase-specific semantic relationships.
5. **No historical raw-byte retention** and no newly authorized verifier,
   task claim, remote completion, worker or external API.
6. **Reader/WAL Gate R independent:** B2a remains
   `snapshot_proven=False`. The laboratory cannot enable a Collector,
   `projectctl trace export`, a verified assessment or completeness.
7. **Read-only/Privacy:** Seal private JSON includes run/task correlation.
   It cannot bypass ADR-039 public redaction/allowlists and does not
   export raw event payloads or tasks.

## CI and owner acceptance

GitHub Actions is active again. PR #62's branch Commit
`a81bf7cc0656c079ca28f73430a3c20880a29ae6` had a successful CI
run (#1040). **This is not evidence that B3a2 passed.** Check this
PR's exact head GitHub Actions run and inspect its jobs before any
Ready-for-Review or merge recommendation.

Suggested independent operator smoke:

```bash
git fetch origin
git switch --track origin/feature/m6.0-b3a2-seal-transaction-lab
source .venv/bin/activate

python -m pytest -q \
  tests/test_m60b3a2_seal_transaction_lab.py \
  tests/test_m60b3a1_pure_seal_contract.py \
  tests/test_m60b2a_detached_wal_probe.py

python -m pytest -q
GIT_PAGER=cat git diff --check origin/main...HEAD
git rev-parse HEAD
python --version
```

**Merge gate:** focused/full suite green at exact head in Actions and
locally, model/schema threat review, no production authority mutation,
owner merge decision. Remain Draft until these gates are satisfied.
