# M6.0 M0b — Offline Migration Admission and Legacy-v2 Writer Barrier

**Status:** TEST-ONLY characterization and proposed production decision.
**Baseline:** `main@da2ddbf001bcc06a3af61413b19415d451ae5900`
(PR #71 merged after resolving SQLite storage-class/event-prefix findings).
**Scope:** project-state v2→candidate v3 **maintenance admission only**,
not a production migration or trusted Seal writer.
**Governing decisions:** ADR-039 and ADR-040 Path A (Accepted).

## Executive decision

**NO-GO for an automated, in-place v2→v3 migration based only on
`lease_owner IS NULL`, SQLite `BEGIN IMMEDIATE`, a newly created
`flock` mutex, or the existing `execution_authority_gate`.**

An unmodified ProjectCTL v2 process does not participate in the
proposed M0/W1 lock protocol. It can have an already-created
`RunStore` object and later open a SQLite connection, or publish
an external JSON file, after an M0 migration has sampled source state.
Consequently a newly introduced lock is an advisory contract, **not**
a mechanism that forcibly fences old binaries or other nonparticipants.

This PR deliberately **does not implement a supposedly safe
automated admission helper**. It tests the actual missing cooperation
so a future production migration cannot mistake a negative preflight
sample for positive proof of all-writer quiescence.

## Source evidence and exact laboratory

`tests/test_m60m0b_offline_migration_admission.py` creates a
disposable project-state v2 schema using the real ProjectCTL
initializer and a real RunStore, all under pytest `tmp_path`.
Each test starts an **independent spawned Python process with a
RunStore object constructed before the purported maintenance gate**,
then uses a bounded IPC handshake to execute one operation while
the parent holds the gate/lock. Four negative-characterization tests:

1. Parent holds the real `execution_authority_gate` while the
   legacy child calls `RunStore.append_event`: the event succeeds.
   Thus the project authority gate, designed for selected application
   operations, does not cover every direct v2 RunStore entry point.
2. Parent confirms `lease_owner IS NULL` while the legacy child is
   already alive, then allows it to acquire the lease during
   `execution_authority_gate`. An empty lease column does **not**
   exclude a process that can acquire its first lease afterward.
3. Parent holds a new disposable `flock` maintenance lock while the
   nonparticipating child appends an event successfully. A hypothetical
   M0 lock does not acquire coercive effect against old v2 writers.
4. Parent holds SQLite `BEGIN IMMEDIATE` while the child replaces an
   independent dummy JSON file. SQLite transaction serialization does
   **not** prevent separately published artifact bytes from changing.

**Interpretation:** passing tests prove these safety gaps are
reproducible for the tested v2 runtime. They are NOT assertions that
the unsafe behavior should remain in future versions. When a
cooperative maintenance gate is deployed to every participating
writer, these characterization tests should be replaced by explicit
refusal/concurrency tests.

## Safe rollout alternatives requiring owner decision

### Option A — Strict offline-only v2→v3 migration (narrow preferred path)

- Operator deliberately stops **all ProjectCTL processes** capable of
  touching this project, including ongoing verification workers,
  heartbeat threads, schedulers, recovery/admission and detached
  processes holding SQLite connections; external trusted file
  writers must also be stopped. The exact operating-system-specific
  exclusion/verification procedure must be documented and tested.
- The migration tool is launched in a **dedicated offline maintenance
  window** with explicit project identity and operator authorization;
  it MUST fail closed if the environment cannot establish the stated
  offline/exclusive condition. A `ps` snapshot, PID-file, empty
  lease table or a lock invented in v3 cannot by itself prove this.
- Resolve legacy lease owners; never silently convert a v2 owner
  string into a v3 fencing credential or assert generation continuity.
- Anchor and validate the selected project's database and artifact
  paths; verify source version, integrity, trusted migration history,
  ownership, permission and backup retention destination; capture a
  durable validated backup including WAL-committed state.
- Hold the maintenance exclusion **continuously** across source
  recheck, backup publication, migration transaction, version/integrity
  recheck and commit-outcome reconciliation. Reopen/unpause workloads
  only after exact v3 outcome is unambiguous, and old clients are
  prevented from reopening or modifying it.
- On ambiguous commit, crash or untrusted backup, stop and require
  operator-guided recovery; **no automatic replacement of source
  DB/WAL/SHM** and no inference from a lone version number.
- Even after successful migration, full W1 trusted writer
  fencing/artifact publication and independently safe R1 WAL
  read-only gate remain distinct requirements.

**This is a policy candidate, not a claim that a portable, reliable
offline admission implementation already exists.**

### Option B — Two-stage cooperative cutover

Ship and independently validate a **pre-v3 v2-compatible release**
in which every writer, lease grant, background heartbeat and
source artifact publisher participates in one audited maintenance
admission/fencing protocol. Only after no uncooperative v2 binaries
remain can the second-stage v3 migration assume the gate is honored.

This has broader code rollout/test and compatibility cost, and
cannot be safely enforced retroactively against already-running
old binaries without a separate operator exclusion gate.

## Prerequisites before operational Migration M0

**M0-1 — exact source and writer inventory.** Record all RunStore
calls, worker/heartbeat lifetimes and paths that publish
VerificationManifest/EvidenceManifest; include processes that
currently hold an open SQLite file descriptor but have
`lease_owner=NULL`.

**M0-2 — supported OS/filesystem admission method.** Define a
testable *offline state*, an operator confirmation or site-specific
coordination protocol, error/timeout handling and how to fail closed
for unknown writers, process namespaces, mounts and remote clients.
Do not treat a new advisory lock as an exclusion proof.

**M0-3 — durable backup and recovery.** Use SQLite online backup as
appropriate for committed WAL state *only after trusted admission*;
protect backup directory ancestry/leaf identity, source/backup
privacy, fsync file+parent, and ambiguous outcomes. Validate backup
integrity, epoch identity, and explicit operator restore semantics
before changing state.

**M0-4 — one reviewed v3 contract.** Use the corrected M0a
storage-class, composite FK and event-prefix constraints. Define
fresh-project v3 initialization, v1→v2→v3 migration, old v2 client
refusal without mutation, no legacy lease token carry-over,
reverification policy, and trusted application API changes.

**M0-5 — dedicated fault and concurrency acceptance.** Real OS
process crash, WAL contention, partial backup/fsync/full-disk,
unexpected permissions, symlink/hardlink/path swaps, stale writer
resume and ambiguous SQLite COMMIT. A green routine CI suite is
insufficient for a durable production gate.

## Scope and code safety

Only one new test file and this document. No code under
`projectctl/` is edited; `PROJECT_STATE_DB_VERSION=2`, normal
`projectctl migrate`, RunStore, production SQLite, Verification,
Worker privileges, release and Trace Collector remain unchanged.

**Exact-head CI:** require full Python pytest/compile/schema export
and pinned SDK jobs. Since subprocess and POSIX locking behavior
are environment-specific, an operator-local focused test is
recommended before accepting this as a portable observation.

```bash
git fetch origin
git switch --track origin/experiment/m6.0-m0b-offline-admission-proof
source .venv/bin/activate
python -m pytest -q tests/test_m60m0b_offline_migration_admission.py
GIT_PAGER=cat git diff --check origin/main...HEAD
git rev-parse HEAD
python --version
```

**Disposition:** propose adopting the **offline-only default**
before operational migration, subject to review of actual
environment-specific exclusion and restore controls. M0b laboratory
success does **not** authorize production migration or elevate
R0 `snapshot_proven=False`/Slice B `assessments=[]`.
Owner-controlled review and merge remain mandatory.
