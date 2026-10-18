# D0 — ProjectCTL product dogfooding protocol

**Status:** research-only, design/preflight only; no worker calls or task mutations authorized by this document.
**Research branch:** `research/advisory-skills-eval`.
**Source reference:** ProjectCTL at `1477cad` with v6 closeout; read current code afresh at execution. M6.0 remains independent.

## Objective

Compare the *existing, supported* ProjectCTL workflow with standalone Codex on equivalent low-risk development tasks. Measure whether independently verified completion, recoverability, scope enforcement and operator effort justify control-plane overhead. This is not a new worker, trace exporter or milestone.

## Hard isolation requirements

1. Use two disposable local Git repositories or genuinely separate snapshots from one fixture base, both **outside** the ProjectCTL source checkout and M6.0 worktrees; neither may have production remotes.
2. Isolate ProjectCTL state using a dedicated `PROJECTCTL_HOME`, not the operator's usual account-global state. Maintain separate canonical task authorities per experimental repo. Never create a second task tracker in one project.
3. Do not touch `projectctl/`, `docs/PROJECT_STATE.yaml`, accepted ADRs, root verification/scope policy, or active M6.0 branches. All research docs live under `experiments/dogfooding/`.
4. No production credentials, sensitive data, network writes, push/merge, forced Git cleanup, uncontrolled deletions, or privileged host changes.
5. Do not run ProjectCTL migration on existing databases; only newly initialized disposable state may be used. No real worker execution in D0.

## D0 offline compatibility inventory — before task mutation

- Git: `git --version`, ensure original worktrees are clean.
- Task authority: verify **local Beads `bd`** is present and suitable. If absent, record `BLOCKED_TASK_AUTHORITY`. Do not substitute GitHub Issues or invent a second authority.
- ProjectCTL package/CLI: available Python >=3.12 and projectctl 0.41.0 source; use an environment separate from the existing advisory-runner virtualenv.
- Worker: code pins `openai-codex==0.160.0` (Python SDK); ensure install/probe in the isolated environment. The user's `codex-cli 0.163.0` and confirmed model `gpt-6-luna` are **not evidence that the SDK adapter accepts that model**.
- Run supported **static** CLI/help/capability inspections first. Do not call `run prepare/start/verify/integrate` in D0. A live worker-capability probe may be considered in D1 only if needed and explicitly scoped.
- Verify trial controls for quota, model profile/actual model routing, scope governance, verification catalog, clean primary worktree, and task readiness. If any required property cannot be established, stop with typed blocker rather than relaxing policy.

## D1 first actual comparison (requires separate operator execution)

One small Python standard-library implementation task with a precise specification and a preexisting independent test suite. Freeze the starting Git commit and expected behavior **before** execution.

- **A = standalone Codex CLI** using a fresh, isolated session, explicit pinned model/reasoning, local-only workspace-write policy with network disabled, no Git history mutation by the agent. Human runs an independent fixed verification afterward.
- **B = existing ProjectCTL** using one canonical local Beads task; after confirming supported SDK/model and safe admission: `run prepare --strategy direct` → `run start RUN_ID` → `run verify RUN_ID` → separately reviewed `run integrate RUN_ID`, all against disposable local repo. This is not `run auto` and has no implicit migration.
- Ensure both arms start from equivalent commits and independent context. Do not reuse a session across arms. If model/API/sandbox behavior cannot be sufficiently aligned, report the difference and downgrade cross-arm conclusions.
- **Do not launch D1 automatically** from any preflight or Codex goal. The owner runs explicit commands after reviewing the D0 evidence.

## Measurements and failure conditions

Record, separately by arm: base SHA; target SHA; fixture/spec digest; model, adapter/runtime version, reasoning; tool/sandbox/network settings; wall time; observed input/output tokens and cache details when available; operator prompts/interventions; test commands; correctness against fixed acceptance; protected-path changes; retry and recovery activity; worker vs independent-verifier claims; Git history effects; final task/evidence state.

Hard-stop on unauthorized file/Git mutations, any inability to prove task ownership, unexpected network/provider effects, mismatched verification evidence, an invalid fixed test, or unexplainable SDK incompatibility. Missing usage metrics must remain `unknown`; never backfill made-up numbers.

## Decision and scale-out

D0 result is `READY_FOR_SINGLE_DOGFOOD` or typed `BLOCKED_*` (never claimed as real end-to-end product validation). D1's single paired task evaluates **feasibility** only. If successful, run a predeclared set of 5–10 equivalently scoped tasks with mixed bug-fix, clean and recovery conditions; do not claim statistical significance from one pair.

The owner may later decide to propose changes to ProjectCTL based on evidence, under the project's existing ADR process. Nothing here changes M6.0.
