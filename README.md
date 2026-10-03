# ProjectCTL

ProjectCTL is a local-first deterministic control plane for AI-assisted software engineering.

This repository currently implements **M1.2a — Codex Capability & Strategy Layer**, building on durable run preparation and isolated worktrees.

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
