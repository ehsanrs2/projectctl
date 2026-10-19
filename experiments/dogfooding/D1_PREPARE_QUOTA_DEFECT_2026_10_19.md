# D1 first ProjectCTL prepare attempt — quota resource-class consistency defect

**Observed:** 2026-10-19, preclaim attempt started `10:17:55Z`. **Result:** `D1_PREPARE_FAILED_PRECLAIM`. No `run start` and no model turn. The existing first D1 attempt is preserved as a **failed result against the original experimental runtime**.

## Operator evidence

- Before attempt, official Codex App Server quota snapshot at `2026-10-19T10:09:30.332109Z`: five-hour raw `0.98` (effective `0.88`), weekly raw `0.61` (effective `0.51`), mode `normal`, `stale=false`.
- `projectctl next`: selected `d1ctl-lh4`, `eligible=true`, `reasons=[]`, model profile `balanced`, reasoning `medium`.
- Operator's preflight printed `D1_CONFIG_AND_POLICY_PASS`; Beads-ready and Scheduler selection checks succeeded.
- `projectctl run prepare --strategy direct --project CTL --json` printed `Execution quota policy changed before task claim acquisition.` to stderr. Script `set -e` stopped. No `PREPARE_PASS`, `start`, worker result or integration occurred.
- This failure occurs in source `projectctl/application/execution.py:500-511` after a run record is created and marked `preparing`, where non-null `_prepare_quota_reason` transitions it to `failed` with terminal reason `quota_exhausted` before `claimer.claim`. Inspect `projectctl runs --json` and `bd show d1ctl-lh4 --json` on the operator's machine to independently confirm durable state before retrying. `prepare.json` from the failed CLI may be empty due to stdout redirection; do not treat it as proof of no durable run.

## Confirmed root cause from source

The Beads task has `issue_type=task` and no explicit `resource_class`; normalization sets `NormalizedTask.resource_class=UNKNOWN`. Scheduler calls `effective_resource_class(task)` (which conservatively derives `MEDIUM` for generic tasks) before quota eligibility/model routing. Execution had **four** inconsistent raw accesses to `task.resource_class`:
1. `_validate_plan_inputs` legacy preflight;
2. `_prepare_quota_reason` preclaim check;
3. `_quota_monitor` live checkpoint monitor constructor;
4. `_evaluate_current_worker_quota` start-time check.

`QuotaManager.eligible_for_resource(ResourceClass.UNKNOWN, ...)` always returns False, irrespective of healthy quota. Thus preclaim failure is a **source-level deterministic mismatch** and not evidence that 98% raw five-hour quota is insufficient.

## Scoped research-branch fix

On `research/advisory-skills-eval` only, `projectctl/application/execution.py` now imports `effective_resource_class` and uses it in those four quota boundaries. It **does not** change default reserve/thresholds, Task's provider data, Scheduler, normalized task schema, Beads, or M6.0 main branch. Added six regression tests in `experiments/dogfooding/test_d1_quota_resource_consistency.py` to check:
- same unknown-origin Beads Task is admitted preclaim with official sufficient quota;
- insufficient quota is still denied;
- start-time quota recheck uses MEDIUM;
- live checkpoint monitors MEDIUM and flags a genuine drop;
- legacy preflight uses MEDIUM;
- low-level manager still denies unresolved UNKNOWN when no conservative mapping has been applied.

**Qualification status:** The scoped code/test changes have been committed to the research branch. They have **NOT** been executed in the operator's D0 virtualenv yet. Verify that importing `projectctl.application.execution` resolves to this research worktree, then run the six new tests before any rerun. A non-editable site-packages installation may require deliberate test-env-only reinstallation; do not modify the production environment automatically.

## Next operator checks (read-only and offline)

1. Pull research branch, inspect/import source module path and run `python -m unittest -v experiments/dogfooding/test_d1_quota_resource_consistency.py`.
2. In the isolated fixture, `projectctl runs --project CTL --json`, `bd -C CTL show d1ctl-lh4 --json`, `git status --porcelain`, `git worktree list --porcelain`. Expect one failed first attempt and Beads task still `open`, but **do not infer the persisted state solely from stderr**.
3. Re-read official quota and next decision before manually approving another **single** ProjectCTL attempt. Use a *new* evidence directory (e.g. `ctl-attempt-2`); preserve previous evidence.
4. If the first run is anything other than `failed` with `quota_exhausted` and no claim, stop rather than auto-recover/retry. If regression tests fail, stop and assess; do not weaken quota rules.

## Evaluation integrity

D1 original-runtime feasibility attempt has a real **NO-GO** result attributable to ProjectCTL, not to Codex. Any subsequent successful run with this patch is labeled **D1-R1 / research-patched ProjectCTL**, not original stock M6.0 behavior. Comparing its quality/time to direct Codex CLI must disclose this code deviation and initial failure, including preparatory effort. No blanket production compatibility claim follows.


## Independent owner-run qualification (2026-10-19)

The owner ran the patched research source using the isolated D0 Python environment, and reported:

- `projectctl.application.execution.__file__` exactly resolves to `/home/ai/project/My/projectctl-advisory-lab/projectctl/application/execution.py`.
- All **6/6** new `test_d1_quota_resource_consistency.py` regression tests passed (preclaim sufficient/insufficient, legacy preflight, start revalidation, checkpoint monitor, low-level UNKNOWN protection).
- `projectctl runs --project CTL --json` exposed **one** durable prior run:
  - `run_id=run-88361fe2431e4e299a0f4b9c506c50fa`;
  - `status=failed`, `terminal_reason=quota_exhausted`;
  - `started_at=null`, `worker_thread_id=null`, `candidate_commit=null`;
  - `lease_owner=null`, `lease_expires_at=null`; base `7388896be4a7ba46770ae76c7cd5480f0cd9e27b`.
- `bd show d1ctl-lh4 --json` reported `status=open` with no `assignee`, so the task remains unclaimed/ready, pending fresh live admission.
- Fixture `ctl` `git status --short --untracked-files=all` was **empty**.
- The diagnostic ended with `D1_DIAGNOSTIC_PASS` and `DIAGNOSTIC_EXIT_CODE=0`. The separately printed blank `BASH_EXIT_CODE=` is a shell `PIPESTATUS` capture issue in the reporting wrapper, not a failed test.

**Decision updated:** `D1_R1_PATCH_OFFLINE_QUALIFIED`; first original-runtime attempt remains `FAILED_PRECLAIM`. No second `prepare`, `start`, model call, verification or integration has yet been reported. Research-only modified runtime and its success, if any, must remain distinguishable from the unpatched baseline.
