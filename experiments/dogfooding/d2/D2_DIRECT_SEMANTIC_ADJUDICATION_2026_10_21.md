# D2 Direct source, provenance and independent semantic assessment — 2026-10-21

**Observed status:** `D2_DIRECT_CANDIDATE_EVIDENCE_AUDIT_PASS__SEMANTIC_REVIEW_PENDING` from owner-owned local audit.  
**Assistant assessment based on operator-supplied full source:** `D2_DIRECT_SEMANTIC_REVIEW_PASS_WITH_EDGE_RISK` (not an owner approval and not a claim of formal program proof).  
**Paid ProjectCTL:** not started.

## Local evidence reported by operator

- Research checkout fast-forward: `d15c7a8..c2b305d`.
- All 13 newly defined audit tests passed (`Ran 13 tests in 0.002s; OK`).
- Independent read-only audit returned `D2_DIRECT_CANDIDATE_EVIDENCE_AUDIT_PASS__SEMANTIC_REVIEW_PENDING`, `D2_AUDIT_EXIT=0`, **26/26** frozen tests passed.
- Original Direct Git HEAD remains `32836ea5633230e50fb9d907dcdba83e357bcfc6`; CTL Git HEAD remains `3c69dd42497acadadc5d64e7b4abe5d412b309f5`. Exactly these three Direct files are modified: `d2events/cli.py`, `d2events/parse.py`, `d2events/report.py`. No CTL paid execution or fixture modification.
- Single Codex CLI thread and single completed turn; no repeated invocation reported. Worker monotonic duration: **32.809408731s**; independent test duration: **0.165026099s**.
- Direct usage: `input_tokens=196969`; `cached_input_tokens=185088` (subset of input); `cache_write_input_tokens=0`; `output_tokens=2335`; `reasoning_output_tokens=243` (subset of output). Derived uncached input = 11,881 tokens. Do not add the subset counters to token totals. The large cached component must be disclosed in pair comparisons.
- Full raw JSONL and worktree source remain local and **must not** be committed or copied into CTL.
- SHA-256 of Direct outputs:
  - `d2events/cli.py`: `a9eec60be23a186805c1275f53ed6ece80ad63049d27a0c64ed9a24685d15451` (30 lines).
  - `d2events/parse.py`: `0eda41e5175e353773c49bdb41dcc41293f6f9df1b073385c75a7d7722065ef3` (82 lines).
  - `d2events/report.py`: `43e9ef46a244083c66fce87759028e90cb9344c5b782ebb89cdcd0d95640d625` (30 lines).

## Source-level semantic review against frozen SPEC

**Parser:** `parse_events` enumerates the input iterable starting at physical line 1, skips whitespace-only lines, accepts only string rows, loads JSON with `object_pairs_hook` that rejects duplicate keys (including nested objects), checks root object type and exact four-key set and string values, rejects duplicate case-sensitive event IDs, validates ASCII anchored ID and user ID patterns and actions. User IDs are stripped and ASCII lowercased; timestamp uses a strict `YYYY-MM-DDTHH:MM:SSZ` ASCII regex plus real `datetime` calendar/time validation. All intended validation failures produce a sanitized `ValueError("invalid event on line N")` without raw event echo.

**Aggregation:** `build_report` counts `login/logout/purchase` per canonical user, tracks total and lexical min/max of fixed-width canonical UTC timestamp strings (equivalent to chronological ordering on this domain), sorts users lexically and returns the frozen empty report for no events.

**CLI:** `argparse` enforces exactly one file path with invalid-argument exit 2, `open(..., encoding="utf-8")` streams iterable lines, handled I/O/encoding/validation errors exit 1 and write only stderr, and success emits one sorted compact JSON line followed by newline. All imported dependencies are stdlib or the two D2 sibling modules. No network, Git, external shell or file-write implementation was observed.

**Caveats/limits:** This was inspection of source displayed in the operator's audit transcript, not independent execution of new test cases. Pathological deeply nested JSON can raise Python `RecursionError` rather than a line-numbered `ValueError`; this extreme untested edge is logged as a residual robustness risk, not silently fixed post-competition. No mutation or retry of Direct source is authorized. Tests cover 26 frozen examples but not every possible adversarial input. The observed `codex-cli 0.163.0` vs ProjectCTL SDK/runtime `0.160.0` version and their prompt/tool interfaces remain confounders. CLI stderr for nonexistent filenames can include the pathname; it does not show raw event contents.

## Decision and next gate

The assistant's semantic assessment is **PASS with recorded edge limitation** for the frozen D2 practical contract. Owner's human adjudication is still distinct: the user did not explicitly authorize model execution in the CTL arm simply by posting Direct logs. Keep Direct worktree and `direct-attempt-1` evidence immutable, with zero direct reruns. Proceed with **read-only CTL readiness and instrumentation qualification only**, on research branch `research/advisory-skills-eval`. A subsequent CTL run prepare will acquire canonical Beads task `d2ctl-g4q` and create local run/worktree; that mutation needs its own explicit operator go-ahead. A separate paid `run start` requires explicit paid authorization and fresh high-confidence canonical Codex quota immediately before execution. Verify/integrate stay separate; no automatic publication.

**Next state:** `D2_DIRECT_SEMANTIC_PASS_WITH_EDGE_RISK / CTL_PREPARE_NOT_AUTHORIZED / CTL_INFERENCE_NOT_AUTHORIZED`.
