# M6.0 Slice B — Collector Snapshot, Privacy and Locator Decision Gate

**Status: Proposed for architecture approval; Collector/CLI deliberately BLOCKED**  
**Base:** `main@1b9672af619e7ff4e0fe151b8983c5ca3ec405f6` (PR #54 merged and locally tested)  
**Governing ADR:** ADR-039, still `Proposed`  
**Work in this PR:** concrete source/SQLite/security decisions and *pure* trace-format helper tests; no operational read APIs.

## 1. Existing data-store behavior (verified from code)

`projectctl/storage/runs.py` calls `connect_db` separately for
`RunStore.get`, `RunStore.manifest` and `RunStore.events`.

`projectctl/storage/sqlite.py::connect_db` calls
`path.parent.mkdir(parents=True, exist_ok=True)`, `sqlite3.connect(path)`
and sets `PRAGMA journal_mode = WAL`, plus other PRAGMAs. Reusing it for
a trace exporter violates the strict "cannot create or mutate anything"
boundary. It also cannot provide one consistent snapshot across all three
independent calls.

**Proposed resolution:** the Slice B reader must open an **existing**
project-state database via a new private, explicitly read-only connection,
without importing or invoking `connect_db` or SQLite migration/initialization
routines. Use a bounded SQLite `mode=ro` URI and `PRAGMA query_only=ON`,
verify `application_id` and `user_version`, then `BEGIN` a read
transaction before selecting the run, its stored `manifest_json`, and
ordered events on the **same connection**. SELECT with bound `run_id`;
do not run any DDL, `CREATE`, `INSERT`, `UPDATE`, `DELETE`,
`ATTACH`, checkpoint or journal-mode writes.

**Open SQLite/WAL caveat:** even a read-only WAL-mode connection may require or
interact with `-wal`/`-shm` sidecar files. The next implementation must
*prove* no ProjectCTL authority mutations, and explicitly test first-reader,
absent-sidecar and concurrent writer conditions on the supported platforms.
Do not use `immutable=1` on a live WAL database to avoid sidecars: it can
miss committed WAL content. If a strictly side-effect-free read is impossible
on a supported target, fail closed and document the limitation rather than
silently weakening the contract.

**Race policy (proposed):** inspect `PRAGMA data_version` before and after
the bounded read; check snapshot identity/status against source files before
emitting any trusted result. A changed database or file means
`inconsistent_snapshot`, not a coherent "complete" trace. One bounded
retry at most; after that return typed inconsistency or fail. No execution
lock, migration or indefinite waits. Do **not** infer that data_version
alone covers file-DB atomicity.

## 2. Fixed source locators (verified in production source)

**Database sources — never construct a filename from an event payload:**

| Kind | Verified canonical location |
| --- | --- |
| `run_record` | `.projectctl/state.sqlite`: row from `runs` by bound run_id |
| `run_manifest` | Same `runs.manifest_json` in the *same* SQLite snapshot |
| `run_event_stream` | `run_events` rows in ascending `id`, bound by run_id |

Only read private event `event_type`, ID and creation time to derive category
and order; **do not read or export event payload_json** merely to classify
an event. Worker messages/error details can appear inside event payloads.
Raw type strings do not appear in the bundle.

**Filesystem evidence — fixed leaf filenames under a single validated
`.projectctl/runs/<run_id>/` directory:**

| Kind | Fixed artifact filename | Verified writer |
| --- | --- | --- |
| `execution_input_manifest` | `execution-input-manifest.json` | application/execution.py |
| `claim_transition_evidence` | `claim-transition.json` | application/execution.py |
| `context_manifest` | `context-manifest.json` | application/execution.py |
| `worker_result` | `worker-result.json` | application/execution.py |
| `verification_manifest` | `verification-manifest.json` | application/verification.py |
| `evidence_manifest` | `evidence-manifest.json` | application/verification.py |
| `integration_manifest` | `integration-manifest.json` | application/integration.py |
| `publication_manifest` | `publication-manifest.json` | application/publication.py |
| `review_receipt` | `review-receipt.json` | application/review_delivery.py |

Version-aware readers must use matching historical models; never parse v1
as the latest v2/v3 class. The `RunStore.manifest` convenience reader
currently validates only the v2 RunManifest; the collector must branch on
historical schema/version explicitly.

**Phase-aware presence:** a planned/running/failed run need not have an
IntegrationManifest or PublicationManifest. Absence of optional *future*
artifacts must not itself be an inconsistency. Evidence expectations must
be derived only from the independently observed lifecycle/lineage, not
from arbitrary Worker payload fields.

**Allowed bytes:** at most 2 MiB per evidence file and 512 events per export
in the initial bounded implementation (limits proposed; require regression
coverage for oversize/truncation). Absence of a file is not a cue to recurse,
search sibling directories or follow references supplied in that file.

## 3. Symlink and containment protections

The run ID must satisfy `ExecutionTraceBundle` identifier restrictions
*before* building a path. Do not derive the project root from an arbitrary
artifact reference: use an explicit local repo path and re-check the
configured project ID.

On supported POSIX systems, traverse the known `.projectctl`, `runs`,
run-ID and leaf components with directory-relative `openat`/`os.open`,
`O_DIRECTORY` and `O_NOFOLLOW` as appropriate. Reject symlinks at
every component; compare `fstat` regular-file identity/size around bounded
reads and revalidate source snapshots. A `Path.resolve` check alone is
insufficient against a replacement race.

On platforms without a demonstrably equivalent safe read, fail closed
rather than silently falling back to unsafe `Path.read_bytes` or recursive
glob patterns. Never execute file content, run an LLM or read outside the
explicit source allowlist.

## 4. Identity disclosure and privacy decision (operator review)

**Recommended default for the first local-only CLI:** retain bounded
`project_id` and `run_id` exactly as the selected source identities.
This keeps traces useful for a human to reconcile with `RunStore`.
It is an **explicit privacy tradeoff**, not anonymization: IDs and raw
content SHA-256 hashes may permit correlation/dictionary attacks.

No network publishing is authorized. File export must require an explicit
operator-provided destination outside the mutable authority paths and safe
no-clobber handling. Broader sharing, pseudonymization, salts, hiding
hashes and opt-in disclosure modes must be separately designed before any
cloud/API/dashboard endpoint.

Field allowlist **excludes** task IDs unless subsequently needed, worker
provider/thread, branch, absolute worktree location, lease owner, raw event
type/payload, prompts, logs, environment, remote review URLs, titles,
freeform verification failures, source paths and arbitrary exception text.

## 5. Export model semantics for Slice B

- `ExecutionTraceBundle v1` is already a strict allowlist from Slice A.
- `TraceSourceDescriptor.content_sha256` for a file is over the same
  bounded raw bytes passed to a version-specific reader. SQLite synthetic
  sources must define a deterministic serialization of **exact selected
  columns**; the descriptor is *not* a SHA of an entire SQLite database.
- Emit only `TraceEventSummary(sequence, occurred_at, category)` using
  a finite exact allowlist. All other event names become `unclassified`,
  not arbitrary event type strings.
- In **Slice B, `assessments=[]` always**. Even valid Verification/Evidence
  model objects do not prove the semantic digest/lineage relation.
- Initially prefer `completeness=incomplete` or `inconsistent`
  whenever coverage or cross-artifact proofs are unestablished. Do not
  promote to `complete` merely because all discovered files parse.
- Missing, unsupported, invalid, stale and inconsistent source evidence
  uses typed reason codes only. Never embed Pydantic exception strings.
- Keep `observed_run_status` an observation, not a success/delivery verdict.
- Stable UTF-8 JSON: sorted keys, stable separators, UTC normalized
  timestamps, one trailing newline, no export wall-clock or machine paths.
  `projectctl/trace/format.py` already provides a *pure* formatter.

## 6. Explicit acceptance tests before enabling Collector/CLI

1. A cold (no WAL sidecar), an active WAL and a concurrent-writing SQLite
   fixture: no DB/content changes and no mistaken complete snapshot.
2. Absent DB/config must not be created by an attempted export.
3. Source file replaced during read or parent symlink swapped: either
   typed inconsistency/rejection or fail closed; never follow the target.
4. Oversized file/event stream and malicious run ID fail before unrestricted
   read or directory traversal.
5. RunManifest v1 is historical and different from v2; unknown versions
   show `unsupported_schema`, not coerced `present`.
6. Verification/Evidence without proven shared identity and digest must
   never yield `support=supported`.
7. An active run and a completed run both produce safe traces; absent
   future-phase artifacts do not automatically become failures.
8. No Worker API, task claim, verification/integration mutation, network
   connection or output-file creation from read-only `--format json`
   to stdout.
9. Byte-for-byte deterministic repeated output for a stable run.
10. Full suite + history tests pass and schema v1 remains additive.

## 7. Draft-only B0 implementation in this PR

`projectctl/trace/format.py` implements **pure** deterministic serialization
of an already validated trace and exact-allowlist event categorization.
`tests/test_m60b0_trace_format_policy.py` checks no raw event strings,
no free-form dict output, deterministic bytes and no forbidden fields.

There is **no** actual file or SQLite reader, no export command and no
new ability to mutate ProjectCTL. This is an architecture approval gate.

### Operator validation (uv)

```bash
git fetch origin
git switch --track origin/design/m6.0-slice-b-readonly-snapshot-gate
source .venv/bin/activate
python -m pytest -q tests/test_m60b0_trace_format_policy.py tests/test_m60a_trace_contract.py
python -m pytest -q
git diff --check origin/main...HEAD
```

Record terminal output; earlier GitHub Actions quota exhaustion remains an
infrastructure exception, not a green hosted CI result. No tests were
executed from this GitHub-connected session.

**Reviewer decision:** accept these snapshot/locator/privacy constraints,
amend ADR-039 to Accepted, then begin the *actual* bounded collector
implementation in a separate Slice B execution PR.
