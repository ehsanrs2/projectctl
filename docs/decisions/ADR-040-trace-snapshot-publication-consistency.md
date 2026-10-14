# ADR-040: Consistent Trace Snapshot Publication and Proof

**Status: Accepted as bounded Path A design on merge of the ADR-040 Path A acceptance PR (2026-10-14); no writer code, database migration, Collector, live-WAL reader, or release is accepted by this decision alone.**
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
transition. Integration similarly persists delivery receipts/manifest around separate
RunStore updates. In particular, the task completion provider can be called
**before** the integration manifest and final RunStore transition; the
integration manifest can also be **replaced again after PASSED** when
worktree cleanup succeeds. Neither the external task provider nor remote
review/publication state participates in the local SQLite transaction.
No current cross-store transaction or durable all-artifact snapshot
publication boundary was found.

SQLite's WAL read transaction provides one consistent **SQLite**
snapshot, but does not automatically include file-system artifacts.
An isolated DB/WAL raw-copy read cannot prove a single atomic instant;
`PRAGMA integrity_check` does not prove that the copy contains the
latest committed transactions. Using a source `mode=ro` connection may
still create/update WAL-index sidecars. Accordingly, none of the above
may be promoted to a proven trace without additional authority evidence.

## Selected decision: Path A — bounded writer-published as-of seal

**Path A was explicitly selected by the owner. This architecture decision
becomes Accepted only when its separate acceptance PR is merged.** Introduce
a *trusted, writer-published, versioned, immutable observation seal* at an
explicit durable lifecycle boundary. The Seal represents an **as-of local
observation**, not a new verifier, Worker permission, task authority, or
independent assertion of successful delivery.

**Initial scope:** one successful non-review Verification path, at the
`VERIFYING -> READY_TO_INTEGRATE` RunStore transition **only**, after the
same Run's `verification-manifest.json` and `evidence-manifest.json` have
been durably published. Other states, review-strategy `PASSED`, failures,
reverification, integration, task-provider changes and remote delivery are
explicitly **out of this first implementation**. The trusted writer must
publish a monotonic versioned Seal **inside the same SQLite transaction as
the status transition and its run.transition event**, not in a following
transaction.

**Historical bytes:** the first slice creates **no new raw-evidence archive**.
If fixed-name files are later replaced, an older Seal may become
unreplayable and must be marked unavailable/stale, never reinterpreted using
new bytes. Retention and immutable content-addressed archives require a
separate decision.

**Read-only boundary:** the exporter/Collector remains strictly read-only
per ADR-039. A Seal does not solve the live WAL snapshot reader problem;
that has a distinct, mandatory security/consistency Gate. No operational
export is authorized by accepting this design. See
`docs/architecture/M6_0_B3_SEAL_V1_DESIGN_GATE.md` for the precise
contract and tests-first rollout.

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
   may be overwritten **even after a Run reaches PASSED** (e.g. the final
   integration manifest is replaced to record worktree cleanup).
   Decide whether sealed epochs retain immutable versioned/content-addressed
   bytes under a new trusted-writer policy, or whether older seals
   legitimately become unavailable when their original bytes change.
   Do not promise historical replay without an approved storage and
   cleanup lifecycle.
7. Keep the exporter fully read-only. It can validate the existing seal
   against safely snapshotted source bytes; no CLI or collector may
   generate/repair seals, trigger Worker operations, or write authority.
8. **Keep trust domains separate:** even a valid local seal does not prove
   an external task was completed, a pull request was merged or a
   remote publication succeeded. Those statements need independent
   trusted receipts and semantic validation (later L3/L4), and must not
   be inferred from local `run_status=passed`.
9. **Independent WAL read gate:** a trusted seal committed into the same
   live WAL database does not by itself solve safe, non-mutating extraction
   of its bytes. A separate reviewed reader must prove coherent sealed
   epoch visibility and **zero source DB/WAL/SHM content or authority-state
   mutations**, or refuse. B2a raw-copy `snapshot_proven=False` cannot
   be upgraded just because a seal schema exists. Address filesystem
   access-time (`atime`) effects explicitly; earlier B2a tests compared
   bytes/inode/size/mtime/ctime, **not atime**. If the approved contract
   forbids any source metadata changes, enforce that in a supported
   platform test or fail closed rather than overstating "zero mutation".

**Change-control rule:** Path A accepts the *architectural scope* for a
future, narrowly scoped trusted writer-side Seal. It is not permission to
merge an unreviewed implementation. A separate code/schema/test PR and
explicit operator approval are required before modifying production writers,
RunStore persistence, migrations, or execution authority. The first stage
must remain disabled on existing projects until its migration compatibility,
crash, privacy and concurrency test gates pass.

## Alternatives considered (Path A selected; others remain fallbacks)

### A. Writer-published sealed boundary — selected within the strict initial scope

Pros: explicit as-of point, deterministic proof chain, possible support
on existing local filesystems without privileged snapshot operations.
Costs: touches trusted write paths and possibly SQLite schema; adds
durable publication/recovery mechanics. Requires proof that seal bytes
are complete and were bound to the recorded transaction. A seal is not
independent proof of successful Verification, remote Task completion or
GitHub review state. It also needs a **separate** demonstrably
non-mutating reader for the live-WAL seal and its event prefix.

### B. Atomic filesystem snapshot of DB, WAL and run artifacts

Pros: unmodified existing writers, single filesystem instant if the
underlying mechanism truly offers it. **A filesystem-consistent instant
can still capture a legitimately in-progress multi-step ProjectCTL
workflow; it is not automatically a committed verification boundary.**
Costs: portability,
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

## Implementation-level decisions and follow-up gates (not implicit authorization)

- The owner has selected a **bounded trusted writer-side Seal** while retaining
  the fully read-only Exporter. Any widening beyond the initial successful
  `VERIFYING -> READY_TO_INTEGRATE` path requires a new approval.
- The selected first boundary is `VERIFYING -> READY_TO_INTEGRATE` after
  durable Verification and Evidence manifests. Additional phases, review,
  failure, rebind/reverify and post-PASSED cleanup remain future decisions;
  an initial Seal never asserts that the Run is forever terminal.
- Can we augment the existing `run_events` within a single transaction
  safely, or is a separately migrated typed `trace_seals` table
  necessary? A seal must not hash its own containing event recursively.
- What schema and digest/lineage versions must be supported initially?
  How will missing/historical evidence be classified without guessing?
  Are earlier sealed artifacts retained as immutable copies, or does
  the first implementation explicitly reject historical replay when
  the fixed leaf has been replaced? What disk/retention/privacy budget
  applies to any archived raw bytes?
- The first use case is a **local as-of Verification observation**, not
  "most recent live state", with ADR-039's approved local-only identity and
  digest correlation limits. Broader sharing, pseudonymization or a
  published analytics API remains unapproved.
- Can a seal publish an observation **after** a Run reaches PASSED and
  its integration manifest is replaced by worktree cleanup, without
  falsely presenting an earlier version as complete? Does any phase
  require a later explicit epoch to make its artifact membership final?
- How will a sealed WAL epoch be read **without source sidecar writes**?
  Trusted publication does not answer the read-path problem by itself.
- Which external task/remote delivery receipts can be independently
  checked later, versus merely recorded as non-authoritative observed
  evidence? The seal itself must not expand provider authority.
- The writer extension is restricted to publishing derived audit evidence
  and the exact SQLite transaction boundary; it cannot grant privileges,
  auto-complete tasks, run verification, alter review policy, or repair
  historical authority. If a required security property cannot be proven,
  the system **fails closed** rather than falling back to B2a.

## Required acceptance evidence (before any operational exporter)

- Fault injection at **every** file replacement / fsync / SQLite commit
  cut point: no falsely complete or passing trace after a crash.
- Concurrent append, WAL checkpoint, writer restart, event mutation,
  run rebind/reverify, **post-PASSED integration-manifest overwrite**
  and delivery review updates; no self-inconsistent or stale-as-latest
  assertions.
- A provider-side Task completion succeeds but the local integration
  event/manifest/RunStore commit crashes: no false local/remote
  completion proof, and no automatic task-provider repair by the
  exporter.
- A WAL seal is structurally valid but its source cannot be read without
  sidecar mutation: no exporter call may bypass the refusal.
- An untrusted modified file, symlink swap, source replaced-and-restored,
  missing/unknown historical artifact and wrong-project seal cannot be
  promoted to present verified lineage.
- Corrupt, reordered, duplicated, replayed, cross-run and unsupported
  seal versions fail closed, with only typed safe findings.
- Seal N's referenced file replaced by N+1: either exact trusted immutable
  bytes are still available and validated, or N becomes unavailable;
  never incorrectly bind N's digest to N+1's contents.
- Exact proof of no `.projectctl` / DB / WAL / SHM / Git/worktree/task
  **authority-state or content** mutation by the exporter under success
  and failures. Audit source file **atime** separately; decide whether
  access-time updates are forbidden, tolerated as filesystem metadata,
  or prevented through demonstrably supported read flags. Never silently
  reinterpret no-write as no-metadata-change.
- Repeated serialization is byte-identical for the same accepted
  **immutable seal**, using only source-allowlisted fields and
  `assessments=[]` until independently proven lineage is approved.
- Full existing regressions, pinned optional SDK check and local
  Linux/macOS portability coverage as applicable. Hosted Actions quota
  errors are tracked as non-green infrastructure status.

## Disposition and effectiveness

**Path A is the selected bounded architecture.** On merge of the separate
ADR-040 acceptance PR, this ADR is Accepted **as a design only**. Neither
the selected Seal protocol nor safe live-WAL observation has yet been
implemented, executed, or proven. PR #59's detached WAL candidate remains
`snapshot_proven=False`.

**No operational authority or readiness is implied**: no production writer
change, SQLite schema migration, Collector, public `projectctl trace export`,
verified assessment, new Worker capability, milestone closure, tag or
package release is authorized by this ADR acceptance. The next PR must
independently implement and test the narrowly bounded Seal contract before
a separate merge decision; live-WAL reading remains another gate.
