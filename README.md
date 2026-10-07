# ProjectCTL

ProjectCTL is a local-first deterministic control plane for AI-assisted software engineering.

The **Post-M4 Architecture Review** is complete. M4.0–M4.1 safety primitives are implemented, and the active milestone is now **M4.2a — Execution Input Contract Unification**.

For the canonical product vision, authority map, architecture invariants, current reality check, and roadmap, read **`docs/PROJECTCTL_BLUEPRINT.md`**. `docs/PROJECT_STATE.yaml` remains the only authority for the active goal and milestone.

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

Beads is currently a full execution-capable task authority.

GitHub Issues now implements the current full task lifecycle under ProjectCTL's direct-publication policy: read, claim/release, decision blocking, publication-gated completion, and recovery. Repositories that require PR-only delivery remain fail-closed until an explicit PR publication mode is implemented.

Inspect the configured adapter capability surface with:

```bash
projectctl task-authority --project /path/to/repo
projectctl task-authority --project /path/to/repo --json
```

Spec Kit `tasks.md` remains a one-way planning/import artifact and is not allowed to create a parallel Beads tracker when another task authority is configured.

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


## M2.1 — Automatic Codex Quota Provider

M2.1 removes the manual-only quota limitation from M2.0 without weakening its bounded
autonomous safety contract.

Quota provider selection is account-global:

```bash
projectctl quota provider --project /path/to/repo
projectctl quota provider --set codex_app_server --project /path/to/repo
projectctl quota provider --set manual --project /path/to/repo
```

When `codex_app_server` is selected, normal status/scheduling/auto evaluations obtain a
fresh observation through the supported `codex app-server` JSON-RPC interface and
`account/rateLimits/read`.

ProjectCTL identifies five-hour and weekly windows by their reported duration (300 and
10080 minutes), not by primary/secondary position. It prefers the explicit shared
`codex` bucket when present and never infers model applicability from display names or
opaque bucket IDs.

`ordinaryUsageAllowed=false` is authoritative and places quota in critical mode.
Provider/runtime failures become an unknown stale snapshot in scheduling paths, so M2.0
stops rather than inventing available budget. `projectctl doctor` probes the configured
provider separately and distinguishes temporary unavailability from malformed/unsafe
protocol data.

Successful official observations are persisted in the existing global ProjectCTL account
database. Manual quota remains supported. M2.1 does not predict per-task token cost,
remove `--max-tasks`, or call private OpenAI endpoints.


## M2.2 — Budget-aware Checkpointing & Graceful Quota Stop

M2.2 closes the remaining quota gap inside long worker turns.

A checkpoint-aware Codex turn is monitored against fresh account quota while it runs.
ProjectCTL requests a graceful interrupt when quota becomes stale/critical or the
remaining effective budget no longer satisfies the current task's resource class.

```text
RUNNING Codex turn
      ↓
periodic live quota observation
      ↓
budget still fits task? ── yes ──> continue
      │
      no
      ↓
TurnHandle.interrupt()
      ↓
WorkerCheckpoint v2
      ↓
RUNNING + durable checkpoint + preserved partial worktree
      ↓
fresh quota later
      ↓
thread_resume(original_thread_id)
      ↓
continue same task
```

Checkpoint artifacts bind the provider thread to the exact run, context, complete worker
request, quota snapshot, base commit, and partial workspace digest. Git-history changes remain forbidden. External
changes to the checkpointed workspace fail closed instead of being silently incorporated.

Operators can resume explicitly:

```bash
projectctl run resume RUN_ID --project /path/to/repo
```

The autonomous loop also resumes an intact checkpoint before scheduling new work. If
quota is still insufficient, it exits cleanly with `quota_checkpointed`; this is a
planned budget stop, not a worker failure.

Checkpointed runs may also be explicitly aborted with the existing
`projectctl run abort RUN_ID` command.

M2.2 keeps the bounded `--max-tasks` contract and does not estimate future token cost.


## M3.0a — GitHub Issues Reader & Authority Discovery

M3 begins the external team/project-management integration layer. The first slice adds a
real GitHub Issues reader without weakening the execution claim boundary.

Brownfield onboarding can detect a github.com `origin` and pin the repository identity:

```yaml
task_store:
  provider: github
  repository: owner/repo
```

The repository can also be supplied explicitly:

```bash
projectctl adopt /path/to/repo \
  --task-store github \
  --task-store-repository owner/repo \
  --dry-run
```

GitHub authentication remains owned by the GitHub CLI. ProjectCTL calls
`gh api --hostname github.com`; it does not persist a GitHub token.

Repository identity is part of **ProjectConfig v2**. Existing v1 configs remain readable
and are upgraded only in memory; ProjectCTL does not rewrite them automatically.
Onboarding inspection/plan/manifest contracts are likewise versioned to v2 while their
v1 forms remain available for audit compatibility.

Supported read paths include:

```bash
projectctl tasks --project /path/to/repo
projectctl next --project /path/to/repo
projectctl explain-next --project /path/to/repo
projectctl status --project /path/to/repo
```

GitHub Issues metadata can be expressed with labels such as
`type:feature`, `priority:p1`, `resource:small`, `risk:high`,
`info-gain:3`, and `projectctl:blocked`. Native GitHub milestones are also
normalized into ProjectCTL milestone metadata.

Conflicting scheduling labels fail closed to `needs_decision`.

### Deliberate M3.0a boundary

GitHub-backed execution is **not** enabled yet. `projectctl run prepare` rejects a
GitHub task authority before creating any durable run state.

Likewise, Spec Kit import refuses to silently create a Beads tracker when GitHub is the
configured authority.

M3.0b owns the concurrency-safe GitHub write protocol for claim/release/block/complete.
Only after that protocol is verified should autonomous execution mutate GitHub Issues.


## M3.0b1 — Task Authority Capability & Resolver Layer

M3.0b1 removes historical task-provider branching from the application lifecycle.

The application layer now resolves one provider-neutral Task Authority exposing:

- task reader/snapshot
- claim/release capability
- decision-blocking capability
- completion capability

`TaskAuthorityCapabilities v1` makes those operations explicit and machine-readable.

Current adapter support:

| Provider | Read | Claim | Release | Block | Complete | Execution-ready |
| --- | --- | --- | --- | --- | --- | --- |
| Beads | supported | supported | supported | supported | supported | yes |
| GitHub | supported | supported | supported | unsupported | unsupported | no |

Capability inspection does not require the provider runtime to be installed or authenticated. Runtime health remains a separate concern.

An architecture test prevents `projectctl/application/*.py` from importing Beads or GitHub task implementations directly.

### Why GitHub execution is still disabled

The architecture review found two distinct missing contracts:

1. claim ownership requires a remote CAS primitive rather than issue labels/assignees;
2. M1.4 integrates locally but does not push, so a GitHub issue must not be closed before required remote publication is observed.

M3.0b2 resolves the first item with an exact remote Git-ref lease. The second remains the M3.0c boundary.

Therefore the sequence is deliberately:

```text
M3.0b1 provider-neutral lifecycle boundary
    ↓
M3.0b2 concurrency-safe GitHub remote claim
    ↓
M3.0c remote publication + GitHub completion
```

See ADR-012 and `docs/PROJECTCTL_BLUEPRINT.md` for the full rationale.


## M3.0b2 — GitHub Remote Claim Protocol

M3.0b2 adds concurrency-safe claim and release semantics for GitHub task authority without
pretending that remote completion is solved.

For issue `gh-42`, ProjectCTL reserves:

```text
refs/heads/projectctl/claims/issue-42
```

The ref points to a unique marker commit bound to one `TaskClaimRequest v1`. It contains no
source changes and has the execution base as its parent.

Acquisition uses an absent-only Git lease:

```text
git push --force-with-lease=<claim-ref>: origin <marker-sha>:<claim-ref>
```

Release uses the exact observed ownership SHA:

```text
git push --force-with-lease=<claim-ref>:<ownership-sha> origin :<claim-ref>
```

This means a delayed/stale runner cannot delete a claim that another runner acquired later.
A successful exact-SHA delete remains successful even if another runner immediately reacquires the
ref before ProjectCTL's follow-up observation.

Before claiming, ProjectCTL also requires:

- `origin` to represent the configured GitHub repository
- the remote integration-target branch to exist
- that remote target to equal the exact execution base

After claim acquisition, ProjectCTL revalidates the execution-plan inputs again before creating the
worktree, closing the race between preflight and distributed ownership acquisition.

Every new run writes `task-claim-request.json` and `task-claim.json`; their digests are anchored
in the append-only run event stream. Abort/retry release therefore uses exact durable ownership
evidence rather than only a task id.

Pre-M3.0b2 Beads runs remain releasable when both new claim artifacts are absent. GitHub never
allows that legacy fallback.

### GitHub remains non-executable

After M3.0b2 the GitHub adapter reports:

```text
read                 supported
claim                supported
release              supported
block_for_decision   unsupported
complete             unsupported
```

The current lifecycle requires all of those operations, so `run prepare` remains fail-closed for
GitHub projects. M3.0c must define remote publication and completion before this gate can open.

### CI note for the reserved claim namespace

The claim is currently a remote branch under `projectctl/claims/**`. Repositories with broad
push-triggered GitHub Actions may wish to ignore that prefix:

```yaml
on:
  push:
    branches-ignore:
      - "projectctl/claims/**"
```

Repository rules or insufficient Git write permission may intentionally reject claim creation or
deletion; ProjectCTL does not bypass those policies.

See ADR-013 and `docs/PROJECTCTL_BLUEPRINT.md` for the full protocol and scope boundary.


## M3.0c — Remote Publication & GitHub Completion

M3.0c makes team-visible delivery a first-class requirement for remote task authorities.

For GitHub, the delivery sequence is:

```text
verified candidate
    ↓
local fast-forward integration
    ↓
durable PublicationRequest
    ↓
exact-base remote publication
    ↓
remote candidate observation
    ↓
durable PublicationManifest
    ↓
additive projectctl:completed marker
    ↓
exact claim release
    ↓
PASSED
```

Publication uses the exact verified base as the lease expectation:

```text
git push --force-with-lease=<target-ref>:<base-commit> \
  origin <candidate-commit>:<target-ref>
```

ProjectCTL never treats a successful local integration as sufficient proof of remote delivery.

GitHub completion is additive rather than a blind native Issue close. ProjectCTL uses:

```text
projectctl:completed
projectctl:needs-decision
```

and preserves native GitHub close reasons as higher-authority human/external workflow state.

The GitHub completion adapter independently validates the referenced `PublicationManifest`,
its digest, `published=true`, and exact remote candidate identity before it can add
`projectctl:completed`.

After completion, claim cleanup cannot rewrite the task back to needs-decision. An exact-claim
ownership conflict is recorded as a control-plane cleanup anomaly while the already proven
delivery/task completion remains authoritative.

Repositories that reject direct target-branch publication because of branch protection, rulesets,
or required pull requests remain fail-closed. M3.0c does not bypass those policies and does not
create/merge PRs automatically.

See ADR-014 and `docs/PROJECTCTL_BLUEPRINT.md`.


## M3.1a — GitHub Dependencies & Sub-issues

M3.1a makes GitHub's structured team relationships visible to the deterministic scheduler.

ProjectCTL reads GitHub's native Issue dependency API:

```text
Issue A --blocked by--> Issue B
```

and normalizes it as:

```text
A.dependencies = [B]
B.blocks = [A]
```

An unresolved native dependency makes the dependent Issue ineligible. Once a local dependency is
DONE, the existing generic scheduler can admit the task without any GitHub-specific scheduling
code.

Open cross-repository dependencies are represented by stable external identities such as:

```text
github:owner/repository#42
```

Because those tasks are not present in the local authority snapshot, they fail closed as unresolved
dependencies. Closed/completed external dependencies are treated as satisfied.

GitHub sub-issues are represented separately:

```text
hierarchy.parent
hierarchy.sub_issues
```

A sub-issue relationship does **not** become a dependency implicitly. Teams that need blocking
semantics must use GitHub's native dependency relationship explicitly.

Dependency cycles, hierarchy cycles, conflicting parents, malformed relations, and same-repository
dependency nodes missing from the current snapshot fail closed to `needs_decision`.

M3.1a also introduces **TaskSnapshot v2** with `TaskHierarchy`; TaskSnapshot v1 remains exported
for audit compatibility.

Relationship endpoint failures are never interpreted as an empty relationship set.

The correctness-first implementation performs additional GitHub API reads while constructing a
snapshot. Efficient incremental synchronization is intentionally deferred to M3.1c.


## M3.1b — GitHub Team Metadata

M3.1b exposes stable Issue-level team metadata without turning team workflow fields into hidden
execution authority.

Current `TaskTeamMetadata` includes:

```text
assignees
issue_type
milestone:
  number
  title
  state
  due_on
  external_url
  open_issues
  closed_issues
```

Assignees are observational context only. They do not claim tasks, affect eligibility, choose a
worker, or grant permissions.

GitHub native issue type participates in task classification with this precedence:

```text
explicit ProjectCTL type:
    ↓
recognized GitHub native issue type
    ↓
generic labels such as bug/enhancement
    ↓
unknown
```

If an explicit recognized `type:` label conflicts with a recognized native GitHub issue type,
ProjectCTL fails closed to `needs_decision`.

Native milestone title continues to feed milestone relevance. Its explicit `due_on` value now
feeds `task.due_at`, so the existing deterministic urgency score can use a GitHub milestone
deadline.

Assignee-only changes remain visible in TaskSnapshot but are excluded from the semantic scheduler
digest and GitHub semantic source revision. They therefore do not invalidate an otherwise safe
ExecutionPlan.

M3.1b introduces **TaskSnapshot v3**. v1 and v2 remain exported for audit compatibility.

Organization-specific Issue Fields and GitHub Projects V2 are intentionally not merged into core
scheduling semantics yet. A field named Priority, Risk, DRI, or Due Date does not automatically
have ProjectCTL meaning. Those integrations require explicit binding/conflict policy.

See ADR-016 and `docs/PROJECTCTL_BLUEPRINT.md`.


## M3.1c1 — GitHub Derived Cache & Freshness Contract

M3.1c1 defines the cache contract before ProjectCTL starts using cached GitHub responses.

Derived entries live under:

```text
.projectctl/cache/github/v1/<owner>/<repository>/<request-fingerprint>.json
```

GitHub remains authoritative. Removing the cache may make the next refresh slower but must not
change task semantics.

Each cache request binds the exact REST representation:

- repository and endpoint
- GET method / github.com host
- GitHub API version
- Accept media type
- pagination and slurp behavior

GitHub GET requests are now explicitly pinned to:

```text
Accept: application/vnd.github+json
X-GitHub-Api-Version: 2026-03-10
```

Each `GitHubCacheEntry v1` records payload/provenance including:

```text
request_fingerprint
payload_digest
integrity_digest
observed_at
validated_at
etag
last_modified
```

`observed_at` means the payload itself was fetched. `validated_at` means GitHub most recently
confirmed that representation as current. This distinction is required so a later HTTP 304 can
advance freshness without pretending the payload was downloaded again.

Freshness is explicit:

```text
now - validated_at <= caller max age  -> fresh
otherwise                             -> stale
```

File modification time is not freshness authority. Future timestamps, digest mismatches, request
identity mismatches, cache-path escapes, and symlink entries fail closed.

M3.1c1 deliberately **does not serve task snapshots from cache**. It established the
correctness/provenance contract consumed by M3.1c2.

See ADR-017 and `docs/PROJECTCTL_BLUEPRINT.md`.

### M3.1c2 — Conditional GitHub Reads

M3.1c2 activates remote validation for single-response GitHub GET representations.

For cacheable single-response reads, ProjectCTL now:

- captures HTTP status plus `ETag` / `Last-Modified` using authenticated `gh api --include`
- sends `If-None-Match` when an ETag exists
- falls back to `If-Modified-Since` only when no ETag is available
- handles `304 Not Modified` by preserving payload, payload digest and `observed_at` while
  advancing `validated_at`
- handles `200 OK` by replacing the derived payload and response validators
- treats provider, transport, auth, rate-limit and server errors as errors even when cached data
  exists
- records `github.cache.read` telemetry outcomes such as `miss_200`, `refreshed_200`,
  `revalidated_304` and `provider_error`
- rejects cached validator values containing line breaks before they can become request headers

M3.1c2 deliberately does **not** attach one validator to a `gh api --paginate --slurp`
aggregate. An HTTP validator proves one concrete response representation/page, not an arbitrary
multi-page aggregate. Existing paginated Issue/relation reads therefore remain unconditional in
this milestone.

Likewise, a locally fresh cache entry is not served without contacting GitHub. TTL-based
cache-backed snapshot assembly and page-aware fan-out reduction belong to M3.1c3.

See ADR-018 and `docs/PROJECTCTL_BLUEPRINT.md`.

### M3.1c3 — Cache-backed Snapshot Assembly & Scale

M3.1c3 activates bounded local reuse of remotely validated GitHub representations.

Project config is additively versioned to **ProjectConfig v3**. GitHub task-store reads now use:

```yaml
task_store:
  provider: github
  repository: owner/repository
  cache_max_age_seconds: 30
```

A value of `0` disables local fresh hits and forces conditional remote revalidation.

Paginated Issue and relation collections are no longer cached as one `--paginate --slurp`
aggregate. They are read as concrete pages:

```text
...?per_page=100
...?per_page=100&page=2
...
```

Each page therefore has its own request fingerprint, payload, validator and freshness proof.

Within the configured freshness window, a valid page can be reused without another HTTP call and
records a `fresh_hit` telemetry outcome. Once stale, M3.1c2 conditional revalidation resumes:
ETag/Last-Modified -> 304 revalidation or 200 replacement. Provider errors after remote validation
is attempted remain errors; stale cache is never used as an outage fallback.

Task mutations invalidate the repository's derived GitHub cache before the post-mutation read, so
completion/decision labels cannot remain hidden behind a fresh cached Issue/list page.

Execution safety is stricter than ordinary status/scheduling reads. Preflight before claim and
again after claim uses a provider-neutral `max_age=0` override, forcing remote validation so a
new dependency or lifecycle change cannot be masked by the normal bounded freshness window.

Scale tests verify that repeated snapshots reuse Issue and per-Issue relationship pages rather than
repeating the original REST fan-out.

See ADR-019 and `docs/PROJECTCTL_BLUEPRINT.md`.

### M3.1d — Schema Export Authority & Drift Policy

M3.1d resolves the repository's public-schema drift ambiguity.

Public JSON Schema contracts are defined by the versioned model classes registered in
`projectctl.schema_export.PUBLIC_SCHEMAS`. The previously checked-in `schemas/generated/`
directory was only a partial, stale mirror, so it is no longer versioned.

Generate schemas when needed:

```bash
projectctl schema export
```

The default `schemas/generated/` output is now Git-ignored. Exported files are derived artifacts,
not a second source of truth.

The exporter writes filenames deterministically. CI enforces that:

- `schemas/generated/` is not checked into the repository
- every `PUBLIC_SCHEMAS` entry exports successfully
- the exported filename set exactly equals the registry
- each exported artifact parses as a JSON schema object

This keeps additive schema compatibility in code/history while eliminating manual generated-file
drift and review noise.

See ADR-020 and `docs/PROJECTCTL_BLUEPRINT.md`.

### M3.2a — Linear Read Authority

M3.2a adds Linear as the first post-GitHub remote task authority without assuming that GitHub's
claim or completion semantics transfer to another provider.

Configure a Linear team in **ProjectConfig v4**:

```yaml
task_store:
  provider: linear
  team: 9cfb482a-81e3-4154-b5b9-2c805e70a02d
```

Credentials are not stored by ProjectCTL. The read adapter accepts exactly one runtime credential:

```text
LINEAR_API_KEY       # personal API key
LINEAR_ACCESS_TOKEN  # OAuth access token
```

The Linear GraphQL adapter:

- uses the official `https://api.linear.app/graphql` endpoint
- scopes reads to one configured team UUID
- paginates issues with Relay-style `pageInfo.endCursor`
- rejects GraphQL `errors` even when HTTP 200 contains partial `data`
- validates that every returned page belongs to the configured team
- never persists the API key or OAuth token

Workflow-state normalization is intentionally conservative:

```text
completed -> done
canceled  -> cancelled
started   -> running (observational)
backlog/unstarted -> planned
unknown   -> needs_decision
```

No non-terminal Linear issue is exposed as `READY` in M3.2a. Linear supports issue
blocking/blocked relations, but those relationships are not yet normalized into ProjectCTL's
dependency graph. Claim/release, needs-decision mutation and completion are likewise reported as
unsupported capabilities.

This means `projectctl tasks`, status snapshots and provider inspection can read Linear, while
the execution gate remains fail-closed.

Brownfield onboarding supports:

```bash
projectctl adopt . --task-store linear --task-store-team <TEAM_UUID>
```

See ADR-021 and `docs/PROJECTCTL_BLUEPRINT.md`.

### M3.2b — Linear Relationship & Eligibility Semantics

M3.2b completes the read-side dependency semantics required before Linear tasks can participate
safely in scheduler eligibility.

ProjectCTL reads each issue's incoming Linear `inverseRelations` connection independently with
cursor pagination. For a relation of type `blocks`, the source issue is the blocker and the
requested issue is the blocked target.

Dependency normalization follows these rules:

```text
incoming blocks from unresolved local issue -> local dependency
incoming blocks from unresolved other-team issue -> external dependency
incoming blocks from completed/canceled issue -> satisfied, no dependency
related / duplicate / similar -> not a dependency
unknown/malformed relation -> needs_decision
```

Local `blocks` edges are derived by reversing the canonical dependency graph rather than reading
a second independent representation.

Hierarchy remains separate from dependency semantics. Linear's parent pointer is normalized into
`TaskHierarchy.parent`; local `sub_issues` are derived from those parent pointers. A parent
relationship never blocks a task implicitly.

Scheduler eligibility is now:

```text
completed -> DONE
canceled  -> CANCELLED
started   -> RUNNING (observational)
backlog   -> PLANNED
unstarted + no unresolved blocker -> READY
unstarted + unresolved blocker    -> BLOCKED
unknown/ambiguous relationship    -> NEEDS_DECISION
```

Cross-team open blockers use stable `linear:<UUID>` external dependency identities. An unresolved
blocker that claims to belong to the configured team but is absent from the team snapshot fails
closed to `NEEDS_DECISION`.

Dependency and hierarchy cycles are also detected and fail closed.

Linear is still **not execution-ready**: claim, release, decision-block writes and completion
remain unsupported.

See ADR-022 and `docs/PROJECTCTL_BLUEPRINT.md`.

### M3.2c1 — Execution Transport & Ownership Boundary

M3.2c1 separates three concepts that must not be conflated:

```text
Task Authority       -> Beads / GitHub Issues / Linear / future Jira
Code Transport       -> local Git / generic network Git remote
Execution Ownership  -> task-native / local lock / exact Git ref lease
```

ProjectConfig is additively versioned to **v5**:

```yaml
task_store:
  provider: linear
  team: 9cfb482a-81e3-4154-b5b9-2c805e70a02d

code_transport:
  mode: git_remote
  remote_name: origin
  remote_identity: gitlab.com/acme/widget
```

For a local-only project:

```yaml
code_transport:
  mode: local
```

`remote_identity` is credential-free `host/path`; ProjectCTL never persists a Git token or
username as transport identity.

Ownership resolution is now independent from Task Authority:

- Beads keeps its task-native claim semantics.
- `local` uses an exact ProjectCTL local claim marker serialized by project locks. It protects
  concurrent processes sharing the same project filesystem but makes **no cross-machine claim**.
- `git_remote` uses the existing exact Git ref lease as a provider-neutral distributed ownership
  primitive. The Git host may be GitHub, GitLab or another compatible Git server.
- historical GitHub claim refs remain compatible.

Brownfield inspection records a generic network Git remote identity even when it is not GitHub.
Adoption can therefore configure combinations such as:

```bash
projectctl adopt . \
  --task-store linear \
  --task-store-team <TEAM_UUID> \
  --code-transport git-remote \
  --git-remote-name origin \
  --git-remote-identity gitlab.com/group/repo
```

or explicitly remain local even when an origin exists:

```bash
projectctl adopt . \
  --task-store linear \
  --task-store-team <TEAM_UUID> \
  --code-transport local
```

Inspect the effective ownership strategy with:

```bash
projectctl execution-ownership --json
```

Doctor now checks Task Authority readability and Execution Ownership transport separately.

M3.2c1 **does not make Linear execution-ready**. Linear still lacks proven
`block_for_decision`/completion mutation semantics. It also does not yet generalize remote
publication/delivery: GitLab branch/MR policy belongs to the next milestone.

ProjectCTL remains Git-native. Local-only means a **local Git repository with no network remote**;
a completely non-Git workspace is not supported by the current worktree/candidate/evidence model.

See ADR-023 and `docs/PROJECTCTL_BLUEPRINT.md`.

### M3.2c2 — Generic Delivery & Linear Lifecycle

M3.2c2 separates **delivery authorization** from both Task Authority and Code Transport.

ProjectConfig is additively versioned to **v6**:

```yaml
task_store:
  provider: linear
  team: <TEAM_UUID>

code_transport:
  mode: git_remote
  remote_name: origin
  remote_identity: gitlab.com/group/repo

code_delivery:
  mode: direct_git
```

Supported delivery policies are:

```text
local           -> verified local integration is sufficient
direct_git      -> exact verified candidate must be published to the pinned Git remote
review_required -> explicitly modeled, but fail-closed until a PR/MR adapter exists
```

A discovered remote never grants publication permission. For Linear + GitLab, adoption therefore
defaults to local delivery unless `--code-delivery direct-git` is explicitly selected.

Inspect delivery separately:

```bash
projectctl code-delivery --json
```

The direct Git publisher is now hosting-vendor-neutral. It validates the configured
credential-free remote identity and keeps exact-base/force-with-lease publication semantics.

Linear lifecycle writes are also enabled without changing native Linear workflow state. ProjectCTL
owns only two team-scoped labels:

```text
projectctl:completed
projectctl:needs-decision
```

Completion uses a fail-closed two-phase protocol:

```text
verify evidence + current blockers
        ↓
add needs-decision guard
        ↓
add completed marker
        ↓
re-read current Linear state + blockers
        ↓
safe? remove guard
        ↓
DONE
```

If the process crashes or provider state changes before the final guard removal, the issue retains
the decision guard (or both ProjectCTL markers), which normalizes to `NEEDS_DECISION` rather than
a false `DONE`.

Native Linear `completed`/`canceled` states remain authoritative. ProjectCTL does not replace
human labels, state, assignee, or title.

Examples:

Local-only Linear:

```bash
projectctl adopt . \
  --task-store linear \
  --task-store-team <TEAM_UUID> \
  --code-transport local \
  --code-delivery local
```

Linear + GitLab with explicitly authorized direct publication:

```bash
projectctl adopt . \
  --task-store linear \
  --task-store-team <TEAM_UUID> \
  --code-transport git-remote \
  --git-remote-name origin \
  --git-remote-identity gitlab.com/group/repo \
  --code-delivery direct-git
```

Repository requiring review:

```bash
projectctl adopt . \
  --task-store linear \
  --task-store-team <TEAM_UUID> \
  --code-transport git-remote \
  --git-remote-identity gitlab.com/group/repo \
  --code-delivery review-required
```

The last mode is intentionally not autonomous yet; ProjectCTL will not silently bypass review
policy with a direct push.

See ADR-024 and `docs/PROJECTCTL_BLUEPRINT.md`.

### M3.2c3 — Review-Aware Delivery Adapters

`review_required` is now an executable delivery mode for canonical GitHub.com and GitLab.com
remotes.

ProjectCTL creates a deterministic candidate branch:

```text
projectctl/review/<run-id>-<candidate-prefix>
```

and publishes **only the exact verified candidate** to that branch. If the branch already exists
at another SHA, delivery fails closed rather than replacing reviewed code.

Before any PR/MR creation side effect, ProjectCTL persists and event-anchors a `ReviewRequest`.
Creation is reconcile-first and idempotent, so a crash after the provider created the review but
before ProjectCTL persisted the receipt does not create duplicate reviews on retry.

Supported built-in review hosts:

```text
github.com/<owner>/<repo> -> pull request via authenticated gh
gitlab.com/<group>/<repo> -> merge request via GitLab API
```

GitLab credentials are runtime-only. Configure exactly one of:

```text
GITLAB_TOKEN
GITLAB_ACCESS_TOKEN
```

Opening a review is **not completion**. The run enters `AWAITING_REVIEW`, keeps its execution
claim, and bounded autonomous mode stops with `REVIEW_PENDING`.

ProjectCTL never approves or merges the review itself.

After an external merge, recovery independently proves that old verification evidence is still
valid. Accepted delivery is intentionally strict:

- review head must still equal the verified candidate
- fast-forward merge is accepted when the target equals the candidate
- a merge commit is accepted only when its two parents are exactly the verified base and candidate
- the proven merge result must be reachable from the current stable remote target
- the local integration target must fast-forward to the proven remote target

Squash merges, rebase merges, stale-base merges, changed review heads, closed-unmerged reviews, or
ambiguous provider state fail closed to human decision rather than reusing stale verification.

Recovery:

```bash
projectctl run recover <RUN_ID>
```

While the PR/MR is open, recovery remains idempotently in `AWAITING_REVIEW`. Once the exact
review merge is proven, ProjectCTL synchronizes the local target, completes the canonical task with
the durable `ReviewReceipt`, releases independent ownership, and transitions the run to `PASSED`.

Public contracts added/versioned in this milestone:

- `ReviewRequest v1`
- `ReviewReceipt v1`
- `CodeDeliveryPolicy v2`
- `IntegrationManifest v3`

See ADR-025 and `docs/PROJECTCTL_BLUEPRINT.md`.

### M3.3a — Jira Read Authority

Jira Cloud can now be used as the canonical **read** task authority without introducing a parallel
tracker.

Persist only credential-free identity:

```yaml
task_store:
  provider: jira
  site: acme.atlassian.net
  project: ENG
```

Runtime credentials:

```bash
export JIRA_EMAIL="bot@example.com"
export JIRA_API_TOKEN="..."
```

ProjectCTL uses Jira REST v3 enhanced JQL search with explicit `nextPageToken` pagination and
validates that every returned issue belongs to the configured project.

Brownfield adoption can configure Jira directly:

```bash
projectctl adopt . \
  --task-store jira \
  --task-store-site acme.atlassian.net \
  --task-store-project ENG \
  --code-transport local \
  --code-delivery local
```

M3.3a deliberately normalizes Jira workflow conservatively:

```text
done/completed category + normal resolution -> DONE
done/completed + cancellation-like resolution -> CANCELLED
indeterminate/in-flight                  -> RUNNING (observational)
new/to-do                                -> PLANNED
unknown                                  -> NEEDS_DECISION
```

A Jira To Do issue is **not** automatically `READY`. Jira workflow categories are provider
groupings, not proof that ProjectCTL is allowed to start a task.

Parent/sub-task relations are normalized as hierarchy only. Dependencies, blocker links and custom
workflow readiness belong to M3.3b.

Jira capability state in M3.3a:

```text
read                supported
claim               unsupported
release             unsupported
block_for_decision  unsupported
complete            unsupported
```

Therefore Jira remains non-executable by design even though snapshots, status views and reporting
can read it.

ProjectConfig advances to **v7** and adoption plan/manifest contracts to **v6**. Older ProjectConfig
versions remain readable without rewriting the project file.

See ADR-026 and `docs/PROJECTCTL_BLUEPRINT.md`.

### M3.3b — Jira Relationship & Workflow Eligibility

Jira scheduler semantics are now explicit human policy rather than provider-name heuristics.

Example:

```yaml
task_store:
  provider: jira
  site: acme.atlassian.net
  project: ENG
  jira_policy:
    ready_statuses:
      - id: "10000"
        name: Ready
    link_rules:
      - type_id: "10001"
        name: Blocks
        inward_label: is blocked by
        outward_label: blocks
        inward: dependency
        outward: blocks
```

Use the provider metadata command before authoring the policy:

```bash
projectctl jira-metadata --json
```

This exposes current Jira status IDs/names/categories and issue-link type IDs plus their
inward/outward labels.

A Jira to-do/new issue becomes `READY` only when its stable status id **and** name are explicitly
pinned. Unconfigured to-do statuses stay `PLANNED`. If a pinned status is renamed or moved to
another status category, ProjectCTL fails closed to `NEEDS_DECISION`.

Jira issue links are also explicit. For every configured link type, each visible side must be
declared as one of:

```text
dependency -> linked issue blocks the current task
blocks     -> current task blocks the linked issue
ignore     -> this side has no scheduling meaning
```

ProjectCTL pins type id, name and both provider labels. Unknown link types and metadata drift are
not guessed.

For local project issues, either valid side of a Jira link is enough to reconstruct both canonical
edges. This prevents a partial Jira read from leaving the blocked task falsely READY.

Cross-project blockers are represented by stable identities:

```text
jira:<site>:<stable-issue-id>
```

and are independently re-read before eligibility is decided. An embedded stale status in
`issuelinks` cannot silently unblock work.

Parent/sub-task remains hierarchy only. Dependency cycles and hierarchy cycles are checked
separately and participants move to `NEEDS_DECISION`.

ProjectConfig advances to **v8**. Older config versions continue to load in memory without
rewriting persisted files.

Jira lifecycle capabilities are still intentionally unsupported:

```text
read                supported
claim               unsupported
release             unsupported
block_for_decision  unsupported
complete            unsupported
```

So M3.3b improves scheduler truth without yet making Jira autonomously executable.

See ADR-027 and `docs/PROJECTCTL_BLUEPRINT.md`.

### M3.3c — Jira CAS Lifecycle

Jira can now participate in ProjectCTL execution without ProjectCTL transitioning native Jira
workflow state.

ProjectCTL reserves one issue property:

```text
projectctl.lifecycle.v1
```

with three states:

```text
completion_pending
completed
needs_decision
```

Lifecycle writes do **not** use Jira's ordinary per-issue property PUT. Instead ProjectCTL uses the
filtered bulk property endpoint as compare-and-set:

```text
new marker:
  entityIds=[stable issue id] + hasProperty=false

existing marker:
  entityIds=[stable issue id]
  + hasProperty=true
  + currentValue=<exact previously observed marker>
```

The Jira async task is awaited and the property is read back before ProjectCTL accepts success.

Completion is crash-safe:

```text
validate durable evidence
        ↓
verify current Jira task/blockers
        ↓
CAS absent → completion_pending
        ↓
re-read current Jira task/blockers
        ↓
CAS exact pending → completed
        ↓
exact property read-back
```

If ProjectCTL crashes after the guard is written, the task normalizes to `NEEDS_DECISION` until
the same run/evidence resumes. If completion already succeeded remotely before a local crash, retry
recognizes the same completed marker idempotently.

Unexpected/malformed/foreign property values are treated as external state and are never silently
overwritten.

Native Jira terminal state remains authoritative. A completed ProjectCTL marker also does not hide
a currently unsafe dependency/provider state; such conflicts normalize to `NEEDS_DECISION`.

Jira lifecycle capabilities are now:

```text
read                supported
claim               unsupported
release             unsupported
block_for_decision  supported
complete            supported
```

Claim/release remain intentionally provider-independent. Local projects use the ProjectCTL local
ownership lock; distributed projects use the exact Git ref lease established in M3.2c1.

Completion evidence remains delivery-aware:

```text
local delivery       -> EvidenceManifest
direct Git delivery  -> PublicationManifest
review delivery      -> ReviewReceipt
```

ProjectConfig remains **v8**; M3.3c introduces the public `JiraLifecycleMarker v1` contract rather
than changing project intent/config.

See ADR-028 and `docs/PROJECTCTL_BLUEPRINT.md`.

### Post-M3 architecture review and M4.0a implementation

The post-M3 review is recorded in:

```text
docs/architecture/POST_M3_ARCHITECTURE_REVIEW.md
docs/decisions/ADR-029-global-admission-before-parallelism.md
```

It identified the correctness gap between account-global quota observation and project-local
execution admission. **M4.0a now closes that gap.**

Implemented:

- global-state DB **v2** with an explicit backup-producing v1 → v2 migration
- authoritative `execution_admissions` state in `$PROJECTCTL_HOME/state.sqlite`
- at most one active quota-consuming worker turn per quota account
- admission identity bound to quota account, project instance, logical project, run and lease owner
- atomic acquisition with SQLite `BEGIN IMMEDIATE` plus per-account uniqueness
- owner heartbeat/expiry and deterministic stale-lease reclamation
- durable admission audit events for acquire, reconcile, stale reclaim and release
- fresh quota revalidation **after admission acquisition** and before worker-provider contact
- admission enforcement on both `run start` and checkpoint `run resume`
- busy-account and quota-denied starts remain retryable instead of corrupting run state
- release after worker completion, checkpoint or provider failure
- no admission held through verification, integration, publication or external review waiting
- no fabricated token/percentage reservation or task-cost estimator

Existing installations with global-state DB v1 must run:

```bash
projectctl migrate
```

The command now migrates the account-global state database as well as the project-local state
database and creates backups before applying supported migrations.

### M4.0b — Portfolio Scheduling & Cross-Project Arbitration

M4.0b adds deterministic cross-project arbitration on top of the M4.0a account admission
primitive.

The portfolio layer chooses a **project / worker-turn action**. It never compares raw local
scheduler scores and never replaces the project-local task scheduler.

Supported actions:

```text
resume_run
   ↓
start_run
   ↓
new_task
```

Within one action class, fairness is:

```text
never admitted
   ↓
least recently admitted
   ↓
older registration
   ↓
stable project-instance id
```

Inspect the next project for one quota account:

```bash
projectctl portfolio next --account openai-default
projectctl portfolio next --account openai-default --json
```

Execute exactly one selected quota-consuming worker turn:

```bash
projectctl portfolio run --account openai-default
```

For new work, the portfolio decision is bound to the local scheduler's selected task,
task-snapshot digest and project-state digest. If those inputs change before preparation,
ProjectCTL fails closed before claiming a task.

Normal decisions are materialized under:

```text
$PROJECTCTL_HOME/portfolio/decisions/<decision-id>.json
```

These files are audit artifacts, not task or admission authority. Actual worker-turn ownership
remains the M4.0a account admission lease.

### M4.1a — Parallel Planning Safety Contract

M4.1a defines the proof required before same-project concurrency can be enabled.

Parallel safety is explicit and fail-closed. Tasks that may participate must declare human-managed
scope in:

```text
projectctl.parallel.yaml
```

Example:

```yaml
schema_kind: projectctl.parallel_scope_catalog
schema_version: 1
tasks:
  TASK-123:
    task_id: TASK-123
    inputs:
      - path: src/parser
        kind: tree
    writes:
      - path: src/parser/new_backend.py
        kind: exact
    resources:
      - parser-registry
```

The catalog is protected from worker modification by verification policy.

Build one proof artifact:

```bash
projectctl parallel plan TASK-123 --project /path/to/repo
```

Assess two tasks:

```bash
projectctl parallel assess TASK-123 TASK-456 --project /path/to/repo
projectctl parallel assess TASK-123 TASK-456 --project /path/to/repo --json
```

The decision is deterministic and checks:

- scoped task/dependency state rather than the whole unrelated task snapshot
- exact Git-base input digests
- project-state identity
- task dependency relations
- write/write overlap
- write/input invalidation in both directions
- exclusive resource overlap
- shared-target base consistency

No LLM conflict judgment is authoritative.

Two tasks can be execution-independent while sharing one target/base. In that case the decision
explicitly records that integration requires reapplication/fresh verification after the first
candidate advances the target. Existing evidence is never valid for transformed code.

M4.1a **does not enable multiple active runs**. It only establishes the proof contract consumed by
M4.1b.

### M4.1b — Safe Parallel Execution & Integration

M4.1b consumes the M4.1a proof and enables a bounded same-project active set.

The explicit runtime is:

```bash
projectctl parallel run --max-runs 2 --project /path/to/repo
projectctl parallel queue --project /path/to/repo
projectctl parallel integrate RUN_ID --project /path/to/repo
projectctl parallel recover --project /path/to/repo
```

A new run is admitted only when it is pairwise independent from every currently active
parallel-bound run and the configured active-set bound is not exceeded.

Important: M4.0a remains authoritative. Multiple isolated runs may be active, but one quota account
still permits at most one quota-consuming worker turn at a time. ProjectCTL does not invent a
token-cost model merely to increase concurrency.

Each admitted run receives a durable `ParallelRunBinding` after task claim. Its verified changed
paths must remain inside the human-managed `projectctl.parallel.yaml` write scope.

Integration order is deterministic by run creation time plus run id, rather than worker finish
time. Earlier unfinished/review-waiting runs remain ahead of later candidates.

When an earlier integration advances the shared target, a later candidate is never accepted under
its old evidence. ProjectCTL proves that the target advancement did not touch the later run's
declared inputs/writes, archives the old proof chain, reapplies the exact verified patch onto the
new base, returns the run to `VERIFYING`, and only then creates fresh candidate/evidence.

Crash evidence for this transformation is recorded as:

```text
ParallelReapplicationRequest v1
        ↓
workspace transformation
        ↓
durable run rebind -> VERIFYING
        ↓
ParallelReapplicationManifest v1
        ↓
fresh VerificationManifest / EvidenceManifest
```

Ambiguous crash states fail closed rather than guessing.

The legacy `projectctl run auto` remains a serial orchestrator and intentionally still stops on a
multiple-active-run set. Parallel orchestration is explicit.

### Post-M4 Architecture Review

The review found that the M4 safety primitives are real, but they are not yet one unified execution
contract.

Two concrete composition gaps were found:

- `ExecutionPlan v2` / `ContextManifest v2` still carry whole-task-snapshot execution inputs,
  while parallel safety uses a scoped task/dependency proof.
- portfolio arbitration excludes projects with multiple active runs, while M4.1b intentionally
  creates bounded multi-run active sets.

A provider-native claim edge case makes the first gap immediately important. Beads claim ownership
moves the selected task to `in_progress`, while current prepare logic rechecks the pre-claim whole
TaskSnapshot digest. The claim transition must be modeled as an expected control-plane mutation,
not confused with external stale context.

The current "parallel runtime" should also be read precisely as **bounded concurrent work-in-progress
/ active runs**. M4.0a still allows only one quota-consuming worker turn per account at a time.

The remediation sequence is now:

```text
M4.0a  Account-Global Execution Admission                  completed
   ↓
M4.0b  Portfolio Scheduling & Cross-Project Arbitration   completed
   ↓
M4.1a  Parallel Planning Safety Contract                  completed
   ↓
M4.1b  Bounded Parallel Active-Set & Safe Integration     implemented
   ↓
M4.2a  Execution Input Contract Unification               next
   ↓
M4.2b  Unified Turn Orchestration
```

M4.2a will separate full scheduler observation from scoped execution validity, make claims
transition-aware, connect code scopes to context/verification, clean up reapplication provenance,
and add cross-layer scenario tests.

M4.2b will make portfolio arbitration aware of parallel active sets and route automated worker
turns through one account-global dispatcher.

Graphify/context discovery remains a strong candidate for **M5**, but only after these M4 contract
closure steps.

See ADR-029 through ADR-033, `docs/architecture/POST_M4_ARCHITECTURE_REVIEW.md`, and
`docs/PROJECTCTL_BLUEPRINT.md`.

Next:

- **M4.2a — Execution Input Contract Unification**
