# D1 manual single-task paired experiment plan

**Status:** prepared by D0 only; operator execution required. This document does not authorize D1.

## Feasibility boundary

The checked-in CLI implements the lifecycle: for the existing Git fixture, `projectctl init FIXTURE --non-interactive --yes --task-store beads --code-transport local --code-delivery local` is the documented brownfield-adoption form (the command's source confirms those option names); `projectctl run prepare --strategy direct --project REPO`, `projectctl run start RUN_ID --project REPO`, `projectctl run verify RUN_ID --project REPO`, then (after human review) `projectctl run integrate RUN_ID --project REPO`. `prepare` claims the scheduler-selected Beads task and creates a ProjectCTL worktree; `start` runs the worker; verification is independent; integration is a separate control-plane mutation. The Beads adapter uses `bd list --json`, `bd ready --json`, `bd show ID --json`, and create/update operations. Its source constructs `bd create TITLE --description TEXT --type task --priority 2 --json`; D1 must first check the installed Beads `--help` for local initialization and exact supported options.

ProjectCTL's Python adapter is `openai-codex==0.160.0`, distinct from the Codex CLI version. The source statically declares `direct` as supported and passes the configured `actual_model` and reasoning level into SDK calls. That proves adapter intent and parameter plumbing only. It does not prove the SDK runtime resolves `gpt-6-luna`; the D1 gate remains `SDK_MODEL_RUNTIME_UNVERIFIED` until an explicitly authorized disposable worker run establishes it. Do not substitute a CLI success or version for that evidence.

## Manual setup and mutual exclusion

1. Confirm this D0 report's GO checklist, then explicitly authorize one D1 attempt. Stop if any gate remains open.
2. Build the fixed fixture twice with `python3 experiments/dogfooding/build_fixture.py ctl` and `... direct`. The builder is limited to `experiments/dogfooding/fixture-output/`; compare printed base SHA and spec digest. Use two separate disposable copies, no remotes, and no symlinks. Preserve each baseline.
3. Set a new, empty, dedicated `PROJECTCTL_HOME` for the ProjectCTL arm before any ProjectCTL command. Never point it at the normal account state. Use only this one configured task authority in that repo: local Beads. Inspect installed `bd --help` and initialize a fresh, repo-local Beads store using its documented syntax. Create exactly one task from `SPEC.md`; verify `bd show ID --json` and `bd ready --json` identify it as the sole eligible task. Do not create a second tracker.
4. Run the brownfield `projectctl init` command above only in the ProjectCTL arm after Beads is initialized and the task is visible. Review the resulting config. Author and review required scope policy (`scope_governance.mode: required`, explicit task read/write paths) and an independent verification policy that runs `python3 -m unittest -v test_user_id.py`. Review actual generated policy and config; do not guess quota. Use a fresh authorized quota observation/profile if admission requires it. Network access and external delivery remain prohibited.
5. Before either arm, record the two base SHAs, spec SHA-256, protected file SHA-256 values, relevant package/runtime versions, model `gpt-6-luna`, reasoning `medium`, and sandbox/network policy. Confirm both repos are clean and remote-free. If exact model/reasoning settings cannot match, stop or report the comparison as non-equivalent.
6. Run exactly one arm at a time. First choose either A or B and complete/adjudicate it before opening the other. Never share a Codex session, worktree, task store, ProjectCTL state root, or uncommitted output across arms.

## Arm A — direct Codex CLI

Use the `direct` fixture copy in a fresh Codex CLI session, explicit `gpt-6-luna` / medium reasoning, workspace-write sandbox, network disabled, and no permission to change Git history or protected files. Do not connect it to Beads or ProjectCTL. The operator observes and records wall time and usage shown by the CLI; missing usage remains `unknown`. After the session, capture target SHA, diff, status, protected-file digests, and execute the fixed independent unittest command.

## Arm B — ProjectCTL

Use the other untouched baseline. With the isolated state root and single ready Beads task, manually run and inspect each transition:

1. `projectctl run prepare --strategy direct --project REPO --json`; confirm the selected task ID, strategy, base SHA, planned scope, and resulting run is `claimed` before continuing.
2. `projectctl run start RUN_ID --project REPO --json`; confirm only the isolated worktree changed and run reached `verifying`. Stop on SDK/model/auth/network uncertainty or any unexpected mutation.
3. `projectctl run verify RUN_ID --project REPO --json`; independently inspect verification command/result, protected paths and evidence. Require overall pass and exact fixed-test success.
4. Review candidate/base/diff and every integration effect. Only then run `projectctl run integrate RUN_ID --project REPO --json`; inspect final target SHA, task state and evidence. Integration is not automatic authorization from a passing test.

Never use `run auto`. Never use existing state or migrate a database. No push, merge, hosted tracker, credentials in artifacts, or network writes. If prepare requires a config/state setup transition, do it only in the disposable repo and fresh state root and record it.

## Stop conditions

Stop and preserve evidence on dirty or mismatched base, missing/multiple ready tasks, changed policy/spec/protected file, failed required check, task ownership ambiguity, unexpected project/task/Git mutation, model mismatch, unapproved network/auth prompt, SDK incompatibility, uncertain verification, or quota/admission denial. Do not retry automatically. Do not relax scope, verification or quota controls to force completion. A failed or partial attempt is a valid result.

## Observation and adjudication worksheet

Complete one row per arm; retain raw evidence only in the disposable experiment directory and redact account identifiers/secrets.

| Field | A direct CLI | B ProjectCTL |
|---|---|---|
| Base SHA / final SHA | | |
| Spec SHA-256 / protected-file digests | | |
| Model / reasoning / runtime version | | |
| Sandbox / network / approval settings | | |
| Start/end UTC / observed wall seconds | | |
| Input/output/cache usage or `unknown` | | |
| Prompts, interventions, retries | | |
| Changed paths / protected-path changes | | |
| Fixed test command and exit/result | | |
| Independent acceptance outcome | | |
| Git history effects | | |
| Task/run/evidence final state (B only) | | |
| Stop condition or deviations | | |

An adjudicator who did not operate either arm compares the resulting patch against the frozen spec and independently runs the fixed acceptance tests. Mark each criterion pass/fail/uncertain with evidence path: normalization trims outer whitespace and lowercases ASCII; non-string raises `ValueError`; blank-after-trim raises `ValueError`; protected policy/test files unchanged; no out-of-scope paths; no unauthorized Git history effects. Record defects and unsupported claims even if a test passes.

## Expected artifacts

- immutable fixture manifests: base SHA, spec digest and protected digests for both copies
- sanitized command/state transcript for each arm, including observed intermediate ProjectCTL run states
- per-arm diff, test output, final Git status/SHA, and (B) Beads/task/run/verification/integration evidence
- completed worksheet, deviations and adjudicator decision
- D1 result marked feasibility-only; no statistical or general quality claim from one pair
