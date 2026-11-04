# ProjectCTL

**ProjectCTL** is a local-first, Git-native, deterministic control plane for AI-assisted software engineering. It coordinates task authority, quota-aware planning, isolated execution, independent verification, evidence-based integration and explicitly governed recovery. An AI worker or a read-only report is never the authority for project state.

## What it provides

- **Project onboarding and task ownership:** safe greenfield/brownfield setup and pluggable task systems with explicit capability boundaries.
- **Execution governance:** deterministic planning and quota admission, isolated worktrees, bounded lifecycle commands, checkpoints and recovery policies.
- **Independent evidence:** versioned contracts, verification, candidate/integration lineage and fail-closed handling of uncertain results.
- **Read-only lifecycle observability:** `projectctl run audit` and optional monotonic `--measurements` on separately authorized stages, merged in [PR #126](https://github.com/ehsanrs2/projectctl/pull/126). Audit suggestions never dispatch or authorize retries.

ProjectCTL is in active research and development. Support for one feature does not grant blanket permission to execute a Worker, migrate a real project, deploy a privileged policy, or export an authenticated Trace. **M6.0** is the active milestone per [PROJECT_STATE.yaml](docs/PROJECT_STATE.yaml). A fully trusted, coherent live-WAL M6 Trace Collector/CLI is **not** available; its current architecture gates remain fail-closed.

## Quick start — local inspection and development

Requires **Python 3.12+**. From a development checkout:

```bash
uv sync --extra dev
uv run projectctl --help
uv run pytest
```

For an existing repository, read the onboarding/adoption policy before applying modifications. These commands are useful for **inspection** without starting a Worker:

```bash
projectctl inspect --json
projectctl task-authority --json --project /path/to/repo
projectctl run audit RUN_ID --project /path/to/repo --json
```

The audit source reader supports only its documented bounded rollback-journal inputs. It will not turn live-WAL refusal into a trusted read, change a real database's journal mode, or grant an execution decision. Commands that mutate or start a Worker require separate existing owner/policy gates; historical examples are not blanket authorization.

## Documentation map

| Read | For |
| --- | --- |
| [Documentation index](docs/README.md) | Curated navigation across living and historical documents |
| [Implementation status and dependencies](docs/IMPLEMENTATION_STATUS.md) | Verified merged features, current blockers and next gated work |
| [ProjectCTL Blueprint](docs/PROJECTCTL_BLUEPRINT.md) | **Canonical** product vision, architecture, authority map and roadmap shape |
| [PROJECT_STATE.yaml](docs/PROJECT_STATE.yaml) | **Only** structured active-milestone authority |
| [Detailed milestone and feature reference](docs/FEATURE_HISTORY.md) | Preserved long-form historical README with command examples |
| [M6 architecture index](docs/architecture/INDEX.md) | Trace, source/writer consistency, read-only limits and custody research |
| [Architecture decisions](docs/decisions/) | Specific accepted design boundaries and historical rationale |

For the Post-D2 interface, start at [Lifecycle Observability](docs/architecture/POST_D2_LIFECYCLE_OBSERVABILITY.md) and [ADR-041](docs/decisions/ADR-041-offline-lifecycle-audit-and-measurements.md). For separate M6 Trace work, consult [ADR-039](docs/decisions/ADR-039-read-only-execution-trace-export.md) and [ADR-040](docs/decisions/ADR-040-trace-snapshot-publication-consistency.md).

## Development safeguards

Use a clean worktree and pinned branch/commit for every contribution. Test the exact PR head and inspect GitHub Actions after merge. Do not silently modify generated schemas/dashboards or frozen research evidence. Telemetry and advisory recommendations never replace lifecycle authority.

MIT licensed. See [LICENSE](LICENSE).
