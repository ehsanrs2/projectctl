# D2 direct arm — first paid turn completed, scope and frozen tests pass (operator evidence)

**Observed state:** `D2_DIRECT_TESTS_AND_SCOPE_PASS__HUMAN_REVIEW_PENDING`. The Direct CLI coding arm completed one paid model execution. This is **not** a semantic/independent human approval, and no ProjectCTL worker or integration is authorized.

## Operator's completed execution

After a shell window closed unexpectedly, the operator opened a new shell and performed a read-only inspection of the frozen repositories, running-process list and Direct evidence directory. The output established:

- Research branch HEAD `d15c7a83125195c0bd5fda9762a96c2b828a7136` (the exact previously approved research snapshot).
- Direct worktree has only three modified source paths: `d2events/cli.py`, `d2events/parse.py`, `d2events/report.py`. The independent `ctl` worktree shows no changed paths.
- No matching `d2_direct_manual` or `codex.*exec` process was listed at observation.
- Evidence path **exists**: `$HOME/.local/state/projectctl-dogfood-d2/observations/direct-attempt-1`. Important files include `codex-events.jsonl` (23,804 bytes), `codex-stderr.log` (0 bytes), `direct.patch` (5,236 bytes), `direct-run-summary.json` (2,366 bytes), frozen unittest stdout/stderr, prompt and preflight, and the quota/Scheduler observation at admission. Preserve these originals. Do not repeat the Direct arm or delete/reset the fixture.
- The independent operator read of `direct-run-summary.json` gives:
  - `status=D2_DIRECT_TESTS_AND_SCOPE_PASS__HUMAN_REVIEW_PENDING`
  - `codex_exit_code=0`
  - `timed_out=false`
  - `codex_wall_monotonic_seconds=32.809408731`
  - `verification.exit_code=0`
  - `verification.test_count=26`
  - `verification.wall_monotonic_seconds=0.165026099`.

These numbers are *observed run evidence* and exclude setup, CLI start-up outside the timing boundary, operator review, and later ProjectCTL governance. Do not label `32.809408731s` as full experiment end-to-end time or infer token usage from file sizes.

## Shell-window diagnostic

A prior ChatGPT command block used `set -euo pipefail` at the top level of the user's interactive shell. Such options can cause a shell to exit on a non-zero command and are not an appropriate persistent interactive-shell setting; a window that is configured to close when its shell exits may disappear. The evidence now proves that the Direct run **completed**; the specific window closure mechanism was not independently captured. In future, keep strict settings scoped to a child `bash -c` process or script, never the user's long-lived interactive shell.

## Next step — independent candidate inspection, no inference

Inspect the *actual* generated three source files, frozen protected hashes and Git states, Direct JSONL event shape, reported input/output/cache/reasoning token usage (only when actually present), recorded quota-at-admission, independent 26-test evidence, source diff and suspicious external calls. Distinguish what can be checked mechanically from true semantic review of the implementation against frozen D2 SPEC. Do not publish raw `codex-events.jsonl`, prompt, or logs to GitHub, and do not copy Direct source/results into the untouched `ctl` arm.

Only once the Direct patch is independently accepted may the owner separately authorize ProjectCTL `prepare` and later a paid `start`; **neither** is part of Direct acceptance. Same paired design: Direct CLI `0.163.0`, ProjectCTL SDK `0.160.0`, `gpt-6-luna`/medium, network disabled, deny-all, exactly three writes and 26 frozen tests. The difference in interface/version must remain visible in evaluation.

**State:** `D2_DIRECT_TESTS_AND_SCOPE_PASS / SEMANTIC_ADJUDICATION_PENDING / CTL_ARM_UNRUN / DIRECT_RETRY_FORBIDDEN`.
