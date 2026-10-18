# D0 preflight report — ProjectCTL dogfooding feasibility

**Outcome: `BLOCKED_ENVIRONMENT_AND_SDK_MODEL_RUNTIME_UNVERIFIED`**  
**Assessment date:** 2026-10-18  
**Checked-out source:** `research/advisory-skills-eval` at `8ce08d296c1b6880893b22a88ab990a5917fe301`  
**Product package source version:** `0.41.0` (`pyproject.toml`)  
**Scope:** offline D0 only. No D1 worker, task authority, ProjectCTL state, or M6.0 operation was run.

## Decision

The current source contains a manual local-Git/Beads prepare → start → independent verify → separately reviewed integrate path, and a Python SDK adapter with explicit direct strategy, workspace-write sandbox, deny-all approvals, disabled network, and configured reasoning/model fields. This establishes a plausible product path, not safe execution readiness. This host cannot run the required experiment: `bd`, the ProjectCTL CLI and pinned `openai-codex==0.160.0` are absent from the active environment. The source forwards the selected model string to the SDK, but that does not prove `gpt-6-luna` is accepted by the pinned SDK/runtime. The machine-readable preflight therefore fails closed.

Do not proceed to D1 on this evidence. Re-run preflight from the intended isolated operator environment; resolve the typed blockers and review every D1 GO item below first.

## Evidence captured

| Check | Observation | Result |
|---|---|---|
| Git source checkout | `8ce08d296c1b6880893b22a88ab990a5917fe301`, branch `research/advisory-skills-eval` | Observed |
| Python | 3.14.0 | Available; exceeds source minimum 3.12 |
| Git | 2.43.0 | Available |
| ProjectCTL source | 0.41.0 | Present; CLI unavailable in PATH |
| ProjectCTL CLI smoke (`python3 -m projectctl --help`) | Fails with `ModuleNotFoundError: No module named 'typer'` | Blocked by missing project dependencies |
| Local Beads `bd` | Not on PATH | `BLOCKED_TASK_AUTHORITY` |
| Codex CLI | `codex-cli 0.163.0` | Present; distinct from Python SDK adapter |
| Python SDK `openai-codex` | No installed distribution in active Python environment | `CODEX_SDK_PIN_MISSING` |
| `gpt-6-luna` SDK/runtime resolution | Not established by source inspection or offline environment | `SDK_MODEL_RUNTIME_UNVERIFIED` |
| Experiment repo / state / policy | No disposable repo was supplied; no isolated `PROJECTCTL_HOME` configured | D1 prerequisites unverified |
| Current worktree | Clean before D0 edits; all deliverables below are confined to `experiments/dogfooding/` | Preserved |

The local source defines these real CLI forms: `projectctl init PATH --non-interactive --yes --task-store beads`; `projectctl run prepare` supports `--strategy direct`, `--project`, and `--json`; `run start`, `run verify`, and `run integrate` take `RUN_ID` and `--project`. The README and command source distinguish preparation/claim from worker start, independent verification, and integration. The Beads adapter builds JSON reads as `bd list --json`, `bd ready --json`, and `bd show ID --json`; create is assembled as `bd create TITLE --description TEXT --type task --priority 2 --json`. D1 must inspect the installed Beads help for its initialization syntax before changing any disposable task store.

Codex CLI 0.163.0 does not satisfy the `openai-codex==0.160.0` SDK pin. Adapter source passes `request.worker.actual_model` and `request.worker.reasoning` to SDK turn calls. The repository's SDK contract test checks the API shape, but cannot prove model service availability or resolution without runtime execution; D0 deliberately does not execute a worker.

## Delivered D0 tooling

- `preflight.py` emits redacted JSON, performs version and optional Git cleanliness/remote probes, records whether the isolated state-root environment flag exists, and reports typed blockers. It does not print repository paths, inspect secrets, call ProjectCTL commands, mutate project/task state, launch a model, or use the network. Policy/quota settings remain an explicit operator-review blocker.
- `build_fixture.py` creates a two-arm-compatible synthetic project only under `experiments/dogfooding/fixture-output/`. It uses a fixed commit timestamp, local-only Git initialization, no remotes, and rejects destinations outside its output root. It does not initialize ProjectCTL or Beads or launch workers.
- `test_d0_tools.py` uses Python's standard library and creates temporary repositories only beneath `experiments/dogfooding/`.
- `D1_PLAN.md` contains a manual, mutually exclusive A/B procedure, concrete checked-in CLI forms, stage gates, stop conditions, a blind independent adjudication worksheet, and expected evidence artifacts.

Fixture task: implement `normalize_user_id(value)` by trimming outer whitespace and lowercasing; reject non-string and blank input with `ValueError`. `POLICY.md` and `test_user_id.py` are protected. Independent acceptance is `python3 -m unittest -v test_user_id.py`. The builder tests showed two separate local repositories have identical baseline SHA, clean status and no remotes. The fixture is synthetic and is not a production project authority.

## Offline validation

- **4/4 D0 unit/integration tests passed:** `python3 -m unittest -v experiments/dogfooding/test_d0_tools.py`.
- `python3 -m compileall -q projectctl experiments/dogfooding/preflight.py experiments/dogfooding/build_fixture.py experiments/dogfooding/test_d0_tools.py` passed.
- `git diff --check` passed.
- `python3 experiments/dogfooding/preflight.py` emitted valid JSON and typed blockers, including `BLOCKED_TASK_AUTHORITY`, `CODEX_SDK_PIN_MISSING`, and `SDK_MODEL_RUNTIME_UNVERIFIED`.
- `python3 -m projectctl --help` was attempted as a non-mutating CLI inspection and could not run because `typer` is missing. Root pytest and the existing SDK contract test were not run because the active environment lacks project dependencies and the pinned SDK; no dependency installation/network access was attempted.
- No ProjectCTL worker command, Beads mutation, model inference, migration, network action, M6.0 edit, or file outside `experiments/dogfooding/` was used.

## Reproduction

From the repository root, using Python 3.12 or newer:

```bash
python3 experiments/dogfooding/preflight.py
python3 experiments/dogfooding/preflight.py --repo /path/to/disposable-clean-local-git-repository
python3 -m unittest -v experiments/dogfooding/test_d0_tools.py
python3 -m compileall -q projectctl experiments/dogfooding/preflight.py experiments/dogfooding/build_fixture.py experiments/dogfooding/test_d0_tools.py
git diff --check
```

The `--repo` argument must be a disposable, clean, local-only repository. The preflight only reads Git status/remotes and never prints its path. It does not declare readiness merely because the repo is clean.

## D1 GO/no-GO checklist

Every item must be explicitly verified before an operator starts D1:

- [ ] User separately authorizes one D1 paired attempt.
- [ ] Pinned `openai-codex==0.160.0` installed in the exact ProjectCTL environment; ProjectCTL CLI imports and help successfully.
- [ ] Local `bd` installed; exact installed version and documented local initialization/task syntax recorded; one canonical repo-local task authority only.
- [ ] D1 model `gpt-6-luna` resolves with the SDK/runtime and chosen reasoning setting is actually applied; record evidence. If not provable safely, stop at `SDK_MODEL_RUNTIME_UNVERIFIED`.
- [ ] Two disposable fixture repositories share the exact baseline SHA and spec digest; both are clean, local-only, remote-free, and outside source/M6.0 worktrees.
- [ ] Dedicated empty `PROJECTCTL_HOME` is used only by ProjectCTL arm; no existing database is migrated or reused.
- [ ] Beads task is the sole ready task; ProjectCTL config selects Beads and local transport/delivery; required execution scope and independent verification are reviewed in the disposable repo.
- [ ] Quota/admission/profile is safe and explicitly observed; no production credentials, network writes, or external delivery are available.
- [ ] Model, reasoning, sandbox/network policy, and base snapshot are matched across arms or deviation is declared before execution.
- [ ] A and B are run manually and sequentially in separate clean copies/sessions; B stages are inspected one by one; integration follows human review only.
- [ ] Stop conditions, usage unknowns, protected paths, changes, independent adjudication, and all expected artifacts are recorded.

Current decision: **NO-GO**. The open environment, task-authority, SDK and model-runtime gates are evidence-based blockers, not permission to substitute a different tracker/runtime or relax controls. D1 is not executed by this report.
