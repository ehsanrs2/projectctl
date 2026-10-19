# D1 policy preparation recovery — exact Beads ignore false positive

**Observed:** 2026-10-19. **Status:** D1_POLICY_PREP_BLOCKED_BY_TOOL_BUG; fixed on the research branch, not yet operator-qualified. No paid inference or worker execution occurred.

## Operator evidence

- After `projectctl init`, the disposable `ctl` fixture remained at setup commit `1b38e7526c00009fd44a910e438d74969f00b3c9` with the expected five untracked ProjectCTL bootstrap files.
- `test_d1_prepare_policy.py`: 4/4 existing tests passed.
- Both Preview and Apply of `d1_prepare_policy.py` returned `BLOCKED / ValueError / unexpected Beads ignore content`.
- The inspection probe reported no verification catalog; `git add` failed because scope/verification files were never created. The attempted setup commit created nothing. No manual files were cleaned, reset or overwritten.
- `projectctl quota --json`: the isolated `openai-default` account had the default `manual` quota provider, observed at the epoch, with **unknown** five-hour and weekly ratios; `stale=true`, mode `conservation`.
- `projectctl next --json` found only `d1ctl-lh4` but ruled it ineligible for `quota_unknown`; `selected_task_id=null`.
- Thus there are **two independent gates**: policy script false positive and missing trusted quota observation.

## Root cause and research-only fix

The operator's actual 7-line `.gitignore` has rules `.dolt/` and `.beads/proxieddb/`. The old check `".beads/" in original_ignore` matched the beginning of **`.beads/proxieddb/`**, falsely treating it as a top-level `.beads/` rule. The intended guard now reads exact, non-comment/nonblank ignore lines and compares **`.beads/` as a complete pattern**. It accepts the observed Beads 1.3.1 rules; missing `.dolt/`, an exact forbidden top-level `.beads/`, and an already-present `.projectctl/` rule remain guarded.

Four regression tests have been added to cover precisely those cases; unit count is now eight. A standalone reproduction of these four matcher cases passed in isolated Python. The full updated eight-test suite, helper Preview/Apply and policy verification still require the owner's host run. No ProjectCTL product/runtime code or M6.0 file was edited.

## Operator recovery — no re-init, no manual cleanup

1. Pull latest `research/advisory-skills-eval` after verifying repository cleanliness.
2. In the dedicated D0 Python 3.12 virtual environment, run `python -m unittest -v experiments/dogfooding/test_d1_prepare_policy.py` (expected **8 tests**) and `python -m compileall -q experiments/dogfooding/d1_prepare_policy.py`.
3. Use the existing fixture and isolated `PROJECTCTL_HOME`. Run guarded Preview; require `PREVIEW_ONLY`. Run guarded Apply once; require `POLICY_FILES_WRITTEN`. **Do not run `projectctl init` or `bd init` again.**
4. Confirm the verification profile is detected, the policy files bind only task `d1ctl-lh4`, and the only changed/added human-managed paths to stage are `.gitignore`, `docs/PROJECT_STATE.yaml`, `projectctl.scope.yaml`, `projectctl.verification.yaml`. Do not stage `.projectctl/`, SQLite, Dolt or `.beads/`.
5. Commit just those four paths inside the **disposable ctl fixture**, preserving both original source baseline and setup SHA. Leave the `direct` repo untouched.
6. The default manual quota snapshot is **unknown**, not evidence of an exhausted Codex account. Switch the **isolated** account's quota provider to `codex_app_server` using the supported `projectctl quota provider --project CTL --set codex_app_server --json` command. Then `projectctl quota --project CTL --json` retrieves an official app-server rate-limit snapshot, and `projectctl next --project CTL --json` should be reassessed. This starts a local Codex app-server process and can contact the authenticated quota endpoint; it does not run a model turn. If unavailable/ambiguous, report the actual quota error or unknown state; **never invent ratios** or force admission via `quota set` with arbitrary numbers.
7. Do not start `run prepare` or either paired worker until real quota permits scheduling, verified scope is required, catalog is recognized, task remains uniquely ready, zero remotes and Git-clean, and the single-actor/no-concurrent-reclaimer condition is confirmed.

## Decision

`D1_NO_GO` for inference remains appropriate. The setup helper failure caused no loss of work or need to rebuild either fixture. Treat `quota_unknown` as an independent genuine admission gate rather than hiding it with a policy change.
