# ProjectCTL

ProjectCTL is a local-first deterministic control plane for AI-assisted software engineering.

This repository currently implements **M0.3.1 — Adaptive Project Onboarding** on top of M0.3 task-system integration.

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

No Codex worker, quota scheduler, model routing, or autonomous code-writing loop is enabled yet.

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
