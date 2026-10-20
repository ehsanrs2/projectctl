# D2 Direct harness offline qualification — 19/19 tests and preview PASS

**Date:** 2026-10-20  
**Operator result:** `D2_DIRECT_HARNESS_PREVIEW_PASS__NO_PAID_CALL`  
**Decision:** `D2_DIRECT_HARNESS_OFFLINE_QUALIFIED__OWNER_PAID_AUTHORIZATION_PENDING`

## Observed terminal evidence

The operator fast-forwarded the isolated research branch `research/advisory-skills-eval` from `dc6177d` to `d95b9e2` and executed the repaired `experiments.dogfooding.d2.test_d2_direct_manual` suite:

- All **19/19** tests passed in **0.037 seconds**, including the two new regression tests for terminal newline normalization in `git rev-parse HEAD` and preservation of Git porcelain's significant leading status-space.
- Subsequent direct harness `--preview` returned `D2_DIRECT_HARNESS_PREVIEW_PASS__NO_PAID_CALL` and nested `D2_NO_INFERENCE_PREFLIGHT_PASS`.
- The direct prompt SHA-256 remained `b4aa6e48872f07d1d608bf24a5beeed45ac9e68656defc52aa8c632b63c50f65`.
- The direct fixture is `direct_clean=true`, and both pinned frozen Git heads were accepted by the nested preflight.
- Arm order remains `[direct_cli, projectctl]`.
- Proposed local evidence path: `/home/ai/.local/state/projectctl-dogfood-d2/observations/direct-attempt-1`. The prior blocked Preview explicitly had `existing_evidence_path=null`; the new Preview does not write to the evidence directory.
- `paid_execution=NOT_AUTHORIZED_OR_STARTED`; no D2 model turn, Beads claim, worker start or direct source mutation was observed.

## Static audit of the future execution path

The checked-in `d2_direct_manual.py` keeps `--execute --ack-paid` separate from `--preview`. Execution checks the same frozen preflight, re-reads **fresh official** `codex_app_server` quota and Scheduler selection for the sole task `d2ctl-g4q`, requires high-confidence canonical `codex` bucket with sample age at most 120 seconds and sufficient effective MEDIUM quotas, and refuses an existing evidence directory.

Its intended single independent `codex-cli 0.163.0` call pins `gpt-6-luna` and medium reasoning, `workspace-write`, `approval_policy=never`, network disabled, `--ephemeral`, `--ignore-user-config`, `--ignore-rules`, `--strict-config`, `--disable apps` and `--disable plugins`. It records UTC timestamps, monotonic inference wall time, JSONL events, provider-reported usage when exposed, Git diff and ignored paths, frozen hashes, and the independently run 26-test suite, without automatic retry, integration or remote publication. Files are written in a private evidence directory (process umask 077).

This is **source-level inspection plus offline testing**, not execution-time proof that flags were honored, a model request was delivered, tools were truly equivalent, or that the model implementation will pass the 26 frozen tests. Direct CLI `0.163.0` and CTL SDK/bundled CLI `0.160.0` remain explicit confounders. The 26-test verification suite has not been executed against a generated solution.

## Owner authorization gate

The **next scientific step** is a **separate explicit owner decision** to permit **exactly one** paid Direct CLI turn on the unchanged D2 `direct` fixture, with no retries or hotfix during the same pair. Do not run the command merely because offline Preview passed. No ProjectCTL worker is authorized by a Direct-only decision.

If authorized, the already reviewed runner requires `--execute --ack-paid` and independently rechecks fresh quota/admission at launch. If quota, model, flags, frozen heads or source integrity drift, stop and retain evidence; do not bypass quotas. The Direct candidate must be independently checked after the run before considering the separate ProjectCTL arm. No claims about superiority, time/token savings or end-to-end effort are justified before both arms and human adjudication.

**Snapshot state:** `D2_OFFLINE_DIRECT_READY / FIRST_PAID_DIRECT_TURN_NOT_AUTHORIZED / CTL_NOT_STARTED / FROZEN_PAIR_INTACT`.
