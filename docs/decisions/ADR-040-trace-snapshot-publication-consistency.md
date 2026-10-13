# ADR-040: Consistent Trace Snapshot Publication and Proof

**Status: Proposed — NOT Accepted; operator architecture decision required**
**Milestone:** M6.0 — Read-only Trace & Evaluation Export
**Parent decision:** ADR-039 (Accepted; derived local-only non-authoritative export)
**Baseline:** PR #59 merged into `main@90b5bd50777556756e6cf8caed233c3b132f7424`

## Context: the consistency requirement is unresolved

B1a's source SQLite reader deliberately refuses live WAL. B1b validates
previously captured artifact bytes but cannot bind their identity to a
coherent state of RunStore. B2a demonstrates bounded, non-mutating *detached*
WAL readability, **not** an atomic or latest-commit snapshot. Its
`snapshot_proven=False` is a critical safety property, including after
PR #59's passing operator-reported focused/full-suite tests.

ProjectCTL's current writers call `_atomic_json` using temporary files,
`fsync`, and `os.replace`. Their subsequent `RunStore.append_event` and
`RunStore.transition` operations commit through *separate* SQLite
transactions. For example, Verification writes the VerificationManifest
and EvidenceManifest before emitting the corresponding durable event and
transition. Integration similarly persists delivery receipts/manifest
around separate RunStore updates. No current cross-store transaction or
durable all-artifact snapshot publication boundary was found.

SQLite's WAL read transaction provides one consistent **SQLite**
snapshot, but does not automatically include file-system artifacts.
An isolated DB/WAL raw-copy read cannot prove a single atomic instant;
`PRAGMA integrity_check` does not prove that the copy contains the
latest committed transactions. Using a source `mode=ro` connection may
still create/update WAL-index sidecars. Accordingly, none of the above
may be promoted to a proven trace without additional authority evidence.

## Decision under consideration: writer-published sealed observation

**Proposed preferred approach (NOT approved):** add a *trusted,
writer-published, versioned, immutable observation seal* at carefully
selected durable transition boundaries. A seal is **derived audit
evidence**, not a new task/claim/Worker permission or a new verifier.
The collector stays read-only and consumes only an existing seal.

The writer publication protocol, if explicitly authorized, must:

1. Identify a finite bounded set of authoritative file artifacts for
   one `project_id`, `run_id`, `task_id` and source-version set; capture
   exact byte SHA-256 plus **separate** existing ProjectCTL semantic
   digest where applicable. Do not serialize raw prompts, logs or tokens.
2. Publish each referenced file via secure no-follow, same-directory
   atomic replacement, with file and parent directory durability checked.
   A durable file **alone** is not enough to make a multi-file snapshot.
3. In an authorized trusted-application SQLite writer transaction,
   atomically bind **one explicitly selected lifecycle status**, its
   `RunManifest` identity/version, ordered event-prefix boundary, the
   list of fixed-kind source digests, and a monotonic per-run seal sequence.
   The seal must be committed atomically with the status/event boundary
   or be explicitly a later **as-of** observation; never silently claim
   an intervening state as atomic.
4. Use an append-only, uniquely identifiable, versioned record; protect
   against replacement, replay, cross-project/run/task mismatches,
   ambiguous event ordering, or digest collision assumptions.
   The storage design is **not selected yet**: evaluate a typed existing
   `run_events` entry versus a migration to a dedicated `trace_seals`
   table, including the existing event stream's self-reference hazard.
5. Define a bounded recovery procedure for a crash before file replace,
   between files, before the sealing transaction, during commit and
   after commit. A missing/partial seal must be ignored or reported as
   `indeterminate`, never reconstructed from a Worker success flag.
6. Distinguish **as-of seal N** from "latest live Run". If subsequent
   runs/receipts advance, the exported trace is historical as-of N; it
   cannot be labeled the latest state unless separately proven. Do not
   claim the seal cryptographically authenticates the producer.
   **Crucially, a digest is not retention**: existing named JSON artifacts
   may be overwritten. Decide whether sealed epochs retain immutable
   versioned/content-addressed bytes under a new trusted-writer policy,
   or whether older seals legitimately become unavailable when their
   original bytes change. Do not promise historical replay without
   an approved storage and cleanup lifecycle.
7. Keep the exporter fully read-only. It can validate the existing seal
   against safely snapshotted source bytes; no CLI or collector may
   generate/repair seals, trigger Worker operations, or write authority.

**Important change-control rule:** this proposal would add behavior to
trusted ProjectCTL writers. It is a *scope extension* beyond the currently
purely read-only M6.0 export implementation. It **requires an explicit
operator architecture decision**, an ADR-039 compatibility review, and
focused regression/security tests **before any production changes to
writers, RunStore schema/events, or execution authority**. Merely merging
this Proposed ADR does not accept or implement those changes.

## Candidate alternatives (unselected)

### A. Writer-published sealed boundary — preferred to investigate

Pros: explicit as-of point, deterministic proof chain, possible support
on existing local filesystems without privileged snapshot operations.
Costs: touches trusted write paths and possibly SQLite schema; adds
durable publication/recovery mechanics. Requires proof that seal bytes
are complete and were bound to the recorded transaction. A seal is not
independent proof of successful Verification.

### B. Atomic filesystem snapshot of DB, WAL and run artifacts

Pros: unmodified existing writers, single filesystem instant if the
underlying mechanism truly offers it. Costs: portability,
permissions/privileges, mount-topology constraints, lifecycle cleanup and
non-atomic multi-volume layouts. Btrfs/LVM/reflink/copied files are not
interchangeable; ordinary sequential copies are **not** snapshots. Do
not assume an eligible snapshot API exists on a user's machine.

### C. Existing SQLite backup or native WAL snapshot API

Pros: may yield a consistent SQLite view. Costs: SQLite itself must open
the source, so sidecar non-mutation still needs demonstration; even a
perfect SQLite transaction cannot atomically include separately written
JSON files. Not a standalone resolution to the full requirement.

### D. Remain fail-closed, export no "complete" live WAL observations

Pros: no authority expansion and preserves current ADR-039 invariants.
Costs: normal WAL-enabled ProjectCTL cannot yet offer an operational
live RunStore trace. It remains the **mandatory fallback** if no
fully reviewed proof-bearing strategy works.

## Open decision questions (human review required)

- Is adding a *trusted writer-produced, derived seal* permitted in M6.0,
  or must M6.0 remain strictly read-only across **all** components?
- Which lifecycle transition(s) are seal-worthy? Only a terminal
  verification/integration boundary, or interim/pending-review states?
  Some terminal states may later be rebound/reconciled; "terminal"
  must not be assumed immutable without code-backed proof.
- Can we augment the existing `run_events` within a single transaction
  safely, or is a separately migrated typed `trace_seals` table
  necessary? A seal must not hash its own containing event recursively.
- What schema and digest/lineage versions must be supported initially?
  How will missing/historical evidence be classified without guessing?
  Are earlier sealed artifacts retained as immutable copies, or does
  the first implementation explicitly reject historical replay when
  the fixed leaf has been replaced? What disk/retention/privacy budget
  applies to any archived raw bytes?
- Is the initial use case a **sealed historical as-of trace** instead of
  "most recent live state", and may local identity/digest correlation be
  disclosed under ADR-039's non-anonymous privacy policy?
- Does the requirement prohibit **any** writer code/schema change?
  If so, select explicit fail-closed D or a separately validated
  filesystem snapshot facility; do not pretend B2a solved this.

## Required acceptance evidence (before any operational exporter)

- Fault injection at **every** file replacement / fsync / SQLite commit
  cut point: no falsely complete or passing trace after a crash.
- Concurrent append, WAL checkpoint, writer restart, event mutation,
  run rebind/reverify and delivery review updates; no self-inconsistent
  or stale-as-latest assertions.
- An untrusted modified file, symlink swap, source replaced-and-restored,
  missing/unknown historical artifact and wrong-project seal cannot be
  promoted to present verified lineage.
- Corrupt, reordered, duplicated, replayed, cross-run and unsupported
  seal versions fail closed, with only typed safe findings.
- Seal N's referenced file replaced by N+1: either exact trusted immutable
  bytes are still available and validated, or N becomes unavailable;
  never incorrectly bind N's digest to N+1's contents.
- Exact proof of no `.projectctl` / DB / WAL / SHM / Git/worktree/task
  mutation by **the exporter** under success and failures.
- Repeated serialization is byte-identical for the same accepted
  **immutable seal**, using only source-allowlisted fields and
  `assessments=[]` until independently proven lineage is approved.
- Full existing regressions, pinned optional SDK check and local
  Linux/macOS portability coverage as applicable. Hosted Actions quota
  errors are tracked as non-green infrastructure status.

## Disposition

**No option has been accepted.** This ADR is a proposal for a deliberate
operator choice. PR #59 and this document are **not** an authorized
cross-source consistency proof. Preserve `snapshot_proven=False` and
no public `projectctl trace export` command until a separate approved,
tested implementation satisfies ADR-039 and the selected design.
