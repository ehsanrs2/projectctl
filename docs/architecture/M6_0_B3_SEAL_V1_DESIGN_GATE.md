# M6.0 B3 — Verification As-of Seal v1 Design and Implementation Gate

**Status: Architecture contract proposed for acceptance with ADR-040 Path A;
no schema migration or trusted writer implementation in this PR**

**Base:** `main@8b40a84fdea1f86ff16427c3f53982e954208e91` (PR #60 merged)
**Parent:** ADR-039 Accepted; ADR-040 Path A selected by owner, effective as
accepted architecture only upon merge of its separate acceptance PR.
**Release:** no new package version, state migration or operational exporter.

## 1. One narrow phase, no implied delivery

The **first implementation target** is the successful *non-review*
Verification transition:

```text
RunStore status: VERIFYING
  -> trusted verifier persists VerificationManifest and EvidenceManifest
  -> verifies pinned source bytes, identities and durability
  -> RunStore transaction: transition to READY_TO_INTEGRATE
       + append run.transition event
       + append immutable as-of seal with that event-prefix ID
  -> one SQLite COMMIT (or all three operations roll back)
```

The first Seal records *locally observed verification evidence* as-of
that committed boundary. It **does not independently certify** that
verification checks passed, that Worker claims are true, that the
candidate was integrated, that the Task was completed, or that any
remote delivery/review succeeded. `ExecutionTraceBundle.assessments=[]`
remains mandatory for Slice B, even for sealed `READY_TO_INTEGRATE`.

**Explicitly out of scope of v1 pilot:** the review strategy that can
transition directly to PASSED; failed/policy-blocked verification;
re-verification/rebind; all claim ownership, integration, cleanup,
task-provider completion, publication and review states; retroactive
seals for existing runs; historical artifact archives; a CLI/Collector.

## 2. Internal seal contract (design target; not a committed schema)

Prefer a **dedicated append-only `trace_seals` table**, migrated only by
an explicit, reviewed project-state database version upgrade, instead
of writing a new `run_events` entry whose own event-prefix digest
would be circular. Event prefix refers to the transition event inserted
**earlier in the same transaction**, not to future events.

`trace_seals` **v1** proposed private fields:

| Field | Required rule |
| --- | --- |
| `run_id`, `project_id`, `task_id` | Exact validated trusted identities; run_id FK, project identity bound to approved local authority |
| `seal_schema_version` | Exactly 1; unknown versions fail closed |
| `seal_sequence` | Monotonic per run, uniquely constrained with `run_id` |
| `observed_status` | Exactly `ready_to_integrate` for v1 |
| `event_prefix_id` | Positive ID of the `run.transition` event inserted inside the same SQLite transaction |
| `run_manifest_schema_version` | Exact persisted historical version at the transition |
| `run_manifest_raw_sha256` | SHA-256 of the exact UTF-8 `runs.manifest_json` bytes stored by that transaction |
| `run_record_projection_sha256` | Deterministic SHA-256 over strictly enumerated selected row columns, excluding authority secrets such as lease owner |
| `verification_manifest_raw_sha256` | SHA-256 of the exact immutable-at-publish file bytes |
| `evidence_manifest_raw_sha256` | SHA-256 of the exact immutable-at-publish file bytes |
| `artifact_digest_algorithm` | `sha256`; semantic digests must be separately labeled, never conflated with raw SHA |
| `seal_protocol_version` | Exact version for file publication and DB event binding semantics |

The schema and column names above are a **review target**, not an
approved migration. All fields must be typed and bounded in storage,
with UNIQUE(`run_id`, `seal_sequence`) and an explicit immutable
insert-only application API. A writer with unrestricted DB access can
still tamper with rows: append-only means **application protocol plus
constraints/test guarantees**, not cryptographic authenticity. No
private event payload, provider credentials, freeform errors,
prompts, logs, absolute paths or review URLs in the seal.

**Do not hash the event payload stream** to create the public event
descriptor. The transition event's `id` is an internal as-of boundary;
public `run_event_stream` remains strictly category/timestamp/sequence
summaries from allowlisted metadata, and the future reader must prove
that the retrieved prefix is complete and consistent with the seal.

## 3. Writer safety and consistency invariants

1. **Trusted local writer only:** the Seal is issued solely from the
   existing verifier/RunStore transition code path, never by Worker,
   CLI export, network, scheduler, or a new autonomous authority.
2. **Durable file publication:** compute exact raw SHA over pinned,
   regular, no-follow artifacts of fixed names. Ensure the underlying
   JSON writer has flushed and fsynced the temporary file and safely
   replaced the named leaf. **The existing helpers do not fsync the
   containing directory** after replacement; this is a new, reviewed,
   POSIX-specific durability requirement before issuing the Seal.
   Unsupported directory fsync/portable equivalents fail closed.
3. **Same-run publication serialization:** prevent any other trusted
   writer from replacing these leaves between validating them and
   the seal transaction commit. `BEGIN IMMEDIATE` alone cannot lock
   filesystem writers. A bounded established writer-serialization
   guarantee must be proven or a separately reviewed mechanism
   introduced; absence of proof blocks sealing.
4. **One DB commit:** open an authorized trusted SQLite writer
   transaction, compare the exact expected `VERIFYING` row state and
   identity, update its `RunManifest` / run row to
   `READY_TO_INTEGRATE`, append the transition event, and insert
   the Seal referencing that event ID **before one commit**.
   Any failure rolls back **all SQLite changes** in that transaction.
   A post-commit separate insert does not satisfy this gate.
5. **No new run authority:** the Seal is not a prerequisite to a
   Worker run, task claim, scheduler decision or delivery. If pilot
   publication is enabled, failures must have a defined fail-closed
   operational policy and must not falsely advance status or silently
   downgrade safety. No task-provider state change is attempted.
6. **Immutable-as-of, not latest:** all Seals represent declared
   committed epochs only. A later transition or an overwritten file
   cannot be combined with the older Seal and labeled current.
   Subsequent replacement of any original evidence filename means
   its older Seal can become **unavailable**, never `present` with
   new bytes. No archival or content-addressed copy is approved in v1.
7. **Strict trust separation:** local publication proves the
   writer-committed source membership, not an independent L3
   semantic proof or L4 delivery assessment.

## 4. Crash/retry decision table

| Interruption point | Required safe state |
| --- | --- |
| Before writing the first source file | No Seal, existing Run state unchanged |
| Temporary file fsynced but not replaced | No Seal; stale temp cleanup by trusted writer only |
| Verification JSON replaced but Evidence not yet persisted | No Seal; never infer verified delivery |
| Both JSON leaves replaced but directory fsync fails | No Seal; typed writer failure, no status advancement |
| Both files durable but another writer races/replaces a leaf | Abort before Seal; require same-run serialization proof |
| SQLite `BEGIN IMMEDIATE` succeeds, transition/event succeeds, seal insert fails | Rollback status + event + seal atomically |
| SQLite commit fails | No Seal accepted; retry/recovery resolves commit outcome, never blindly reinserts |
| Process crashes immediately after committed transition + Seal | Exactly one durable epoch, no duplicate on idempotent reconciliation |
| Concurrent reverify, later file overwrite, or WAL checkpoint | Earlier epoch is as-of only; unavailable if bytes no longer match |
| WAL reader cannot prove side-effect-free source visibility | Refuse Collector; do not use B2a raw copy as proof |

The file system and SQLite are **not** magically one ACID transaction:
before DB commit, a crash may leave published files without a Seal.
Such files must never count as sealed. After DB commit, successful
durability/fsync and writer serialization are required for the
reader to validate the committed seal's file versions.

## 5. Required tests-first implementation work (separate PR)

**Gate W — writer publisher** (not yet implemented):

- Model/schema validation and versioned migration compatibility
  for old DB versions, corrupt new rows and explicit migrations only;
  no automatic migration on an export read.
- Exact status-boundary negative tests for all excluded transitions,
  review strategy, blocked/failed verification and rebind.
- Atomic transaction fault injection at transition, event insert,
  seal insert, SQLite commit and ambiguous commit error.
- Durable-file fault injection at temp creation, file fsync,
  `os.replace`, directory fsync and leaf identity recheck.
- Concurrent same-run writer and file swap simulation, plus crash
  recovery with no false Seal or duplicated monotonic sequence.
- Wrong project/run/task IDs, forged digest, unsupported version,
  symlink path, oversized artifact, missing evidence; typed
  fail-closed treatment.
- Check preserved run/event business behavior, no extra Worker
  authority, no remote provider actions, no raw source disclosure
  into public output.
- Full regression suite and repeatable byte/metadata baseline.
  Publish operator-local test result and exact tested Git SHA.

**Gate R — safe WAL observation** (also separate, NOT solved by Gate W):

- Demonstrate an existing, immutable sealed-as-of record can be read
  as a coherent SQLite WAL snapshot **without** any source
  DB/WAL/SHM authority-data write or covert task/Worker mutation.
- Check source file `atime` under an explicit supported OS policy;
  never claim metadata non-mutation from B2a's old tests.
- Prove DB/event-prefix and fixed-file digests agree with one sealed
  epoch across concurrent writers/checkpoints or fail closed with a
  typed reason; B2a remains `snapshot_proven=False`.
- `assessments=[]` always; no `complete` or remote delivery inference.
- No public trace CLI until both the writer and reader gates pass,
  with separate human merge/acceptance decisions.

## 6. Security/compatibility notes

ADR-039 remains authoritative for exported field allowlist and
local-only, deliberately non-anonymous `project_id`/`run_id` +
source-SHA policy. Internal Seal contents are **not** automatically a
new publicly exportable schema or exception to redaction rules.
The resulting `ExecutionTraceBundle v1` shape and package version
remain unchanged.

M6.0 is still the active project milestone. Approval of this document
permits only a **separate tests-first implementation proposal** for
the narrow trusted verification writer Seal; it does not authorize an
unreviewed migration, Writer code merge, Collector, CLI, scoring,
network sharing, task completion or release.
