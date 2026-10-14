# M6.0 — Architecture and Implementation Audit (2026-10-14)

**Status: REVIEW FINDINGS; not an accepted ADR or authority change.**
**Audited main:** `2e47b50b0308b0919114bbdd0f88e6ce97fed8e2`
**Milestone authority:** `docs/PROJECT_STATE.yaml`, still M6.0.
**Audit scope:** accepted ADR-039, ADR-040, merged PRs #54–#65, trace
source/format/model/validation, Verification/RunStore/SQLite source,
B3a1–B3a4 experimental laboratories, tests and CI workflow.

This is a **source and contract review**, not a formal security proof,
production crash experiment, independent replication of all tests, or
certification of GitHub's production infrastructure. No writer,
schema version, database, CLI or tests were modified for this audit.

## 1. Decision in brief

**Conditional GO for the *architecture*, NO-GO for operational migration,
writer-produced seals or a public trusted Collector.** ADR-039 and
ADR-040 agree at the governing level: an exported trace is non-authoritative;
a narrowly trusted writer may later publish a derived as-of observation
at the Verification boundary. The separation between the writer
publication gate (W) and the side-effect-free live-WAL reader gate (R)
is correct.

However, the implementation is still a series of **safe, isolated
experiments**, not a connected end-to-end system. Several design
preconditions must be made executable and demonstrably true before
advancing from laboratory evidence to production. We should **stop
creating further general-purpose migration/backup labs for now** and
first resolve the critical proof and rollout questions below.

## 2. Verified current inventory

| Layer | Merged PR(s) | Implemented | Explicitly not implemented |
| --- | --- | --- | --- |
| Trace contract and formatting | #54/#55/#56 | `ExecutionTraceBundle v1`, deterministic formatter, accepted read-only/privacy ADR-039 | Collector and CLI |
| Source readers | #57 | No-follow bounded artifact reads, conservative rollback-journal DB read | Validated safe live-WAL read |
| Artifact interpretation | #58 | Exact versioned schema parsing, local identities, always-incomplete bundle, `assessments=[]` | Semantic lineage and independent supported assessments |
| Detached WAL feasibility | #59 | Bounded detached candidate with `snapshot_proven=False` | Atomic/latest cross-source snapshot |
| Consistency architecture | #60/#61 | Accepted ADR-040 Path A, verification-only seal design | Proven writer seal or file+DB ACID |
| Strict private Seal v1 | #62 | Pure private typed model, canonical JSON and bounded decoder | Durable writer authority |
| Transaction laboratory | #63 | In-memory candidate table, insert checks and fault-injected rollback | Real RunStore transition coupling |
| v2→v3 DDL rehearsal | #64 | Temporary real-v2 schema DDL/rollback test | Registered migration or new runtime DB version |
| WAL-inclusive backup lab | #65 | Disposable v2 SQLite backup/restore and prepublication fault tests | Maintenance lock, durable recovery, production backup |

All twelve PRs #54–#65 were verified merged. PR #65 merged to
`main@2e47b50b0308b0919114bbdd0f88e6ce97fed8e2`.
The PR #65 *head* `d14ab6c7c65b53f7d5c7c17f3451b83c243842e5`
passed [CI #1046](https://github.com/ehsanrs2/projectctl/actions/runs/38528342075)
(`test` and `codex-sdk-contract`). At audit lookup time the merged
`main` SHA had **no separate workflow run returned**: do not invent
a successful run for that merge SHA. Earlier PR local/CI evidence
is not evidence for an untested future commit.

`PROJECT_STATE_DB_VERSION=2`, `GLOBAL_STATE_DB_VERSION=2`; there is
no `trace_seals` table in normal project state; no real Seal producer,
trusted Exporter or `projectctl trace export` CLI.

## 3. Correct choices to preserve

1. **Authority separation:** ADR-039 forbids export from deciding
   Worker admission, claim, task completion, verification, integration or
   delivery. ADR-040 permits only a bounded trusted-writer evidence
   extension, not a new verifier. Maintain both independently.
2. **No premature confidence:** B1b never emits supported assessments or
   complete traces. B2a always declares `snapshot_proven=False`. A
   valid model, integrity check, duplicate byte sampling or local Seal
   fingerprint must never be promoted to historical source truth.
3. **Privacy and historical format:** field-level allowlist, exact
   non-anonymous local identity policy, fixed artifact names, bounded
   POSIX no-follow reads and historical schema dispatch are sound
   conservative starting points.
4. **Tests-first, additive development:** separate PRs, pinned SHAs,
   explicit operator merges, local and hosted CI distinction and a
   functioning GitHub Actions test pipeline reduce regression risk.
5. **Two independent proofs:** writer's durable same-run epoch and
   exporter's non-mutating coherent source observation must both be
   proven before a trusted trace; neither can imply the other.

## 4. Blocking and important findings

Risk labels below are **future production acceptance blockers**, not
claims that currently disabled laboratory code already corrupts
user projects.

### F-01 — HIGH: no proven same-run writer fencing or crash-durable file set

**Evidence:**
- `projectctl/application/verification.py::_atomic_json` writes/fyncs a
  temporary file and replaces the named JSON leaf, **without directory
  fsync** or directory-relative no-follow protection.
- In `verify_run`, verification and evidence JSON are saved before
  `store.append_event("verification.passed")`, then
  `store.transition(VERIFYING -> READY_TO_INTEGRATE)` in another
  DB transaction.
- `RunStore.acquire_lease`/heartbeat support expiring lease owner,
  but `RunStore.transition` validates the *status*, not a matching
  lease owner/fencing generation; SQLite `BEGIN IMMEDIATE` cannot
  prevent a concurrent file replacement.

**Impact:** if future code merely inserts a Seal into the Run transition,
it may bind files replaced by a different/stale writer. A crash between
JSON rename and SQLite commit can leave unsealed files. File fsync alone
does not guarantee durable directory entries.

**Required:** select a trusted same-run writer serialization and
fencing rule spanning both file publication and SQLite commit; ensure
its lease expiry/restart semantics are safe. Pin and re-hash the *actual*
no-follow file bytes, durable directory fsync, then atomically bind
the run transition event/status + Seal in one commit. Fault-inject all
cuts, including after commit and stale-owner resumes.

### F-02 — HIGH: experimental Seal table lacks SQL-level same-run event proof

**Evidence:**
- `projectctl/trace/seal_transaction_lab.py` candidate DDL has
  `run_id REFERENCES runs(run_id)` and independent
  `event_prefix_id REFERENCES run_events(id)`; it has no composite
  `(run_id,event_prefix_id)` relationship.
- The private Seal's project/task identity, status, digests, schema
  version and JSON fingerprint primarily live inside unvalidated SQL
  `seal_json` text, not enforced by SQLite constraints.
- The lab helper does check `event.run_id` and `event_type`, but
  does not prove the event was **inserted in the same transaction**
  or the previous status was VERIFYING; its own audit explicitly
  acknowledges the former. The candidate can accept structurally
  inadequate direct SQL rows.

**Impact:** a future database-only consistency check or another SQL
writer could store a cross-run or forged/ill-formed Seal. Insert-only
triggers constrain edits after insertion, not truth at insertion.

**Required:** review typed schema/unique constraints, composite
event/run FK or robust equivalent, current-version and hash constraints,
trusted constructor, atomic transition/event/Seal write API and
post-read revalidation. Resolve deletion policy and existing
`run_events ... ON DELETE CASCADE` interactions; document threat
model: local DB-admin tampering is not prevented by a plain SHA.

### F-03 — HIGH: operational v2→v3 upgrade and recovery are not defined

**Evidence:**
- `projectctl/storage/sqlite.py` initializes **project v2** and
  `migrate_project_state_db` handles only **v1→v2**.
- `RunStore.__init__` strictly rejects a DB whose version differs
  from `PROJECT_STATE_DB_VERSION`, currently 2.
- B3a3 uses temporary databases and intentionally refuses v3 under
  existing runtime. B3a4 uses a caller-opened SQLite source and
  disposable destination, **not** a maintenance lock or operational
  backup/restore API.
- In `seal_backup_lab.py`, `os.link` can expose a backup name before
  parent directory fsync. If that fsync fails, the name can be visible
  but untrusted; there is no recovery state marker or user-approved
  restore. Path ancestors are not pinned against symlink/swap races.

**Impact:** enabling v3 before a coordinated runtime/version rollout
will block old project clients. An interrupted or ambiguous-commit
upgrade can leave no trusted basis for automated restore.

**Required:** maintenance exclusivity across all project writers,
privacy/backup retention policy, source identity/version rechecks,
secure anchored backup names, durable backup publication, migration
commit-outcome reconciliation, recovery states, and explicit
operator-approved restore. Test v1→v2→v3, fresh v3, old v2 client
refusal, repeated requests, WAL/checkpoints, disk full, crash and
power-loss boundary; never auto-upgrade on a read.

### F-04 — HIGH: the normal live-WAL read-only Gate R remains unsolved

**Evidence:** `projectctl/trace/snapshot.py::read_run_db_snapshot`
intentionally rejects WAL-mode SQLite headers before connecting;
ProjectCTL's own `connect_db` sets WAL. B2a staged raw copies are
non-atomic candidates and explicitly `snapshot_proven=False`.
SQLite's backup API in B3a4 deliberately opens the source and cannot be
reused as an ADR-039 no-mutation Exporter.

**Impact:** even perfectly published Seals cannot be exposed safely
through a normal WAL-enabled ProjectCTL trace under current constraints.

**Required:** do an independent, short **feasibility/proof spike**
for a source-non-mutating, coherent *sealed-as-of* WAL reader before
committing to a production migration rollout. Test cold/active WAL,
missing SHM, concurrent checkpoint/restart, torn/replaced sources,
metadata `atime`, Linux/macOS targets. If impossible, preserve
fail-closed and revisit the product scope without claiming an
operational complete trace.

### F-05 — MEDIUM/HIGH: public trace v1 has no explicit as-of/Seal proof locator

**Evidence:** `ExecutionTraceBundle v1` currently includes project/run,
observed status, sources, events, findings and assessments. It does
**not** state an `as_of_seal_sequence`, event boundary or proof state.
The model's `complete` check is only **structural**, not a trust
certificate. B1b's pure builder always emits incomplete/inconsistent.

**Impact:** future callers may confuse a current run observation with
a historical sealed epoch, especially after rebind, later transitions
or source-file overwrite.

**Required:** settle how private Seal identity/proof/epoch is safely
represented (a controlled public schema revision, explicit typed
as-of metadata, or an intentionally limited v1 mode) and how
`unavailable` historical bytes are reported. Never silently label a
stale Seal current, or treat a parseable `ExecutionTraceBundle` as
independent verification.

### F-06 — MEDIUM: semantic lineage L3 and phase completeness remain unfinished

**Evidence:** `inspect_artifact_snapshot` compares only schema
and available identities; its own docstring expressly disclaims
RunStore epoch and parent digest lineage. B1b builder intentionally
leaves assessments empty. ADR-039 requires supported outcomes to be
grounded in *independent* verification, not Worker success.

**Required:** separate proof levels L0/L1 byte and schema validation,
L2 sealed same-epoch source binding, L3 independent semantic parent/Git
candidate/digest links, L4 verified/delivery assessment. Write
negative tests for forged valid-shaped SHA strings, re-verification,
wrong candidate and external-provider failure. Keep
`assessments=[]` until an independently reviewed gate says otherwise.

### F-07 — MEDIUM: event classification loses key lifecycle evidence

**Evidence:** `projectctl/trace/format.py::_EVENT_CATEGORIES`
recognizes only five exact event types including `run.created`,
publication/review/claim types. The core `run.transition`,
`verification.passed`, `verification.failed` and rebind events
are currently `unclassified`.

**Impact:** even an otherwise valid diagnostic Trace will obscure
precisely the transitions needed to explain a run.

**Required:** safely enumerate existing durable event types,
assign minimal finite redacted categories after privacy review, test
all known categories and preserve fail-closed `unclassified` for
unknown future or arbitrary Worker-supplied event strings.

### F-08 — MEDIUM: scope drift and stale architecture documentation

**Evidence:** the product goal says "Read-only Trace & Evaluation Export",
yet #62–#65 are Seal/transaction/migration/backup experiments. This is
an **explicit ADR-040 scope extension**, but repeated independent
labs risk delaying a usable conservative Collector. Also:
- `docs/architecture/M6_0_IMPLEMENTATION_PLAN.md` top status still
  calls B3a1 experimental Draft although #62–#65 merged;
- `docs/architecture/M6_0_TRACE_CONTRACT_V1.md` still describes ADR-039
  as Proposed although it is Accepted;
- `docs/decisions/ADR-039-...md` still says hosted CI unavailable
  although GitHub Actions is functioning for recent PR branches;
- old plan's non-goals exclude migrations in the initial slice while
  the later accepted ADR-040 explicitly permits bounded writer-schema
  design; the distinction needs to be stated clearly.

**Required:** one milestone-owned source-of-truth *implementation*
scorecard mapping accepted decisions, implemented-but-disabled
experiments, and production gates. Preserve the user-goal distinction
between local **observability** and independently verified provenance.
Keep the active milestone in `PROJECT_STATE.yaml` unchanged until
explicitly closed.

### F-09 — MEDIUM: CI success does not cover the hard failure model

**Evidence:** `.github/workflows/ci.yml` runs `pytest`,
`compileall`, public schema export checks and pinned Codex SDK on
Ubuntu/Python 3.12. The current lab tests do not demonstrate
process-kill/power-loss behavior, cross-process writer fencing,
live user DB upgrade, filesystem ancestor swaps, macOS behavior or
full fault-injected maintenance restore.

**Required:** add an opt-in dedicated critical-path suite or platform
matrix *when those components exist*, with isolated real SQLite/WAL,
subprocess termination, contention/timeouts, permission/disk fault
injection, and source-data/sidecar byte and metadata baselines.
Do not conflate local tests, PR-head CI, merge-head CI and
production failure proof.

## 5. Architectural contract alignment

| Question | ADR-039 | ADR-040 Path A | Review verdict |
| --- | --- | --- | --- |
| Who has authority? | Existing RunStore/humans; Exporter non-authoritative | Trusted writer publishes derived Seal | Compatible if sealed writer cannot grant new execution rights |
| Is export read-only? | Strict yes | Collector still strict yes | Compatible; B3a4 maintenance backup must never be imported into export |
| What is a trustworthy epoch? | Existing DB/files need consistency proof | Sealed as-of Verification boundary | Coherent *conceptually*, not proven in actual code |
| Are missing claims passed? | No | No; old overwritten bytes unavailable | Compatible |
| Is WAL safe to read? | Needs tests, fail-closed | Independent Gate R | Critical open blocker |
| Can a Run be called delivered? | Only with independent evidence | Seal does not certify remote state | Compatible; L3/L4 not built |
| Is implementation production-ready? | No | No | **NO-GO** |

## 6. Recommended revised sequence before further implementation

**Checkpoint 0 — Stop widening the laboratory surface.**
Do **not** start general-purpose B3a5 implementation or run any
operational v2→v3 migration. Review this audit, classify known
risks as explicit entry/exit criteria, and reconcile documentation.
Do not modify the user project's state just to validate the proposal.

**Gate R0 — live-WAL reader feasibility first.** Produce a bounded
independent feasibility report showing whether a genuinely
non-mutating read of an immutable sealed epoch is achievable on
supported platforms. If not, decide fail-closed or explicitly revise
the product/M6 scope before committing to writer/schema migration.

**Gate W0 — end-to-end writer protocol design review.** Specify:
fixed artifact membership, exact bytes/semantic digests, existing
lease limitations and stronger same-run fencing, directory durability,
transaction API that inserts status + event + seal atomically,
event/run FK design, failed/ambiguous commit and post-commit recovery.
Do not infer event freshness merely from MAX(event_id).

**Gate M0 — controlled schema/backup/recovery decision.** Only after
R0/W0 feasibility: choose final SQL schema and v2→v3 migration,
maintenance exclusivity, secure backup location, durability,
operator-approved restore and old-client compatibility. Test a real
disposable project from v2 to v3 with all failure cuts.

**Gate W1 — one real successful non-review Verification producer.**
Implement a narrowly gated trusted writer against v3 disposable
projects, with a genuinely new transition/event/Seal in the same
commit and independently pinned, durable JSON. Fault/concurrency
tests must pass; absent support means **do not seal**, not
"Seal proved complete".

**Gate R1 — side-effect-free sealed-as-of Reader and bounded Collector.**
Revalidate exact epoch and fixed file bytes, never open mutable DB
connect helpers, never promote stale files, keep `assessments=[]`,
no network or worker/provider activity. Update typed output contract
deliberately if epoch/proof data must be exported.

**Gate L3 (later) — independent semantic lineage and evaluations.**
Only after R1 and acceptance: validate parent/semantic digest and
candidate/remote receipts in a separate review. No arbitrary quality
score or automatic Worker policy.

## 7. Explicit acceptance criteria for the next approved PR

- No production wiring or database version bump without a separate,
  accepted design and exact-head CI.
- All experiments remain excluded from CLI and automatic `RunStore`
  initialization/migration until a human-governed migration gate.
- A trusted Seal cannot be inserted for a wrong run/project/task,
  stale lease, failed/review strategy, changed evidence bytes or
  reused/out-of-epoch transition event.
- Crash at any publication/DB/backup boundary cannot create a
  falsely current, complete or independently supported trace.
- Existing v2 projects remain operable until explicit migration;
  incompatible clients refuse v3 with no mutation; backup/restore
  requires deliberate operator action.
- Any unsupported live-WAL read **fails closed**, rather than using
  B2a's non-atomic double read as proof.
- Full and targeted tests plus independent read-only and privacy
  checks are grounded in exact SHA and CI run; local/platform tests
  additionally cover power-loss, WAL and fsync semantics where CI
  cannot.

## 8. Audit disposition

**The architecture direction remains worth pursuing, with a
conditional approval to continue design work. The current
implementation should not yet be described as a working end-to-end
trace, a proven WAL-consistent Exporter, a production migration, or
an independently verified evaluation engine.**

The nearest high-value action is an **architecture checkpoint,
Reader feasibility and trusted writer fencing design**, not another
isolated backup/SQLite lab. Keep M6.0 open. No code modification,
schema migration, task authority change, package version bump or
automatic merge is implied by this audit.
