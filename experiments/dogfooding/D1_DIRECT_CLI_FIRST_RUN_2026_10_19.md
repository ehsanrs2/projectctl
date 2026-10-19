# D1 direct Codex CLI control arm — single-turn implementation and frozen test pass

**Operator report:** 2026-10-19. **Decision:** `D1_DIRECT_CLI_FIXED_TEST_PASS__PENDING_INDEPENDENT_SOURCE_REVIEW`. The direct worker succeeded on the first invocation; the fixed six-test suite passed; the actual direct `user_id.py` source/diff has not yet been shared with the reviewer.

## Direct arm observations

- Research branch fast-forwarded through `f274505`; Bash syntax check for `experiments/dogfooding/d1_direct_cli_manual.sh` succeeded.
- Original independent `direct` Git baseline: `da9379c70571c9366f5adfccecdfab148c814fc2`; ProjectCTL `ctl` integrated candidate: `2089c04c5fc679cfb4353a2cef2c2f25c83fa40d`, left unchanged.
- Fresh Codex CLI `0.163.0`, explicitly selected `gpt-6-luna`, `medium` reasoning, `workspace-write` sandbox, `approval_policy=never`, tool-network disabled. Single isolated `codex exec` invoked with `--json` and disposable direct fixture. Prompt SHA-256: `bee02f4b3f0f98b789569c2e8e161726999779a6b708a5d2b5e99d28f0cbb9d8`.
- Direct invocation started **2026-10-19T12:23:50Z** and finished **12:24:05Z**; wall time **15 seconds**; process exit 0.
- JSONL event counts: `thread.started=1`, `turn.started=1`, `turn.completed=1`, `item.completed=5`, `item.started=3`, errors empty. **One turn, no retry**.
- Usage from completed turn: `input_tokens=56,720`; `cached_input_tokens=50,304` (**subset** of input); noncached input `6,416`; `cache_write_input_tokens=0`; `output_tokens=438`; `reasoning_output_tokens=64` (not an extra output category for naive billing). Usage for ProjectCTL successful SDK run remains **unknown** with available evidence; do not compare token cost numerically.
- Source-root postconditions: exactly one changed file, `user_id.py`; Git HEAD unchanged; protected files unchanged; no remote or history modification; ProjectCTL fixture unchanged.
- Independent fixed `python3 -B -m unittest -v test_user_id.py`: all **six** frozen tests passed, exit 0.
- Harness concluded `D1_DIRECT_CLI_IMPLEMENTED_AND_FIXED_TEST_PASS__PENDING_HUMAN_ADJUDICATION`, exit 0.
- Raw local evidence: `$HOME/.local/state/projectctl-dogfood-d1/observations/direct-attempt-1/`. Do not publish raw JSONL or account metadata without review.

## Paired feasibility comparison (provisional)

| Measure | Research-patched ProjectCTL | Direct Codex CLI |
| --- | --- | --- |
| Fixture | `ctl` (setup-local policy commits) | `direct` (frozen source baseline) |
| Model/reasoning | `gpt-6-luna`, `medium` | `gpt-6-luna`, `medium` |
| Completed coding turns | One completed in D1-R3 | One completed in first attempt |
| Observed successful start/exec command wall time | **24 s** | **15 s** |
| Frozen acceptance tests | 6/6 passed | 6/6 passed |
| Changed path | only `user_id.py` | only `user_id.py` |
| Canonical completion | `run=passed`, Beads `closed`, local integration | Direct working tree modified; not committed |
| Attempts to first completion | **4** (three orchestration failures) | **1** |
| Token usage | **Unknown** | 56,720 input (50,304 cached), 438 output |

**Important methodological caveats:** 24s for ProjectCTL `run start` versus 15s for `codex exec` measures *different interfaces* (Codex Python SDK vs CLI, differing prompt/control-plane and startup). It excludes ProjectCTL preparation, verification, integration, intervention, recovery, patch engineering, and failed runs. Do not claim a quantified end-to-end 9-second advantage or statistically meaningful speed/quality superiority. One pair is a feasibility observation, not a population estimate. The actual direct implementation is pending human-independent semantic inspection; test pass alone is not enough.

## Next read-only gate

Use `experiments/dogfooding/d1_direct_candidate_audit.sh --read-only` to capture/print the exact direct `user_id.py` source, patch, protected SHA-256, clean frozen baseline HEAD, shared spec, and fixed test output. Independently assess ASCII-only lowercasing, non-ASCII preservation, whitespace semantics, types and blank rejection. Do not run a model, Git commit, ProjectCTL, Beads mutation or another test during this gate. Then record `D1_PAIRED_EVALUATION_COMPLETE` with technical defects and owner interactions retained.
