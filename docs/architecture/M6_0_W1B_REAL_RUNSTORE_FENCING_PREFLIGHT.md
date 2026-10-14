# M6.0 W1b — Real RunStore v2 Fencing Preflight and API Migration Boundary

**Status:** characterization / integration planning, NOT production fencing.
**Base:** `main@a48cc90c0e4dc025deceb37b8097db74622ec2ff`
(PR #69, W1a disposable two-process proof, merged).
**Source:** accepted ADR-039/ADR-040 Path A, the W0 review contract,
the 2026-10-14 M6 architecture audit, RunStore and application code.
**Deliverables:** this document and
`tests/test_m60w1b_real_runstore_fencing_preflight.py`.

## 1. Summary of the actual integration problem

W1a proves a **test-only** per-run mutex plus generation/token algorithm
on a separate `w1a_epochs` table. The actual operational `runs`
table in project-state v2 has `lease_owner`, `lease_expires_at` and
`heartbeat_at` only. Its RunRecord has no generation or token.

Therefore no existing v2 owner-string lease can be deemed a fenced
generation, and there is **no safe incremental switch** that just
passes a token to `verify_run` while leaving other RunStore clients
unmodified.

**Decision for this PR:** characterize specific observed v2 legacy
behaviors against an actual temporary RunStore and inventory its
consumers before proposing an operational migration. This PR makes
**no runtime behavior change**, no DB version change, no migration,
no production file publication and no source WAL Reader.

## 2. Source-proven current v2 behavior

| API or boundary | Verified existing behavior | Why this blocks an unreviewed W1 writer patch |
| --- | --- | --- |
| `RunStore.acquire_lease` | Reacquiring with the same `lease_owner` string does not issue a distinct generation/token | ABA owner reincarnation cannot be distinguished |
| `RunStore.heartbeat` | Checks text owner but not stored expiry, generation or per-acquisition token | Expired stale owner can renew before another takeover |
| `RunStore.release_lease` | Accepts only text owner, not generation/token | Old owner with reused identity can release a later generation |
| `RunStore.transition` | Checks expected Run status in one transaction, not a fenced lease credential | A caller without current lease generation can advance a status |
| `RunStore.append_event` | Commits event in its own transaction | A later refused transition cannot roll that event back |
| `RunStore.rebind_for_reverification` | Resets earlier result to VERIFYING and inserts rebind event in a transaction, but has no publication mutex | A later verifier must not seal a stale phase |
| `LeaseHeartbeat` | Calls owner-only `heartbeat` from a thread and checks failures at boundary | Extending token-aware lifetime requires signature and failure handling |
| `verification.py::_atomic_json` | File fsync and replacement, no parent dir fsync and no run-wide mutex | Raw JSON cannot yet become durable writer-committed as-of evidence |
| `projectctl/storage/sqlite.py` | Project DB remains version 2 and migration currently supports v1 -> v2 only | An implicit new version would break pre-existing clients |

The tests in this PR **intentionally demonstrate three known v2
gaps** (expired-owner heartbeat, unfenced status transition, separately
committed event) rather than calling them desirable behavior. They
MUST be deleted/replaced by fail-closed, generation-aware tests when
the audited production upgrade is implemented. If a future release
fixes these gaps, a failing characterization test is expected progress.

## 3. Actual API consumer inventory

The following source files were checked at the PR baseline for
`acquire_lease`, `release_lease`, `heartbeat`, `transition`,
`append_event`, `rebind_for_reverification`, and manifest writers:

| Area | Relevant source paths | Integration obligation |
| --- | --- | --- |
| RunStore canonical write API | `projectctl/storage/runs.py` | New fenced API(s) may not silently change the semantics for legacy v2 consumers |
| Run lease renewal loop | `projectctl/runtime/leases.py` | Propagate a generation/token handle privately, fail closed after expiry or takeover |
| Execution/admission/resume | `projectctl/application/execution.py` | Many transitions and event writes; verify lock ordering and maintenance compatibility |
| Verification | `projectctl/application/verification.py` | Only non-review successful VERIFYING -> READY_TO_INTEGRATE may emit Seal |
| Integration and cleanup | `projectctl/application/integration.py` | Cannot overwrite protected artifact/epoch without approved coordination |
| Recovery and rebind | `projectctl/application/recovery.py` and RunStore rebind | Old writer cannot seal after phase reset, even if Run ID reused |
| Task reconciliation | `projectctl/application/task_lifecycle.py` | Existing terminal state updates/events must keep their authority and semantics |
| Claim/review/publication | `projectctl/application/claims.py`, `review_delivery.py`, `publication.py` | Preserve independent external/provider authority and event provenance |
| Other JSON producers | `projectctl/application/auto.py`, `portfolio.py` | Inventory path ownership; do not assume all generic JSON writers touch Seal leaves |

**Inventory scope:** a source scan of the above application/storage/
runtime paths at this exact baseline, not a formal call graph or proof
that no plugin/CLI entry points mutate evidence. Before production,
require an explicit owner of every write to
`verification-manifest.json` and `evidence-manifest.json`, and each
rebind/reverification and lease grant path. Do not wrap the generic
`transition` API with an unconditional new token requirement until
a compatibility plan for *all* callers exists.

## 4. Required contract split before real implementation

### 4.1 Generic existing transition vs private sealed transition

Do not naively replace all `RunStore.transition` invocations with a
Seal-capable transition. Propose a separate **private trusted writer
entry point** for the one authorized Verification boundary, with a
transaction owned by that entry point:

1. Validate project/run/task/strategy, current verifying status and
   actual pinned plan/candidate evidence after a unique epoch was
   acquired under the **same** artifact mutex as all competing grants.
2. Compare generation/token/expiry/expected previous status under
   `BEGIN IMMEDIATE`, reject zero-or-multiple row updates.
3. Insert fresh `verification.passed` and `run.transition` events in
   that **same** transaction, and insert one private v1 Seal bound to
   the new event ID, row/manifest and already durable JSON raw bytes.
4. Commit once, handle unknown commit outcomes by exact epoch
   reinspection; no blind duplicated event/Seal.
5. Keep old `RunStore.transition` behavior available for historical
   non-Seal callers until every permitted migration path is planned;
   **never allow it to bypass ownership rules for a Seal-bearing Run**.

The last point is intentionally an **unresolved production design
decision**: an old binary that knows only v2 must not open a v3
authority and mutate a sealed run. It must refuse before writing.
New v3 transition APIs must guard post-Seal state updates and
approved re-verification/rebind paths.

### 4.2 Migration/compatibility

No production `lease_generation`, `lease_token`, `trace_seals`
or SQLite schema-version upgrade is approved by W1b. The future
M0/W1 rollout must atomically establish the final schema, initialize
new project DBs at the new version, explicitly migrate existing v2
only with operator-approved backup/recovery, verify v1->v2->v3
upgrade and old v2-client refusal, and handle all active/expired
legacy leases without silently granting authority. A token must
never be included in public Trace/Seal JSON/logs or event payloads.

Before an operational implementation, specify: which owner may
acquire/reacquire when previous owner expires; trusted time source;
how to bind minted credentials to a process; whether post-rebind
sequence remains pilot=1 or requires a new immutable epoch;
run/event composite FK; and how fixed-name artifact overwrites make
historical raw bytes unavailable.

## 5. W1b characterization test matrix

The six tests in `tests/test_m60w1b_real_runstore_fencing_preflight.py`
use a **freshly initialized ProjectCTL v2 database** in pytest
`tmp_path` and the real `RunStore` to capture:

- exactly v2 fields, and absence of a real `trace_seals` table;
- same-owner lease reacquisition without a new epoch token;
- legacy heartbeat succeeding after stored expiry (known gap);
- legacy status transition succeeding under another live lease owner
  (known gap);
- separately committed `verification.passed` event surviving a
  rejected status transition (known gap);
- existing public lease methods taking an owner name rather than a
  private generation/token.

Tests are safe observations of **disposable state only**; none asserts
that these v2 behaviors should remain in the production fenced writer.

## 6. Exit gates

For this PR only: exact-head GitHub Actions success (full pytest,
compile, schema export and Codex SDK) and no runtime changes. A local
full suite is unnecessary if exact-head CI is green.

For a future **real** migration or trusted writer PR:

- **M0:** approved transactional v2->v3 schema, no silent auto-migrate,
  full explicit backup/recovery/old-client test coverage;
- **W1:** all participating writer/grant paths use the same proven
  mutex/epoch protocol, token is protected, old leases fail closed,
  conditional row/event/Seal one-commit proof with byte/directory fsync
  and process-kill fault injection;
- **R1:** independently safe source WAL read and coherent as-of epoch,
  otherwise fail closed and do not enable the Collector.

**Disposition:** recommended as characterization only; do not merge
without owner approval. Passing CI is not a statement that production
RunStore currently enforces fencing. Milestone M6.0 remains active.
