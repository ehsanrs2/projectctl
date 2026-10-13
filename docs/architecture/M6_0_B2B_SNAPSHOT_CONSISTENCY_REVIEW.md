# M6.0 B2b — Real Writer Boundary Audit and Snapshot Decision Matrix

**Status: Review-only audit; no writer/collector implementation**
**Baseline:** `main@90b5bd50777556756e6cf8caed233c3b132f7424`
**Decisions:** ADR-037/038/039 remain Accepted; ADR-040 is **Proposed only**
**Related evidence:** B1a PR #57, B1b PR #58, detached WAL B2a PR #59

## 1. Concrete persistence ordering observed in production source

| Writer and existing code | Durable order / important gap |
| --- | --- |
| `projectctl/application/execution.py::_atomic_json`, `prepare` | Source JSON files (plan, execution input, strategy, etc.) are published via temporary-file fsync then `os.replace`; `RunStore.create` and later preparation/claim transitions happen in different database commits. A partial run can expose files before the corresponding run row/status exists. |
| `projectctl/application/verification.py` | `verification-manifest.json` is written; failure or success evidence is written subsequently; `store.append_event` then `store.transition` are separate SQLite commits. Readers can see new files with a stale run row, or a run row/status before all phase-specific files are validated. |
| `projectctl/application/integration.py` | Integration/review/publication artifacts use separate atomic JSON writes; event and status updates follow through SQLite in separately committed operations. An in-flight external review can update evidence and state independently. |
| `projectctl/application/publication.py` and `review_delivery.py` | Request/receipt JSON writes precede or surround later durable transitions; raw remote receipt can change without an atomic all-store version. |
| `projectctl/storage/runs.py::transition` | A single transaction binds **its own** `runs` row/serialized `RunManifest` update and a `run.transition` event. It does **not** atomically commit files written by other modules. |
| `projectctl/storage/sqlite.py::connect_db` | Creates state parent when absent and issues `PRAGMA journal_mode=WAL`; exporter cannot reuse this mutable setup path. |
| `projectctl/trace/snapshot.py` (B1a) | Safe no-follow file reads; reads SQLite rollback-mode sources but rejects live WAL headers before SQLite connects. |
| `projectctl/trace/validate.py` (B1b) | Parses known historical artifact schemas and source bytes, checks available identities; still cannot prove a matching run epoch, parent-digest lineage, atomic cross-store provenance or independently verified delivery. |
| `projectctl/trace/wal_probe.py` (B2a) | Stages bounded DB/WAL raw bytes away from the project; isolated SQLite can inspect the copy, but `snapshot_proven=False` and repeated byte samples are **not** an atomic copy. |

**Implication:** per-file atomic replacement ensures one file is not
half-written at a named path. It does not prove a coherent **set** of
files, nor a file set paired to a particular SQLite transaction. SQLite
read transactions do not make external file changes transactional.

## 2. Four states an observer might see

| Scenario | Observable combination | Required classification |
| --- | --- | --- |
| Verification writer just replaced verification JSON | New verification file; old/missing evidence; DB row still `verifying` | Not `verified`, not `complete`; snapshot in progress/indeterminate |
| Writer persisted evidence but has not committed transition | Verification/evidence JSON may parse and hash, yet status/event still pre-transition | No inferred durable verification or task completion |
| SQLite transition committed, later delivery artifacts or receipts pending | New status/events with mismatched/missing future-phase files | Must evaluate exact phase; cannot invent completed publication |
| Detached WAL sampled while checkpoint resets/recycles frames | Individually valid copied DB/WAL bytes can encode a stale or non-atomic candidate | No `snapshot_proven`, no "latest" claim, refuse if proof required |

These scenarios must be represented in targeted tests, not only described
in documentation.

## 3. Distinct levels of evidence and their thresholds

| Level | Minimum demonstrated facts | Is it currently available? |
| --- | --- | --- |
| L0 Source bytes readable | Bounded no-follow file read, or safely staged SQLite candidate | For JSON: yes, B1a; live WAL: experimental B2a only |
| L1 Source structure and local identity | Exact raw SHA; version-specific Pydantic validation and available run/task/project identity | B1b for supplied snapshots; not proof of run binding for all historical kinds |
| L2 Cross-store same-epoch observation | Independently published monotonic seal or real atomic snapshot showing DB/WAL/event-prefix and files belong to a declared as-of epoch | **No** |
| L3 Semantic lineage validated | Version-aware parent digest/claim/verification/evidence/delivery chain verified, including source independence | **No** |
| L4 Verified/delivered assessment | Explainable evidence-backed support status from L2+L3; no worker-only pass inference | **No** |

Do not promote an L0/L1 observation to L2-L4. A model-valid
`ExecutionTraceBundle v1` is not a substitute for L2.

## 4. Snapshot architecture comparison

| Option | Cross-store proof potential | No exporter mutation | Changes to trusted writer | Portable/default viable? | Disposition |
| --- | --- | --- | --- | --- | --- |
| Writer-published immutable as-of seal | Potentially strong if the status/event/seal binding is atomic and files are verified/durable | Yes | **Yes; requires new approval and proof** | Maybe; evaluate | **Preferred investigation, not accepted** |
| OS/filesystem atomic snapshot | Strong only where DB/WAL/artifacts share guaranteed atomic snapshot boundary | Yes if safely external | No | Unknown; cannot assume | Conditional fallback |
| Direct `mode=ro` / SQLite backup | SQLite-only consistency; does not include JSON files | Source WAL sidecar concerns unresolved | No | Not enough by itself | Insufficient as standalone |
| Double-copy B2a | No coherent epoch guarantee | Avoids invoking source SQLite | No | Feasibility-only | Cannot prove L2 |
| Fail-closed | Safely refuses unknown proof | Yes | No | Always available | Required default |

The preferred design optimizes **proof quality and portability**, not
minimum lines of code. It is a proposal, not authorization to modify the
writer.

## 5. If seal option is approved: invariants to implement and test

### 5.1 Sealed epoch identity

Define exact `project_id`, `run_id`, `task_id`, `epoch_sequence`,
`run_status`, `run_manifest_schema_version`, a RunStore revision/commit
anchor and ordered event boundary. The seal is append-only and immutable.
Never reuse an epoch ID after crash recovery or restart. A later run
transition may publish another epoch without rewriting the earlier seal.

### 5.2 Artifact membership

Only fixed `TraceSourceKind` values and known relative leaf names may
belong to a seal. Retain raw SHA-256 and existing semantic digests
**separately**. File bytes are compared via pinned safe descriptors.
Missing/unsupported/historical artifacts remain typed observations; a
seal cannot assert missing files exist or substitute Worker claims.

### 5.3 Crash-safe publication

The producer must finish and fsync artifact bytes, atomically replace
the published leaves, ensure directory durability, then commit an
authoritative DB observation binding the exact digest map with a status
and event-prefix revision **in one appropriate transaction**. Crash at
any boundary means either the previous complete seal remains usable or
the newest seal is absent/invalid. Recovery does not infer a seal from
stale files or call a Worker to repair state.

There is no approved persistence format yet. A new event carrying its
own event-stream digest introduces circularity; choose a strictly
pre-seal event prefix or a dedicated typed seal table **only after**
review of migration/compatibility. Never treat a plain, self-asserted
JSON file as trustworthy commit proof.

### 5.4 Explicit as-of semantics

The trace would represent **as-of sealed epoch N**, not necessarily
the current run status. If the writer advances to epoch N+1, N
remains historical; if the current run later changes without a seal,
**do not return N labeled as current**. An arbitrary "current" status
read from a different epoch must never be combined with seal N's files.

### 5.5 Reader access remains non-mutating

The exporter never creates or repairs the seal, calls mutable
`connect_db`, acquires task/worker authority or exports raw events.
A writer-generated seal itself is NOT independent verification; the
higher L3/L4 checks remain separate. The exporter needs a safe way to
read the **sealed DB epoch** under WAL without creating original
sidecars; staging may help decode proof but not create it.

## 6. Red-team and fault-injection matrix for next implementation gate

| Injected fault/concurrency | Expected safe result |
| --- | --- |
| Crash before/artifact replace/after directory fsync/before seal commit | No new accepted seal or verifiable previous seal only |
| Torn or mixed WAL frames while sampling, checkpoint recycle, writer concurrent commit | No silently latest/proven snapshot |
| Same file name replaced with different inode/bytes or symlink | Refusal / typed source_changed or unsafe_source_path |
| Unknown schema/digest algorithm, historical version, missing source | Unsupported / missing; never current-model coercion |
| Seal refers to another run, project or task | Refusal with identity_mismatch/cross_project_reference |
| Event prefix out of order, duplicate epoch, roll-back to older seal | Refusal or correctly labeled historical as-of |
| Run reverify/rebind or delivery review updates after earlier status | New epoch or declared stale-as-of, never false latest |
| Worker says pass without independently checked evidence | `assessments=[]` for Slice B and no completed-delivery inference |
| Source removed while exporter reads | Safe abort, no write to project or hidden fallback search |
| Serializer repeated with same accepted epoch | Byte-identical redacted JSON and no export-time timestamp |
| Missing CLI permission/new account API | No network or authority-expanding substitute |

## 7. Immediate work recommended for the next approved slice

1. Obtain an **explicit owner decision** on whether trusted writer-side
   derived seal publication is allowed. If not, restrict work to
   fail-closed or supported snapshot-capability discovery.
2. If approved, make a **separate design-and-tests PR** for exact seal
   schema, monotonic epoch semantics, storage choice and state-machine
   cut points, with no Collector/CLI.
3. Prototype sealed boundary for **one** lifecycle transition only,
   prove crash and concurrent mutation behavior, preserve all historical
   schema/event and Worker authority invariants.
4. Only then prove non-mutating sealed-WAL observation and attach the
   accepted file set under a single as-of epoch.
5. Implement read-only Collector/JSON CLI only after the L2 gate and
   independent L3 gate semantics are clearly separated. Slice B still
   emits no supported assessments.

**Do not create ADR-040 `Accepted` by inference from green B2a tests.**
No task, run, or milestone authority was changed by this review.
