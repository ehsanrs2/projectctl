# Post-D2 engineering goal — lifecycle observability and safe handoff

**Status:** DESIGN_AND_OFFLINE_IMPLEMENTATION_AUTHORIZED. No new paid model turn,
live task claim, Prepare, Start, Resume, Verify, Integrate, Merge, or
publication is authorized by this document.

**Branch:** `research/advisory-skills-eval` only. The completed, isolated
D2 Direct/CTL fixtures and all prior one-shot evidence are immutable.
Do not run an experiment on either of them.

## Motivation

D2 reached `RunStatus.PASSED` through an isolated local Integration and
closed the canonical Beads task, with 26/26 tests passed on both arms. However,
two earlier CTL Prepare-admission blocks, multiple manual preflight/inspection
scripts, uncertain/repetitive human gates, and missing SDK usage accounting
made it difficult to attribute operational cost and compare with Direct.

ProjectCTL **already has** `projectctl/application/auto.py`,
`projectctl/application/turns.py`, `projectctl/application/recovery.py`,
`RunStore`, `WorkerResult`, independent Verification and task lifecycle.
Do **not** implement an alternative scheduler, auto-runner, recovery engine,
or a second source of truth for Run status.

## Objective: one bounded engineering change

Build a reusable, strictly **read-only by default** lifecycle audit/snapshot
interface and improve Worker timing/usage instrumentation where supported.
Output should make it easy for an owner to inspect one Run and know:

1. What is observed now, and which durable source proves it;
2. Whether the Run is safe for a **separately approved** action;
3. What action, if any, has already been dispatched (including uncertain
   outcomes), with no inference from missing stdout;
4. Which phase durations and non-sensitive token counters were **actually**
   measured, and which are unknown;
5. Which data are missing or stale, and what bounded, non-mutating
   reconciliation inspection is appropriate.

### A. Observability / diagnostics

Implement a versioned, deterministic JSON snapshot for an existing run
(using a CLI view/command matching current Typer conventions). It must read
existing RunStore, ExecutionPlan, WorkerResult, Verification/Evidence/
Integration artifacts and stage events and cross-check identities/hashes
when available. Distinguish:

- `observed` (verified durable evidence), `missing`, `not_applicable`,
  `unknown` and `inconsistent`;
- no previous action vs an action possibly dispatched but outcome unknown;
- local Integration vs remote publication; Beads task status as evidence,
  never as a substitute for verified RunStore state;
- a valid ready-to-integrate candidate vs already-integrated/cleaned-up
  Worktree (do not flag expected post-Integration removal as corruption).

Never mutate the Run, perform task claim, run `bd` write commands, call
`run_auto`/`advance_non_worker_phases`/`recover_run` as part of a
read-only report, run Git cleanup, refresh live quota or request inference.
Do not depend on a fixed project_instance_id or on flat worktree layouts:
use the stored worktree identity and the ProjectCTL manager's path contract.

### B. Timing and usage

Record bounded, source-attributed **monotonic** durations at well-defined
execution boundaries without changing worker behavior. In particular,
separate SDK/model turn duration, ProjectCTL pre/post dispatch handling
where measurable, independent Verification wall and integration work; never
subtract unmatched wall-clock timestamps and label the result precise
model time. Retain old schema compatibility; add a versioned, optional,
non-sensitive measurement artifact if appropriate instead of silently
changing `WorkerResult` v1.

Inspect the pinned installed `openai-codex` SDK result shape and repository
adapter tests offline before choosing any token capture. Record only values
exposed by the actual runtime (input/output/cached/reasoning *as separately
defined fields*); cached and reasoning counters are subsets and must not
be added twice. Persist explicit `unknown` / reason if absent. Do not
parse private transcripts, fabricate SDK fields, or attach raw prompts,
messages or credentials. Validate timestamp and measurement provenance
for any comparison report.

### C. Single-shot owner handoff (no live dispatch here)

Produce a narrow CLI-oriented preview/handoff or library helper that reports
the exact permitted next action with fail-closed guards. If future stage
dispatch is implemented, it must require **separate explicit owner approval**
and a durable, exclusive intent marker *before* dispatch. Once there is
a dispatch attempt or uncertainty, ordinary retry is prohibited; only
read-only status/evidence reconciliation is allowed, with a new owner
decision for recovery. Do not silently auto-approve the next stage.

Reuse existing ProjectCTL entrypoints and lease/claim semantics; avoid a
second state machine or mutable global consent token. This goal is not
authorization to execute stage actions against any real or historical D2
fixture.

## Engineering constraints

- Keep production defaults unchanged; new behavior opt-in and
  backward-compatible, including unchanged exit semantics for existing
  commands.
- No sensitive payload logging. Snapshot output must avoid raw Codex
  prompts, threads, stdout/stderr transcripts, quota/account details
  and task text; show only safe identifiers, checks, derived counts,
  timing/usage provenance and artifact digest metadata.
- Read-only mode must not create observation directories or emit
  mutable manifests in the project. Synthetic tests may use temporary
  disposable repositories/SQLite copies and stub SDK results.
- Never re-run any D2 paid worker, Prepare, Verify, Integrate, or mutate
  the original completed Direct/CTL evidence. No `git pull` into
  historical fixture, `run recover`, remote push, or publish.
- No change to task selection/quotas, verified Candidate hash,
  integration policy, Provider scheduler, or Beads claim/close logic.
- If any SDK field/behavior is not inspectable offline, stop that
  subfeature with a precise limitation rather than guessing.

## Required verification

- Synthetic tests for all legal Run statuses: claimed, running,
  checkpointed, verifying, ready_to_integrate, passed, failed,
  blocked, needs_decision.
- Both pre-Integration and post-Integration clean-up cases;
  mismatch of Run/Evidence/Candidate and tampered logs must fail closed.
- Durable dispatch intent: duplicate invocation, interrupted command,
  ambiguous stdout, active lease, stale target and candidate drift
  must never silently authorize retry.
- Verify read-only snapshot leaves RunStore event count, Beads task,
  Git HEAD/status and evidence files unchanged. Include a test guarding
  against a regression to parsing Git porcelain with `str.strip()`
  (leading status blank is significant).
- Fake SDK with available token usage, SDK without usage, interruption,
  error, and checkpoint; preserve correct attribution and `unknown`.
- Existing relevant test suites pass. Make a scoped commit only on
  `research/advisory-skills-eval` with code, tests and brief operational
  docs; no production default-branch integration.

## Exit / deliverables

1. Source changes and tests on research branch, with clean worktree and
   exact commit SHA.
2. Example **sanitized** JSON snapshot using synthetic fixtures only.
3. A source-to-metric map documenting precise timing boundaries and
   which usage fields are available or unknown.
4. An operator runbook clearly distinguishing inspection/preview,
   separately authorized stage dispatch, and read-only reconciliation.
5. Test transcript, explicit failures/limitations and next safe gate.
6. End in `OFFLINE_QUALIFIED__LIVE_EXPERIMENT_NOT_AUTHORIZED` only if
   offline tests and read-only invariants pass; otherwise use
   `BLOCKED_WITH_EVIDENCE`.

The eventual D3 experiment is a **separate later study** with its own
frozen tasks and approvals. Do not launch it from this goal.
