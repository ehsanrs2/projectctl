# ProjectCTL

ProjectCTL is a local-first deterministic control plane for AI-assisted software engineering.

This repository currently implements **M2.0 — Bounded Autonomous Loop**, orchestrating recovery, scheduling, execution, verification, and integration under explicit stop policies.

## Implemented

### M0.1 — Contracts and schemas

- strict Pydantic schemas and versioned artifacts
- repository-safe paths and symlink-containment checks
- separate operational state and telemetry databases
- deterministic digests and public JSON Schema export
- adapter/port boundaries for task stores, importers, and quota providers

### M0.2 — Bootstrap and validation

- `projectctl init`
- `projectctl doctor`
- `projectctl schema export`
- global `PROJECTCTL_HOME`
- project/global SQLite initialization
- machine-readable `--json` output

### M0.3 — Task system integration

- Beads task-store adapter through the supported `bd --json` CLI boundary
- normalized `TaskSnapshot` generation
- `projectctl tasks --state all|ready|blocked`
- strict Spec Kit `tasks.md` parser
- one-way Spec Kit → Beads import
- `projectctl import-tasks --dry-run`
- idempotent/resumable import bindings

### M0.3.1 — Adaptive project onboarding

- one entry point: `projectctl init`
- deterministic repository classification:
  - `new`
  - `existing_unmanaged`
  - `managed_valid`
  - `managed_invalid`
- read-only `projectctl inspect`
- `projectctl adopt --dry-run`
- interactive brownfield onboarding wizard
- non-interactive fail-safe flow with exit code `16` when human input/approval is required
- preservation of existing `AGENTS.md`, nested agent instructions, skills and project docs
- knowledge bindings instead of forcing `docs/PROJECT.md`, `ROADMAP.md`, etc. on brownfield projects
- task-authority resolution without creating a second tracker silently
- adoption manifest at `.projectctl/adoption.yaml`
- Git baseline + repository fingerprint for stale-plan detection
- dirty-working-tree protection
- transaction-like apply with rollback of ProjectCTL-created local artifacts
- symlink-escape protection

No Codex worker or autonomous code-writing loop is enabled yet. M0.4 schedules and recommends resources only; it does not claim or execute tasks.

## Onboarding behavior

### New repository

```bash
projectctl init
```

ProjectCTL uses the greenfield convention and creates its minimal project structure.

### Existing repository

```bash
projectctl init
```

ProjectCTL detects the existing project, shows the discovered agent/project assets, asks whether to prepare a safe adoption plan, resolves required human decisions, shows the dry-run plan, and only applies it after approval.

Existing project files are not rewritten automatically.

For advanced use:

```bash
projectctl inspect
projectctl inspect --json

projectctl adopt --dry-run
projectctl adopt --dry-run --task-store beads --json
projectctl adopt
```

For automation/CI:

```bash
projectctl init --non-interactive
```

If human approval or an authority decision is still required, ProjectCTL exits with code `16` rather than guessing.

A reviewed brownfield plan can be applied explicitly:

```bash
projectctl init \
  --non-interactive \
  --yes \
  --task-store beads
```

Use `--allow-dirty` only after reviewing the plan when the working tree contains uncommitted changes.

## Brownfield knowledge bindings

ProjectCTL does not require an existing project to reorganize its documentation.

For example, an adopted repository can bind:

```yaml
knowledge:
  project_overview:
    sources:
      - README.md
  roadmap:
    sources:
      - docs/roadmap.md
  constraints:
    sources:
      - CONTRIBUTING.md
  architecture:
    sources:
      - docs/architecture.md
```

Greenfield repositories still use ProjectCTL's conventional defaults.

## Agent instructions

Existing `AGENTS.md` and nested `AGENTS.md` / `AGENTS.override.md` files are discovered and preserved. ProjectCTL does not merge, append to, or rewrite them during adoption.

## Task authority

Exactly one execution-state authority should be configured per project.

M0.3 implements the Beads adapter. Brownfield onboarding can record an existing GitHub task workflow or defer task-store selection, but those states remain unavailable for scheduling until the corresponding adapter/decision exists.

When `task_store.provider: beads`, Beads is the execution-state authority. Spec Kit `tasks.md` remains a one-way planning/import artifact.

## Development

```bash
uv sync --extra dev
uv run pytest
uv run python -m compileall -q projectctl
uv run projectctl --help
```

Without installing the package, development tests also work directly:

```bash
pytest
PYTHONPATH=. python -m projectctl --help
```

## M0.4 — Resource & Scheduling Core

M0.4 adds a deterministic, read-only scheduling layer. It does **not** claim tasks or execute Codex yet.

```bash
# Record a global account quota observation (ratios or percentages are accepted)
projectctl quota set --five-hour 60% --weekly 40% --project /path/to/repo

# Inspect the current quota mode and reserve-adjusted effective budget
projectctl quota --project /path/to/repo

# Recommend the next eligible task without claiming it
projectctl next --project /path/to/repo

# Explain exclusions, score components, quota mode, and model/reasoning recommendation
projectctl explain-next --project /path/to/repo
```

Scheduling is snapshot-first and deterministic: ProjectCTL captures the task state, reads the account-scoped quota snapshot, evaluates eligibility before scoring, applies stable tie-breaking, and records the resulting decision as telemetry. Unknown or stale quota enters conservation mode; only trivial/small work is auto-eligible until a fresh observation is available.

Model routing uses logical profiles (`economical`, `balanced`, `strong`, `deep`) rather than hard-coded model names. M0.4 only recommends a profile and reasoning level; worker execution is a later milestone.


## M0.5 — Project State & Milestone Awareness

M0.5 adds a small Git-versioned, human-editable state contract at `docs/PROJECT_STATE.yaml`. ProjectCTL does not infer the active milestone from prose.

```bash
# Inspect structured state
projectctl state

# Record the current goal and active milestone
projectctl state set \
  --goal "Complete the deterministic control plane" \
  --milestone M0.5 \
  --milestone-title "Project State & Milestone Awareness" \
  --alias "Project State"

# Read a live project summary without materializing dashboards
projectctl status

# Materialize generated, non-authoritative dashboards
projectctl refresh
```

`projectctl refresh` writes:

- `docs/generated/STATUS.md`
- `docs/generated/BUDGET.md`
- `docs/generated/TASKBOARD.md`

Each generated file carries a source digest. `projectctl doctor` warns when those dashboards are missing or stale.

Scheduler milestone relevance is now deterministic: a task receives milestone relevance only when its milestone exactly matches the active milestone id, title, or an explicit alias after case/whitespace normalization. No fuzzy or LLM-based inference is used.

`SchedulerDecision` is schema version 2 and records the `project_state_digest` because structured project state is now a decision input.


### Beads milestone metadata

When Beads is the task authority, ProjectCTL uses one explicit metadata convention:

```text
milestone:<id>
```

For example, a task associated with the active M0.5 milestone carries:

```text
milestone:M0.5
```

ProjectCTL does not infer milestone membership from issue titles, phases, epics, or unrelated labels. If multiple conflicting `milestone:` labels are present, milestone scoring is disabled for that task and a normalization note is recorded. New Spec Kit tasks imported while an active milestone is set receive the corresponding Beads label. The import plan also records a project-state digest, so a milestone change between preview and apply invalidates the plan.


## M1.0 — Execution Contracts

M1.0 freezes the execution boundary before autonomous task execution is enabled.

New versioned contracts include:

- `ExecutionPlan v1`
- `WorkerRequest v1`
- `WorkerResult v1`
- `WorkerCheckpoint v1`
- `RunManifest v2`
- `ContextManifest v2`
- `VerificationManifest v1`
- `EvidenceManifest v1`

Legacy `RunManifest v1` and `ContextManifest v1` remain readable for audit compatibility.

The default execution policy is intentionally restrictive:

```text
sandbox: workspace_write
network: disabled
approval: deny_all
worker commit/merge/rebase/push: forbidden
```

M1.0 still performs no Codex execution, task claim, integration, or task completion. Those capabilities are implemented incrementally in M1.1–M1.4.


## M1.1 — Claim + Run Store + Isolated Worktrees

M1.1 adds durable execution preparation without starting a worker.

```bash
# Upgrade an existing M0.x/M1.0 project state database explicitly.
projectctl migrate --project /path/to/repo

# Prepare the scheduler-selected task:
# - requires a clean primary worktree
# - revalidates plan inputs
# - atomically claims the task
# - creates an isolated ProjectCTL run branch/worktree
projectctl run prepare --project /path/to/repo

# Inspect durable run state and events.
projectctl runs --project /path/to/repo
projectctl run show RUN_ID --project /path/to/repo

# Release a prepared claim and remove its isolated worktree.
projectctl run abort RUN_ID --project /path/to/repo
```

Project state SQLite is now schema v2. Upgrades are never performed implicitly on normal reads or repeated init. `projectctl migrate` creates a consistent SQLite backup before applying v1 → v2.

Each run branch is named `projectctl/run/<run-id>` and its worktree lives outside the repository under `$PROJECTCTL_HOME/worktrees/<project-instance-id>/<run-id>/`.

M1.1 still starts no Codex worker. A successfully prepared run ends in `claimed`, ready for M1.2.


## M1.2a — Codex Capability & Strategy Layer

M1.2a makes worker capabilities explicit before the Codex execution adapter is enabled.

```bash
# Inspect the installed/provider capability surface without starting a worker.
projectctl worker capabilities --provider codex
projectctl worker capabilities --provider codex --json

# Explain the strategy requested for a task and whether the current
# runtime + adapter surface can actually execute it.
projectctl worker strategy TASK_ID --project /path/to/repo
```

Capability snapshots distinguish **runtime support** from **ProjectCTL adapter support**. A Codex feature is usable only when both are supported. Provider features are therefore never silently treated as ProjectCTL features.

Strategies are selected by the ExecutionPlanner layer, not the Scheduler:

- `direct`: Default mode + workspace-write
- `plan_then_execute`: Plan mode in read-only, then Default mode in workspace-write
- `goal`: persistent Goal execution with an explicit turn/time/stop budget
- `review`: Default mode constrained to read-only

Planning is always bound to a read-only sandbox. Plan mode itself is not treated as a security boundary.

Strategy fallback is fail-closed. Goal → Plan or Plan → Direct fallback happens only when an explicit fallback policy allows it.

The Codex optional dependency is pinned for reproducibility:

```bash
pip install -e ".[codex]"
```

M1.2a performs only capability discovery and strategy negotiation. It still does not start a Codex worker. M1.2b will add ContextAssembler, live capability probing, and the actual Codex WorkerAdapter.


## M1.2b — Context + Codex WorkerAdapter

M1.2b enables the first real worker execution path.

```bash
# Prepare a run. Many Beads tasks still have unknown resource metadata,
# so an explicit direct strategy is useful until richer task metadata lands.
projectctl run prepare --strategy direct

# Start the already-claimed worker in its isolated worktree.
projectctl run start RUN_ID

# Inspect the installed adapter/runtime surface without running a task.
projectctl worker capabilities

# Start the Codex runtime and verify the live surface.
projectctl worker capabilities --live
```

The context assembler writes deterministic control-plane artifacts under:

```text
.projectctl/runs/<run-id>/
├── execution-plan.json
├── worker-capabilities.json
├── worker-strategy.json
├── worker-capabilities-live.json
├── context-manifest.json
├── worker-request.json
└── worker-result.json
```

Context manifests record paths, roles/scopes, and digests. Project documentation and specs are not copied wholesale into prompts. The worker reads relevant paths from the isolated worktree.

Task/spec content is delivered to Codex as an `ExternalMessage`, while ProjectCTL execution restrictions are developer instructions. Repository content therefore cannot grant itself additional authority.

M1.2b uses the documented high-level `openai-codex` SDK for real execution:

- persistent Codex thread
- explicit `ApprovalMode.deny_all`
- explicit `Sandbox.read_only` or `Sandbox.workspace_write`
- workspace-write network access explicitly disabled
- structured `WorkerOutputPayload`
- external/untrusted task message
- configured reasoning level
- isolated worktree cwd

The stable adapter currently executes:

- `direct` — Default mode + workspace-write
- `review` — Default mode + read-only

Native Codex Plan collaboration mode and Goal operations remain modeled and visible but are **not emulated** through prompts. Their current APIs live outside the documented high-level execution surface used by this adapter, so they remain fail-closed until a dedicated adapter bridge is implemented.

A worker returning `implemented` moves the run only to `VERIFYING`. ProjectCTL does not trust the worker's own success claim. M1.3 performs independent diff/test/evidence verification.

ProjectCTL also compares Git HEAD before and after worker execution. Any worker-created commit, rebase, merge, or other history mutation fails the run with `unexpected_git_history`.


## M1.3 — Verification + Evidence

M1.3 makes successful execution evidence-driven.

```bash
# Inspect the authoritative verification profile.
projectctl verification profile --project /path/to/repo

# Verify a worker-completed run.
projectctl run verify RUN_ID --project /path/to/repo
```

Verification is independent from the worker. `WorkerResult.suggested_verification` remains advisory and is never executed as authority.

Verification policy comes from the human-managed `projectctl.verification.yaml` catalog when present. If the catalog is absent, ProjectCTL only uses a small deterministic built-in resolver for conventional Python-with-tests, npm-test, Go, or Cargo projects. If no safe profile can be resolved, verification fails closed.

The M1.3 verification pipeline is:

```text
VERIFYING
   ↓
Diff / ownership policy
   ↓
Configured commands (argv, no shell)
   ↓
Workspace stability check
   ↓
ProjectCTL candidate commit
   ↓
VerificationManifest v2
   ↓
EvidenceManifest v2
   ↓
READY_TO_INTEGRATE
```

Workers cannot define their own required verification commands. Required checks must come from the verification profile.

System-protected paths include ProjectCTL operational state, evidence/generated output, AGENTS instruction files, Project State, specs, architecture decisions, and the verification catalog itself. Profiles can add additional protected paths but cannot remove these system invariants.

Verification command stdout/stderr is written under `.projectctl/runs/<run-id>/verification/`; manifests store digests rather than embedding logs.

A verification command may not silently rewrite the candidate. ProjectCTL snapshots the workspace before commands and verifies the tracked/untracked state and Git HEAD are unchanged afterward. If a verifier mutates tracked state, the run fails.

Only after all required checks pass does ProjectCTL stage the worker changes and create a single-parent candidate commit directly on the run base. The commit is created by ProjectCTL with hooks/signing disabled; workers remain forbidden from committing.

Passing implementation runs move to `READY_TO_INTEGRATE`. Review-mode runs must leave the worktree unchanged and can finish as `PASSED` with the base commit recorded as their candidate reference.

Failed and policy-blocked runs also receive `EvidenceManifest v2`, with `candidate_commit: null`, so rejection is auditable as well as acceptance.


## M1.4 — Integration + Recovery

M1.4 integrates only previously verified candidate commits and reconciles crash windows without re-running untrusted work implicitly.

```bash
# Integrate a verified run into its recorded target branch.
projectctl run integrate RUN_ID --project /path/to/repo

# Reconcile a stale/crashed run from durable state.
projectctl run recover RUN_ID --project /path/to/repo
```

Integration is intentionally **fast-forward-only**. The primary worktree must be clean and have the recorded integration target checked out. If the target has advanced beyond the execution base, ProjectCTL does not rebase or merge the verified candidate: the run moves to `NEEDS_DECISION / STALE_BASE`, because rebasing would create code that the existing EvidenceManifest did not verify.

Before integration, ProjectCTL revalidates the evidence chain:

- WorkerResult digest
- VerificationManifest digest
- verification-profile digest
- candidate single-parent relationship
- actual candidate diff digest
- clean verified worktree
- candidate HEAD identity

The integration order is crash-recoverable:

```text
READY_TO_INTEGRATE
        ↓
INTEGRATING
        ↓
git merge --ff-only candidate
        ↓
close canonical task with evidence reference
        ↓
PASSED
        ↓
remove ProjectCTL run worktree/branch
```

No push is performed by M1.4.

If a crash happens after the Git fast-forward but before task closure or run finalization, `projectctl run recover` observes that the target already equals the verified candidate, completes the canonical task idempotently, records/finalizes integration, and cleans up the run worktree.

Recovery also reconciles a durable implemented WorkerResult left in `RUNNING` to `VERIFYING`, and a passing EvidenceManifest left in `VERIFYING` to `READY_TO_INTEGRATE`. A crashed worker without a durable trustworthy result is not automatically resumed; it moves to `NEEDS_DECISION / RECOVERY_UNSAFE`.

A live, unexpired lease is never stolen by recovery.


## M1.4.1 — Production Hardening Before M2

An end-to-end M1 design review identified four races that must be closed before autonomous `run --auto` orchestration is safe.

### Run lease heartbeat

Worker execution and verification may run longer than the default five-minute lease TTL. Long synchronous operations now keep their lease alive with a periodic heartbeat.

If heartbeat renewal fails, the old owner fails closed and must stop mutating run state. A newly recovered owner therefore cannot race the original process.

### Serialized integration

Per-run leases do not protect the shared integration target from two different runs. All target-branch integration now also acquires a project-wide `integration` lock.

### Canonical task reconciliation

Terminal run state and task authority must agree:

```text
FAILED / CANCELLED / ABANDONED
        ↓
release canonical task for retry

NEEDS_DECISION / BLOCKED_POLICY
        ↓
unassign canonical task
        ↓
mark blocked for human decision
```

If task-store reconciliation itself fails, the run escalates to `NEEDS_DECISION / RECOVERY_UNSAFE` instead of silently leaving a stranded in-progress task.

Recovery also reconciles terminal runs created before this rule.

### Crash-safe project locks

Project locks now contain host, PID, token, and acquisition metadata. A dead lock owned by a dead PID on the same host may be reclaimed. Live locks, malformed locks, and locks from another host remain fail-closed.

Lock cleanup is token-checked so one process cannot delete a lock that has already been reacquired by another owner.

These changes do not add any M2 autonomous behavior; they strengthen the M1 invariants that M2 will rely on.


## M2.0 — Bounded Autonomous Loop

M2.0 introduces a bounded autonomous orchestrator over the complete M1 lifecycle.

```bash
projectctl run auto --project /path/to/repo

# Permit more than one task attempt in the same invocation.
projectctl run auto --max-tasks 3 --project /path/to/repo
```

The default is intentionally `--max-tasks 1`. Raising the bound is an explicit operator decision.

Each autonomous iteration performs a fresh control-plane evaluation:

```text
unfinished run?
   ├─ yes -> recover/resume deterministic phase
   └─ no
        ↓
fresh project state + task snapshot + quota snapshot
        ↓
quota stop policy
        ↓
scheduler
        ↓
prepare
        ↓
worker
        ↓
verification
        ↓
integration
        ↓
fresh project state + quota snapshot
        ↓
material-change check
        ↓
next iteration or typed stop reason
```

The loop is project-serialized with the crash-safe `auto-loop` lock. It will not compete with another live run lease and fails closed if multiple active runs already exist.

Typed stop reasons include quota stale/critical, no eligible task, all work complete, policy block, human decision, active/multiple run conflict, recovery required, retry-budget exhaustion, material project-state change, and the explicit max-task bound.

Retry is conservative. Only infrastructure/timeouts/worker transport/claim/stale-context style failures are eligible, and only within `max_attempts_per_task`. Verification failures, policy blocks, unexpected Git history, and human-decision states do not auto-retry.

If the structured Project State changes while a task is executing, autonomous continuation stops by default after the current task. This is the M2 material-change boundary; the next invocation replans from the new intent.

Quota checkpoints currently re-read the configured ProjectCTL quota provider. The current provider is still manual, so M2.0 does not invent usage estimates or claim live provider accounting. The bounded task cap is therefore part of the safety contract until automatic quota accounting is added.

Every invocation writes an audit artifact under:

```text
.projectctl/auto/auto-<id>.json
```

using `AutoRunReport v1`.
