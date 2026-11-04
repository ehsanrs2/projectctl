# Post-D2 lifecycle inspection and timing

This feature-branch implementation follows ADR-041. It does not authorize a live
experiment or any stage against historical D2 fixtures.

## Inspection and handoff

```
projectctl run audit RUN_ID --project /path/to/project --json
projectctl run audit RUN_ID --project /path/to/project --measurements /path/to/metrics.json --json
```

Audit creates no project files, locks, task transitions or quota observations.
Output omits prompts, task text, accounts, thread IDs and transcripts. Sources
are represented by checks and digests. `observed` means the stated check passed
against the sampled durable source; it does not mean verified readiness or an
atomic snapshot. `missing`, `not_applicable`, `unknown`, and `inconsistent` have
distinct meanings. Local integration does not establish remote publication.
Recorded cleanup makes removal of the old worktree expected.

The report's `permitted_action` is always `inspect`. A `proposed_stage`, when
present, names an existing command for a separate owner decision. No command is
executed or implicitly approved. Recheck the live claim, lease, quota, scope,
execution inputs and exact candidate using the existing entrypoint under its
normal authority gates after obtaining that decision. This document grants none
of those approvals.

An uncertain worker start/resume, an active or stale lease marker, missing
evidence, a changed target or a candidate mismatch requires bounded read-only
inspection first. Do not retry on the basis of missing stdout or a pending
measurement file. Recovery is a new owner decision and uses existing ProjectCTL
recovery semantics; audit never calls recovery. A future dispatcher would need
separate explicit approval and durable exclusive intent before each stage.

## Source support

The current SQLite reader supports bounded rollback-journal sources only.
Live-WAL header sources are explicitly unsupported and report unknown status;
they cannot produce a stage suggestion. Audit does not change journal mode or
copy/repair a live database. Do not change a real Run's database journal mode to
make this report pass. Synthetic tests use disposable rollback-journal fixtures.
The existing M6 Seal and coherent snapshot work remains separate.

DB and artifact rereads detect ordinary drift but are not an atomicity proof.
Git checks use optional locks disabled, stored identity and the manager's path
contract. They do not create the manager's storage directory. Git porcelain is
read as bytes without trimming its significant leading status blank. A verify
preview requires observed HEAD at the frozen execution base when no candidate
exists. Clean porcelain is reported as observed; dirty pre-verification worker
changes are reported as `worktree_clean: not_applicable` with reason
`dirty_workspace_pending_verification`, not as proof of cleanliness. These
changes do not block verify previews or checkpoint-bound resume previews; start
and integrate retain their existing cleanliness gates. Parent
artifact hashes use canonical model digests, while source file SHA-256 values
describe bytes. Event payloads are inspected for available digest links and
structural/time-order inconsistencies; an unauthenticated historical event log
cannot establish absence of dispatch or detect every coordinated alteration.
No Beads or other task provider is contacted; task-provider state stays unknown.

## Optional capture on a separately authorized stage

The existing `run start`, `run resume`, `run verify`, and `run integrate` commands
accept `--measurements PATH`. This is an option on existing actions, not an
inspection command. It requires the same separate stage authorization as before.
No such command has been run on a real fixture for this implementation.

The caller supplies a new file in an existing directory. Capture exclusively
creates it with mode 0600 and fsyncs a pending envelope before the existing
command runs. A duplicate file fails before the action. Final telemetry includes
an invocation ID, Run ID, stage and UTC observation timestamps. Abrupt death can
leave pending or incomplete JSON; this is unknown telemetry, not safe-retry
evidence. Do not delete it to retry an uncertain operation. The artifact is not a
dispatch journal and cannot replace future exclusive dispatch intent.

Python callers may use `capture_measurements()` for in-memory capture or
`measurement_artifact(path, run_id=..., stage=...)` around an already-authorized
existing operation. Neither helper dispatches anything itself.

## Source-to-metric map

All precise elapsed values are integer nanoseconds from `time.monotonic_ns`
within one synchronous call. No duration is calculated from wall timestamps.
Nested boundaries overlap; do not sum them or label their difference pure model
time. UTC envelope timestamps establish observation provenance only; audit
rejects reversed or naive timestamps for comparisons.

| Boundary | Source | Meaning and limits |
| --- | --- | --- |
| `sdk_turn_call` | adapter calls to `thread.run` or `turn.run` | SDK-call elapsed time, including tools, transport and waiting; excludes thread creation/resume setup and structured-result parsing; not pure model/GPU time |
| `worker_pre_dispatch_contract` | `_load_admitted_execution_contract` | Exact admitted execution-contract load/validation call; other preflight, context assembly and admission time is not separately measured |
| `worker_start_handling` | `start_prepared_run` | Whole existing start entrypoint, including preflight, SDK work, post-processing and cleanup |
| `worker_resume_handling` | `resume_checkpointed_run` | Whole existing resume entrypoint; overlaps SDK and post-processing spans |
| `worker_post_dispatch` | `_finalize_worker_outcome` | Existing outcome finalization, including WorkerResult/checkpoint handling and independent Git/policy checks |
| `independent_verification` | `verify_run` | Whole independent verification entrypoint, including policy, command wall time, candidate/evidence creation and cleanup; not just test-process time |
| `integration_work` | `integrate_run` | Whole integration entrypoint, including its normal guards, Git work, task reconciliation and cleanup; does not imply remote publication |

Errors and keyboard interruption preserve the original control flow and record
only an outcome enum. A process killed before the finally block cannot yield a
completed measurement. Disabled capture does not call the measurement clock.

## SDK usage provenance

Offline inspection used installed `openai-codex==0.160.0`:
`openai_codex/_run.py:TurnResult` and its turn-result collector, and generated
`ThreadTokenUsage` / `TokenUsageBreakdown`. The collector retains the last usage
notification matching the requested turn ID. `usage` can be absent.

The report preserves SDK `last` and `total` scopes; it does not rename them
per-ProjectCTL-operation totals or difference thread totals across resumes.
Each scope exposes `input_tokens`, `output_tokens`, `cached_input_tokens`,
`reasoning_output_tokens`, and `total_tokens`. Cached input and reasoning output
are subsets and are never added again. Counts are not summed across operations.
Cache-write and model-context-window fields are deliberately not captured.
Missing, malformed, negative and boolean counters remain explicit unknowns.
An unverified SDK version is unsupported for usage comparisons. No private
transcript, messages, raw SDK object serialization or account usage API is used.

There is no cost estimate, model-only timing, cross-arm performance conclusion,
authenticated execution proof, or live qualification in these measurements.
