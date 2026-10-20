# D2 Direct harness Preview false HEAD drift — offline-only repair (2026-10-20)

**Observed decision:** `D2_DIRECT_HARNESS_PREVIEW_BLOCKED_GIT_OUTPUT_NEWLINE`; no inference, no worker/task claim, no paid Codex turn, no Direct evidence directory. The observed local output reported `existing_evidence_path=null`.

## Operator evidence

The operator fast-forwarded research branch from `7cde6fc` to `dc6177d`, then ran 17 offline `test_d2_direct_manual` tests. **All 17 passed** (`Ran 17 tests in 0.025s; OK`). Immediately afterwards `d2_direct_manual --preview` returned exit 2, with:

```json
{"decision":"D2_DIRECT_HARNESS_BLOCKED_NO_MODEL_CALL_OR_UNKNOWN_IF_POST_START","error_type":"RuntimeError","reason":"Either frozen Git head drifted","existing_evidence_path":null}
```

This was a **read-only Preview failure**, not evidence of actual fixture Git-HEAD mutation: the invoked independent `d2_no_inference_preflight` succeeded before the Harness's second comparison, and a source inspection found a deterministic output-format bug at `d2_direct_manual.py` lines 39–49.

The helper `run_read(...)` returned `subprocess.run(..., text=True).stdout` *including the terminal newline*; the wrapper `git(...)` then compared `git rev-parse HEAD` with frozen SHA strings without a trailing newline. This comparison always failed when `git` exited normally with a standard one-line SHA response.

## Research-only fix

Only in `experiments/dogfooding/d2/d2_direct_manual.py`, the `git` helper now removes **terminal `\n` characters** with `.rstrip("\\n")`, not `.strip()`. This keeps the significant initial space in `git status --porcelain` (e.g. ` M source.py`) unchanged. `run_read` is deliberately kept raw so other command JSON outputs are not changed. No code in ProjectCTL runtime or the frozen D2 fixtures is touched.

Two new negative/positive regression tests in `test_d2_direct_manual.py` verify (a) an actual fresh local Git repository's HEAD compares byte-for-byte after normalization, with clean status, and (b) left-column Git porcelain status and untracked paths are preserved while extra terminal newlines are stripped. Test definitions increased from **17 to 19**, pending the owner's rerun on the actual pinned venv. The prior 17/17 success is retained as historical evidence, not falsely represented as current 19/19 success.

## Next user-owned gate — NO PAID EXECUTION

```bash
cd /home/ai/project/My/projectctl-advisory-lab
git pull --ff-only origin research/advisory-skills-eval
VENV="$HOME/.local/share/projectctl-dogfood-d0/venv"
export PATH="$VENV/bin:$PATH"
export PROJECTCTL_HOME="$HOME/.local/state/projectctl-dogfood-d2/ctl-home"
export BD_ACTOR=d2-dogfood-owner
export BD_DISABLE_METRICS=1 DOLT_DISABLE_EVENT_FLUSH=1 DO_NOT_TRACK=1 PYTHONDONTWRITEBYTECODE=1
"$VENV/bin/python" -B -m unittest -v experiments.dogfooding.d2.test_d2_direct_manual &&
"$VENV/bin/python" -B -m experiments.dogfooding.d2.d2_direct_manual --preview
```

Expected `Ran 19 tests`, `OK`, and `D2_DIRECT_HARNESS_PREVIEW_PASS__NO_PAID_CALL`. If this fails again, **do not execute paid inference** or rewrite/rebuild either fixture; preserve the exact diagnostic. Before any future paid attempt the actual running harness must be reviewed and freshly qualified (including official quota gates). Do not invoke `--execute --ack-paid` or ProjectCTL `run prepare/start` in this step.

**State:** `D2_DIRECT_HARNESS_NEWLINE_BUG_FIXED_ON_RESEARCH / 19_TESTS_OPERATOR_PENDING / DIRECT_ARM_PRISTINE_AS_LAST_AUDITED / NO_INFERENCE`.
