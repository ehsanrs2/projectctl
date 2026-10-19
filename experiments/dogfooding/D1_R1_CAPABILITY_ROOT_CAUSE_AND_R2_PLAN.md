# D1-R1 capability mismatch: confirmed metadata-only cause and scoped fix

**2026-10-19. Result:** Original stock-runtime preclaim failure preserved; D1-R1 research-patched `prepare` PASSED; `start` stopped at capability consistency check. **No actual task-model execution** has taken place so far. Next paid attempt, if any, is **D1-R2**, not a continuation of D1-R1.

## Operator-observed saved artifact comparison

Run `run-10e606ca532c403487131ea092db232c`, prepared `2026-10-19T10:44:30Z`, started the `run start` command at `10:44:37Z`; completed `10:44:40.063904Z`.

Read-only comparison of the **actual saved** ProjectCTL version-only and live capability JSON snapshots:

- Version-only effective digest: `canonical-json-sha256-v1:c5b9b80e55f0419159abd111d7a29a950c63221464c100483281c0acb9c2268b`.
- Live effective digest: `canonical-json-sha256-v1:a4aabf9b7550ee9939f5978d90896b5ec91f0800abd4f40c16dee16dd6b836eb`.
- **Exactly one differing field:** `runtime.runtime_version`.
  - Prepared: `0.160.0`.
  - Live: `0.160.0 (Ubuntu 24.4.0; x86_64) Konsole/230805 (projectctl; 0.41.0)`.
- All other effective capability fields were identical; `worker_started=false`.

Durable state independently verified:
- Run `run-10e606ca532c403487131ea092db232c`: `status=needs_decision`, `terminal_reason=capability_changed`, `started_at=null`, `worker_thread_id=null`, no lease owner; lifecycle events include `task.claim.requested`, `task.claim.observed`, `task.claim.transition_validated`, `worker.admission_acquired`, `worker.quota_revalidated`, `task.reconciled`.
- Beads issue `d1ctl-lh4`: `status=blocked`, no `assignee`; it was explicitly unassigned/blocked by ProjectCTL terminal reconciliation, not left in an active claim.
- The `ctl` Git repository was clean; direct arm has not been run.

## Root cause

`CodexWorkerAdapter.version_capabilities()` used package/CLI version data; `CodexWorkerAdapter.probe()` used live SDK metadata where `server_info.version` combined semantic version **and** platform/user-agent banner. `effective_capability_digest` already excluded observation time, probe labels and notes but did **not** canonicalize human-readable banner suffixes of `runtime.runtime_version`. Therefore two effective capability surfaces with the same actual version were rejected as changed.

## Corrective engineering change (research branch only)

`projectctl/workers/capability_digest.py` now canonicalizes a **strictly recognized** semantic runtime version followed by an explicitly parenthesized descriptive banner for digest computation. It still compares semantic version, prerelease/build identifiers, SDK version, adapter version, provider/runtime names and all effective capability state fields. It preserves the raw persisted version-only/live snapshots for independent audit; unknown unrecognized formats are **not normalized** (fail closed).

A new offline test module `experiments/dogfooding/test_d1_capability_version_identity.py` has **nine** tests covering the exact observed operator banner and equality, real version upgrade mismatch, prerelease/build version mismatch, SDK version mismatch, effective support mismatch, unrecognized version text and null preservation. It must be executed on the owner's machine before any new attempt; no model calls are involved in the tests. Note that version strings alone do not cryptographically authenticate a runtime binary and were not intended to do so.

No change was made to M6.0/main, quota/permissions, task safety policy, or actual SDK/CLI package versions.

## Manual owner adjudication and third attempt

The previous run is *not* to be resumed, re-verified, unilaterally marked successful, or deleted. Its durable `needs_decision/capability_changed` state is retained as a factual experimental defect result.

After the operator pulls and validates the **new** research-branch fix using nine offline regression tests plus six prior quota consistency tests, the operator can make a recorded owner decision to reopen **only** the unassigned, blocked Beads issue `d1ctl-lh4` via `bd update d1ctl-lh4 --status open --json`. This is permissible only after checking that the previous run really has `needs_decision/capability_changed`, started_at is null, no owner or live worker exists, the `ctl` repo remains clean/remote-free and no competing actor is using Beads. This deliberately does not rewrite the old ProjectCTL run state.

The one-shot manual D1-R2 script retains both old runs, requires a fresh official quota observation and same Scheduler/model/sandbox, reopens the task only after guards and tests, then performs at most one `prepare` and one `start`. It creates a unique `ctl-attempt-3` evidence directory, exits immediately on any mismatch, and never invokes `run auto`, `verify`, `integrate` or direct Codex.

**Comparative scientific interpretation:** Both prior failed attempts remain part of ProjectCTL overhead/failure rate. Any later successful work is explicitly labeled patched ProjectCTL D1-R2 and not original M6.0 functionality. One paired fixture provides feasibility information, not statistical generalization.
