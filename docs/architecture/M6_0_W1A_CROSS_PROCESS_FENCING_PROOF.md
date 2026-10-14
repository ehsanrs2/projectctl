# M6.0 W1a — Cross-process Fencing Proof on a Disposable v2 Database

**Status:** Test-only experimental W1a proof, NOT a trusted writer rollout.
**Base:** `main@edd746735910fd66dca0e936e10ccd4abe0f199a`
(PR #68 merged: W0 architecture proposal).
**Architecture:** ADR-039 and ADR-040 Path A Accepted; W0 publication
protocol is a reviewed *candidate*, not an implemented maintenance
migration or source Reader.
**New file:** `tests/test_m60w1a_cross_process_fencing.py`

## Purpose

The primary W0 risk is *stale-owner file publication*, not merely stale
SQLite updates. The production `RunStore` has a lease-owner string,
but no monotonic lease generation or acquisition-unique token. Existing
`transition` checks status without fencing generation, and trusted
Verification publishes JSON files separately from the SQLite event/status
commits.

**W1a isolates one required invariant:** a writer that loses its epoch
must not heartbeat, release its successor's lease, or replace the
protected file. Lease takeover and file publication must participate in
**the same process-safe artifact mutex**; merely using SQLite
`BEGIN IMMEDIATE` and checking ownership before file writes is
insufficient.

## Implemented test-local mechanism

- Creates only disposable ProjectCTL v2 state via the real
  `initialize_project_state_db` under pytest `tmp_path`. Then adds
  **one test-only table** `w1a_epochs` with per-run generation, token,
  expiry and count. No production migration registers this table.
- Issues new random tokens and monotonically increasing 64-bit
  generations on every controlled lease grant, including a grant using
  the exact same `owner` string. The test's caller explicitly simulates
  an authorized takeover; **no production grant authorization or
  clock-source policy is implemented**.
- Coordinates **both** simulated lease grants/takeovers and dummy file
  publication with the **same stable-inode POSIX flock**, under
  `.projectctl/locks` of the disposable fixture. Lock files are never
  unlinked while in use. A Python process crash releases the kernel
  advisory lock without stale-PID lockfile reclamation.
- Guards heartbeat, release and publication by an exact
  generation/token/status/not-expired condition. All SQLite mutations
  use caller-scoped BEGIN IMMEDIATE and CAS predicates; publication
  holds the mutex across prepublication check, 0600 temporary file,
  fsync/replace/parent fsync and postpublication DB update.
- Uses `multiprocessing` with spawn, separate processes, pipes and
  bounded joins to simulate owner reuse, stale-owner recovery and
  interleaved publication and takeover.
- Includes **one explicitly negative** test: a nonparticipating actor
  can update the SQLite lease epoch while bypassing the file mutex.
  This demonstrates the necessary *all-writer cooperation* entry
  condition instead of claiming a SQLite check alone fences files.

The file written in W1a is intentionally **dummy JSON**, not
`verification-manifest.json`, `evidence-manifest.json`, or a Seal.
This helper is *not* imported by application code; no code under
`projectctl/` is modified.

## Tested matrix and safety boundary

| Test | Demonstrated property |
| --- | --- |
| Two processes with reused owner text | Fresh generation/token; first process's heartbeat/release/publication rejected after takeover; new publication remains unchanged |
| One writer paused while holding mutex; another tries to reacquire lease | Takeover cannot complete until publisher releases the exact mutex; no silent interleaving |
| Forced subprocess exit while holding lock | OS releases lock, same inode remains and the next process can acquire it |
| Expired or explicitly released token | Heartbeat and file publication refused before any dummy leaf change |
| Simulated prepublication exception | No file or SQLite progress |
| Nonparticipating DB-only epoch change | Shows why incomplete adoption of mutex protocol is unsafe |

**This is not a comprehensive security proof.** The test-local mutex
opens one fixture directory path, not the future descriptor-anchored
production lock hierarchy. It does not solve symbolic path/race hardening,
NFS/distributed lock semantics, trusted wall-clock vs monotonic time,
run lease migration compatibility, PID reincarnation outside the test
fixture, heartbeat thread shutdown races, or unexpected privileged
writers. It does not crash-test fsync/power loss after rename/commit.
A post-rename SQLite failure may leave an **unsealed partial file**;
the production source-reader must refuse any nonsealed epoch.

## Key architectural correction to W0

**All grant/regrant/takeover operations must acquire the same per-run
publication mutex as artifact writers** or use a stronger, specifically
proven equivalent that prevents lease changes throughout file publish.
Otherwise an owner can become stale *after* its first ownership
validation but *before* replacing named evidence. Lock ordering must be
run mutex → short database transaction, with no waits for the mutex
while a SQLite write transaction is held.

The test-local epoch token is **not** inserted into a Seal, event payload
or public Trace and must not be logged in production. The exact
generation/token schema, source of expiry truth and keys must be
reviewed with the full v2→v3 migration and RunStore API. This PR is
only an experimental proof, **not** adoption of an operational fencing
credential or lock primitive.

## Next gates before any operational Seal

1. Inventory and coordinate all real writer entry points, including
   acquire_lease, release_lease, rebind, verification failure/success
   and every writer of the two fixed JSON leaves. A mutex is not a
   complete fencing protocol until all relevant paths participate.
2. Decide OS/filesystem support and anchored lock-path/leaf operations.
   Test multi-process shutdown and crash under the actual supported
   environments, plus deterministic timeout and clock semantics.
3. Approve explicit backup/recovery and v2→v3 migration compatibility;
   keep `PROJECT_STATE_DB_VERSION=2` until that separate gate.
4. Introduce real conditional transition/event/Seal commit with raw
   file digests and event-prefix same-run FK **only in a later reviewed
   implementation**, with fault injection at every boundary.
5. Preserve independent **R0/R1 WAL reader NO-GO** until a coherent
   no-source-mutation read is proven. Never expose a Trace Collector,
   call an assessment `supported`, or infer remote delivery from a Seal.

## Validation policy

Exact-head GitHub Actions full test, compile, public schema policy/export
and pinned Codex SDK are required. This change introduces actual
cross-process filesystem mutex behavior: targeted local tests on
the operator's supported POSIX filesystem are also **recommended**
before merging, even if GitHub CI passes. The historical PR #68
documentation CI does not count for the W1a head.

```bash
git fetch origin
git switch --track origin/experiment/m6.0-w1a-cross-process-lease-fencing
source .venv/bin/activate
python -m pytest -q tests/test_m60w1a_cross_process_fencing.py
GIT_PAGER=cat git diff --check origin/main...HEAD
git rev-parse HEAD
python --version
```

**Do not merge without owner review**; merging this test-only
experiment cannot accept actual trusted writer changes, a project
migration, new privilege, a live-WAL source Reader or a release.
