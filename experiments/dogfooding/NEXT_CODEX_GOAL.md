# Codex Goal — D0 ProjectCTL Dogfooding Feasibility (offline first)

You are operating in the existing **research/advisory-skills-eval** worktree of **ehsanrs2/projectctl**.

## Goal

Develop and verify a standalone, non-invasive D0 preflight package for a future controlled comparison of ProjectCTL with direct Codex. Answer whether a one-task, disposable local Git + Beads paired experiment can be executed safely with the **already implemented** ProjectCTL CLI and pinned Codex SDK, and produce a precise D1 execution plan. Do not execute D1.

## Read first

- `AGENTS.md`
- `docs/PROJECTCTL_BLUEPRINT.md`, `docs/PROJECT_STATE.yaml`
- `README.md`: implementation/recovery, task-authority, worker and verification sections
- `pyproject.toml` and relevant CLI/schema/worker and test code
- `experiments/dogfooding/D0_PROTOCOL.md`
- `experiments/advisory-review/PILOT_V6_CLOSEOUT.md`

Inspect the **actual current checked-out source** instead of assuming the Oct 18 snapshot is still latest. Record exact commit SHA and dependency versions. Keep the active M6.0 implementation completely out of scope.

## Authorized work — one coherent objective

1. Map the smallest supported local Git + Beads task lifecycle and any required configuration, including SDK vs Codex CLI differences. Verify actual command syntax from code or CLI help; no invented flags. Identify whether `gpt-6-luna` is resolvable through the pinned `openai-codex==0.160.0` SDK without running a worker. If that cannot be proved offline, mark a D1 gate `SDK_MODEL_RUNTIME_UNVERIFIED` rather than guessing.
2. Under `experiments/dogfooding/` only, implement a **read-only, zero-inference D0 preflight** that reports environment readiness, SDK/CLI/Beads availability, repo cleanliness, policy and workspace isolation prerequisites, and typed blockers as JSON. It must never initialize a real project, change a task authority, create/claim tasks, invoke a model, migrate a DB, alter system settings or read secrets. Source inspection and synthetic tests are permitted.
3. Design a small synthetic project task with fixed spec, baseline Git snapshot, protected files, and independent acceptance tests; implement only **local fixture builder scripts/tests in a clearly isolated output root**. If materialization would change disk outside `experiments/dogfooding/`, do not run the builder during D0; document the explicit operator step for D1. Distinguish permitted fixture creation in disposable workspace from production authority actions.
4. Document D1's **manual**, mutually exclusive execution protocol: isolated state roots, single canonical local Beads task for ProjectCTL arm, separate direct Codex arm, consistent model/reasoning and base SHA, staged `prepare/start/verify/integrate` with verification of each observed state and stop conditions, as well as fair observed wall-time/usage measurements and credential/network restrictions. Include an independent adjudication worksheet and concrete expected artifacts.
5. Run offline unit/integration checks for the new preflight and fixture generation only (fake/mocked subprocesses as needed), compile, git diff checks, and any relevant existing tests that cannot mutate live provider state. Detect and fail closed on absent prerequisites; no assumptions that GitHub-hosted CI is green.
6. Deliver `D0_REPORT.md` with `READY_FOR_SINGLE_DOGFOOD` or a specifically evidenced `BLOCKED_*` outcome, test counts, caveats, exact reproduction commands, and explicit D1 GO/no-GO checklist. Append the minimum documents necessary; avoid broad rewriting.

## Non-negotiable scope and safety

- **No live Codex/Codex-SDK inference**, no paid prompts, no network-mutating connector actions, and no background services.
- Do not execute `projectctl init`, `run prepare`, `run start`, `run verify`, `run integrate`, `run auto`, `migrate`, or `bd create` against the user's repos in D0.
- Do not change `projectctl/`, `tests/` at repo root, root policy files, docs/architecture, accepted ADRs, `docs/PROJECT_STATE.yaml`, any M6.0 branch, or earlier v6 files.
- Preserve all preexisting and untracked changes; never reset, clean, force push, auto merge or silently edit outside `experiments/dogfooding/`. For D0 implementation, use only a scoped branch commit if justified and don't push unless clearly included in the user's execution request.
- Prevent accidental leakage of `~/.codex`, env variables, account credentials and user-specific absolute paths in outputs. Avoid embedding full provider logs in public reports.
- No automatic deployment or architecture promotion. Existing ProjectCTL task/scope/verification authority remains authoritative.

## Acceptance

A new operator can run the D0 preflight offline and receive an evidence-grounded, machine-readable report, understandable typed blockers, verified low-risk scripts/tests, a reproducible D1 manual plan, and no modifications to product behavior. If a required dependency (e.g. local `bd` or pinned SDK compatibility) is unavailable, classify precisely and stop rather than fabricating a green status.

Keep the work medium-granularity: analyze, implement limited tooling, test, report in one pass. Do not expand into M6.0 or general framework integration.
