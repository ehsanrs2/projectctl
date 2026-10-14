# M6.0 W0 — Trusted Writer Fencing and Verification Seal Publication Protocol

**Status: REVIEW DESIGN / NOT IMPLEMENTED / NOT A NEW ADR ACCEPTANCE**
**Baseline:** \`main@782c3c4fd4fa29df3169d07c3a6a0b1685eb24e3\`
(PRs #66/#67 merged).
**Authority:** ADR-039 (Accepted: non-authoritative, read-only exporter),
ADR-040 Path A (Accepted: narrow trusted-writer as-of Seal).
**Previous evidence:** B3a1–B3a4 are isolated contract/SQL/migration/backup
labs. R0 is a disposable test matrix, **not** a proven live-WAL Reader.

## 0. Decision requested, with no production permission implied

**Proposed W0 design:** use an independent, per-run, process-safe
*artifact publication mutex* plus a monotonic **SQLite lease generation**
and fresh **lease token** as a fencing pair. For the sole successful
**non-review** Verification boundary, hold the mutex through the
exact-byte file publication and a single transactional
Run status + verification event + transition event + Seal commit.

This is a **design candidate only**: no migration, existing lease method,
filesystem writer, RunStore transition, CLI, reader or Worker permission is
changed by this document. Before implementation, reviewer must approve:
(1) portable supported mutex, (2) all participating writers and lock order,
(3) lease generation upgrade and backward compatibility, (4) safe
publication and failure semantics. Incomplete implementation MUST refuse
sealing, not silently assert a coherent epoch.

## 1. Grounded problem: existing code is not fenced

- \`projectctl/application/execution.py::_actor\` returns
  \`projectctl:<hostname>:<pid>\`. That string can be reused and is
  insufficient as a unique issuance token. Threads in the same process
  may also share it.
- \`RunStore.acquire_lease\` uses \`lease_owner\` and expiration, allows
  the same owner to reacquire, and has **no monotonic generation**.
- \`RunStore.heartbeat\` verifies owner equality but does **not** verify
  generation or reject a lease that was already expired and
  subsequently reused. \`release_lease\` likewise lacks a fencing
  generation. \`LeaseHeartbeat\` calls these owner-only APIs.
- \`RunStore.transition\` checks the old run status under
  \`BEGIN IMMEDIATE\` but has no required current lease generation in
  the update predicate. \`append_event\` commits separately.
- \`verify_run\` writes VerificationManifest and EvidenceManifest
  through independent \`_atomic_json\` calls, emits
  \`verification.passed\` using \`append_event\`, then calls
  \`transition\`. The JSON helper fsyncs the temporary file then
  \`os.replace\`, but **does not fsync the containing directory**.
- The existing \`project_lock\` implementation uses an O_EXCL
  lockfile/reclamation protocol keyed partly to PID/hostname.
  Its current \`execution_authority_gate\` protects project execution
  scope transitions; it does not prove per-run serialized evidence
  publication, and PID-based stale reclamation is not an appropriate
  substitute for a unique lease generation.
- \`rebind_for_reverification\` and other trusted writers can alter
  Run/phase relationships; all paths touching the protected pair of
  artifact leaves or relevant Run state must be inventoried and
  coordinated before enabling W1.

Therefore **SQLite BEGIN IMMEDIATE alone is not an inter-process
filesystem lock** and a matching status alone does not authorize
publication by a stale verifier.

## 2. Candidate ownership and lock protocol

### 2.1 Per-run ownership epoch (proposed private database migration)

Introduce a **trusted-writer-only**, 64-bit monotonic
\`lease_generation\`, initially 0, and unpredictable per-acquisition
\`lease_token\`, bound to the existing \`runs\` row. The exact SQL column
names/migration are **not yet accepted**. Every new lease grant or
regrant, **including same-owner reacquisition**, increments generation
and atomically issues a fresh token. Generation must never wrap, reset,
or be reused, including after recovery. A textual \`lease_owner\`
is diagnostic only; it is not the fencing credential.

Heartbeat, expiration validation, release and all future
Seal-producing mutations must compare \`run_id\`,
\`lease_generation\`, \`lease_token\`, permitted Run status and
trusted database time **inside an SQLite transaction**. Heartbeat by
an expired owner cannot revive an old epoch. Neither a stale release
nor an old heartbeat may alter the successor's lease. The deadline
must use a clearly chosen time source and stable UTC serialization;
tests must cover clock skew, delayed threads and process restarts.
The credential never appears in public Trace, Seal JSON, events,
exception text or logs.

### 2.2 Separate artifact publication mutex

Choose an OS-supported *process-safe* advisory mutex keyed to the
validated run ID, e.g. an owner-private, descriptor-anchored POSIX
\`flock\` file under a fixed \`.projectctl/locks\` directory. Such a
mutex is **not yet implemented**. A design review must establish
which OS/filesystems support it, cross-process behavior, no-follow
path traversal, hardlink/symlink swap safety, parent ownership,
time-bounded wait, safe crash release and cleanup. Never unlink or
replace an inode that might still be locked. A network/distributed
filesystem without proven lock semantics is unsupported and must
fail closed.

**All trusted paths capable of changing the two versioned manifest
leaves, status/event binding or re-verification input lineage must
participate**, or the scope must be narrowed to an *actually exclusive*
producer. A mutex that only \`verify_run\` knows about does not prevent
other writers from replacing those files.

**Lock order (must be audited on every participating path):**

\`\`\`text
acquire run artifact mutex (bounded)
  -> short trusted SQLite lease ownership/epoch revalidation
  -> publish durable fixed-leaf JSON under mutex
  -> BEGIN IMMEDIATE, conditional Run UPDATE + events + Seal
  -> COMMIT/ROLLBACK and resolve ambiguous result
release artifact mutex
\`\`\`

Do **not** wait for the run mutex while holding an SQLite write
transaction. Existing heartbeat can continue using short DB-only
transactions if reworked to be fenced by token/generation and
expiration, avoiding mutex/DB inversion. Global project
execution-authority gate nesting must be documented before any
change to real writers.

### 2.3 Work done outside the short critical section

Long-running verification commands should not hold an SQLite write
transaction or block all runs. Before final publication, a verifier
that has performed checks must acquire the mutex, **revalidate the
active lease epoch**, expected \`VERIFYING\` row and the *actual*
authorized plan, candidate and execution scope. If it lost the
epoch during computation, **abort before writing source leaves**.
This prevents an old process from publishing a new Seal by relying
on an earlier \`record = acquire_lease(...)\` result.

A trust-bearing write after loss of epoch, even if the status happens
to still equal VERIFYING, is prohibited. An old process must not
recover authority by simply calling the same owner-name API.

## 3. Narrow success publication protocol (candidate)

Only \`WorkerStrategyKind != REVIEW\`, actual independently passing
Verification, \`VERIFYING -> READY_TO_INTEGRATE\`, matching expected
candidate, plan and validated source IDs; no failure/review/
reverify/integration/delivery branch is sealed in v1.

While holding the mutex and after checking current lease epoch:

1. Revalidate exact run/project/task association, manifest versions,
   plan/evidence parent semantic digests and current Git
   base/candidate lineage; **a valid-shaped SHA string is not proof**.
2. Construct fixed, versioned Verification and Evidence manifests
   from the trusted results. Persist each by same-directory,
   descriptor-anchored no-follow creation of 0600 temporary files,
   bounded writes, file \`fsync\`, atomic no-follow-safe leaf
   replacement, and directory \`fsync\`. Re-open through pinned,
   no-follow descriptors and hash **the actually published bytes**.
   Do not trust model serialization hashes as if they were raw bytes.
3. Validate the pair's expected identities, semantic linkage and
   inode/path stability while still holding the mutex. Both files
   must be durable before any successful Seal commit. Failure or
   crash during sequential JSON writes may leave **unsealed**
   partial files; they never become a verified epoch.
4. In one caller-owned \`BEGIN IMMEDIATE\` SQLite transaction, recheck
   status=VERIFYING, current token/generation, unexpired lease,
   expected plan/candidate and exact artifact digest inputs.
   Conditionally update Run+manifest using matching lease epoch
   and expected old state; fail if affected row count is not one.
5. Insert \`verification.passed\` **in this same transaction** (today
   it is a separate prior commit). Insert a fresh \`run.transition\`
   event, capturing the newly inserted event ID. Insert a private
   Seal with sequence=1 for pilot, bound to this exact transition,
   row/manifest digests and the published raw file hashes.
   Use **one COMMIT** for status, both events and Seal.
6. Release mutex only after a definite commit or a
   fail-closed/inspected ambiguous commit outcome. Do not retry
   by inserting another Seal based on a guessed previous outcome.
   All subsequent updates treat the Seal as an **as-of** observation
   and cannot silently overwrite it.

The preliminary B3a2 helper tests structural values and the latest
event ID, but **cannot establish event creation inside its caller's
transaction**. The real API must own the complete update/event/Seal
sequence rather than call the existing already-committing
\`RunStore.transition\` and \`RunStore.append_event\` separately.

## 4. SQL relationship and version boundary (not a migration)

The experimental \`trace_seals\` table has separate
\`run_id -> runs(run_id)\` and \`event_prefix_id -> run_events(id)\` FKs.
These do **not** prove that the event belongs to the same Run.

A candidate hardened schema should add a unique index on
\`run_events(run_id,id)\` and a composite foreign key:

\`\`\`sql
FOREIGN KEY (run_id, event_prefix_id)
  REFERENCES run_events(run_id, id) ON DELETE RESTRICT
\`\`\`

This is a **candidate**, not ready-to-apply SQL; analyze
\`run_events\` existing \`ON DELETE CASCADE\` semantics, immutable
Seal retention, run deletion, partial historical databases and
migration compatibility first. Also enforce uniqueness on
\`(run_id,seal_sequence)\`, supported schema/protocol version,
private project/task identity, and robust correspondence between
typed stored fields and private Seal JSON; application-side checks
remain mandatory. A plain SHA fingerprint is not an authenticated
commit certificate.

A v2->v3 migration must be separately approved with maintenance,
backup and recovery protocol. W0 explicitly **does not** modify
\`PROJECT_STATE_DB_VERSION=2\`.

## 5. Failure, crash, retry and concurrency matrix

| Boundary / adversary | Required safe observable result |
| --- | --- |
| Another process with same hostname/PID-style owner obtains new lease | Fresh generation/token; older writer cannot heartbeat, release, write leaves or commit |
| Same owner reacquires before earlier attempt finishes (ABA) | Generation changes; previous attempt's token rejected |
| Lease expired during long verification command | Abort before publication even if status still VERIFYING |
| Stale owner loses lease just before source publication | Guarded recheck refuses; source leaves unchanged by stale attempt |
| Writer crash while owning mutex | OS-released exclusive lock; next writer must check DB and files before retry |
| Cross-run parallel operations | Different run mutexes; no unintended whole-project serialization unless needed for authority policy |
| Rebind/reverification while publication pending | One winner; stale candidate/digests rejected, no false Seal |
| Uncooperative writer replaces a manifest | Sealing prohibited until **all** relevant writers are brought under the protocol |
| Symlink, hardlink swap, parent rename or directory replaced | Descriptor/identity guard refuses; never follow to arbitrary files |
| Fault after verification JSON rename but before evidence rename | Unsealed partial files possible, no successful status/Seal |
| File \`fsync\`, directory \`fsync\`, digest read or semantic check fails | No status advance or valid new Seal; typed failure |
| SQLite update succeeds, passed-event insert fails | Rollback row and all newly inserted events, no Seal |
| Transition event inserted, Seal insert fails | Rollback state and **both** events, no Seal |
| Commit error with uncertain outcome | While still fenced, re-read exact unique epoch; classify committed/uncommitted/indeterminate, **never blind retry** |
| Crash after successful commit, before returning to caller | One durable Seal; reconciliation is idempotent and does not assert duplicate completion |
| Old Seal referenced leaf overwritten by authorized later writer | As-of Seal remains historical; old raw byte proof becomes unavailable without retention |
| Reader cannot observe live WAL without side effects | Gate R remains failed; do **not** enable Collector/CLI |
| GitHub Actions green but real fsync/fencing not tested | No production merge authorization |

## 6. Test-first W1 implementation acceptance checklist

**Fencing (real SQLite, two distinct connections and OS processes):**
lease generation monotonic across takeover/restart, same-owner
reacquisition and token ABA; stale heartbeat/release/transition blocked
by database predicates, expired lease refusal, injected time skew,
process crash during mutex possession and deterministic lock timeout.
The test should prove unchanged original DB/file authority on refusal.

**Publication (disposable actual RunStore, filesystem and WAL):**
all relevant writer paths inventoried; POSIX no-follow anchored file
operations; sidecar/parent inode integrity; file and directory fsync;
raw versus semantic digests; partial file replacement fault injection;
run rebind/candidate-changed race; explicit comparison between stored
Seal and the bytes actually present under the fixed leaf names.

**Atomic DB coupling:** conditional row UPDATE, new same-transaction
verification + transition event IDs, private Seal event-prefix binding
with valid run ID; crash/error injection at each statement and commit;
no false progress, duplicate event or duplicate Seal after recovery.
Old v2 RunStore must reject v3 without mutation; v1/v2 historical
migration cases tested with safely backed-up disposable state.

**Privacy and authority:** no lease token/owner, absolute paths,
provider credentials or raw event payload in public Seal/Trace;
no Worker, task, review or provider privileges added; v1
\`assessments=[]\`; R0 still only feasibility, not a Reader PASS.

**Hosted/local evidence:** exact-head green GitHub Actions full test,
compile, public schema export and pinned Codex SDK. OS-specific
cross-process fencing, filesystem crash/fsync and WAL behavior must
additionally be tested on explicitly supported environments with
recorded fixtures/results, not inferred from ordinary CI.

## 7. Entry/exit and go/no-go

W0 **may be reviewed as a concrete protocol**, not yet accepted as a
verified implementation. BEFORE W1 starts modifying a trusted writer
or v2->v3 migration, decide and record:

1. Exact lock primitive and supported filesystems, lock order and
   participating caller inventory; limitations of network mounts.
2. Generation/token schema and trusted time/expiry policy, old client
   compatibility, required new API signatures and immutable/event
   relational constraints.
3. Rollback and commit-ambiguity recovery semantics, post-commit
   source-byte retention/unavailable behavior and disk/privacy policy.
4. Real test harness for injected failures and two-process stale-owner
   interleavings, including platform limits.

**Disposition:** conditional GO for detailed review of W0; **NO-GO
for production writer change, SQLite migration or Trace Collector**
until the independent W1 implementation and R1 safe WAL reader gates
are met. Retain ADR-039/ADR-040 unchanged and keep M6.0 active.
