# D2 CTL post-Direct read-only readiness — operator PASS (2026-10-21)

**Observed decision:** `D2_CTL_READ_ONLY_PREPARE_GATE_PASS__CLAIM_NOT_AUTHORIZED`. This is a completed *read-only* pre-prepare gate, not a Beads claim or paid worker authorization.

## Operator-supplied evidence

After a fast-forward `227e327..01f7479` on `research/advisory-skills-eval`, the operator ran the isolated venv test module `experiments.dogfooding.d2.test_d2_ctl_readiness`. All **13/13 tests passed**. The subsequent `d2_ctl_readiness --read-only` audit returned success and `D2_CTL_READINESS_EXIT=0`.

Confirmed in the audit's JSON output:

- `beads_task=open_unclaimed`
- `ctl_run_count=0`
- `ctl_worktree_clean=true`
- `paid_worker_started=false`
- `policy_head=3c69dd42497acadadc5d64e7b4abe5d412b309f5`
- `direct_base=32836ea5633230e50fb9d907dcdba83e357bcfc6`
- `projectctl_task=d2ctl-g4q`
- `direct_result=SEMANTICALLY_ASSESSED_PASS_WITH_EDGE_RISK`
- Direct output source hashes: `cli.py=a9eec60be23a186805c1275f53ed6ece80ad63049d27a0c64ed9a24685d15451`, `parse.py=0eda41e5175e353773c49bdb41dcc41293f6f9df1b073385c75a7d7722065ef3`, `report.py=43e9ef46a244083c66fce87759028e90cb9344c5b782ebb89cdcd0d95640d625`.
- Frozen verification profile: `canonical-json-sha256-v1:3e8b2ad56b3306fc92ce5e98034e1e4766a496448d49810d2d29a9240b614cbc`.
- CTL scoped writes limited to `d2events/cli.py`, `d2events/parse.py`, `d2events/report.py`.
- CTL worker contract `gpt-6-luna` with `medium`, `openai-codex 0.160.0`, adapter `0.41.0`. The Direct CLI used `0.163.0`; these different interfaces/versions remain a methodological caveat.
- Reference Direct result: 32.809408731 seconds worker duration, input tokens 196,969 (cached subset 185,088), output 2,335 (reasoning subset 243). Token subsets are not additive.

The original two CTL offline qualification deviations—the `POLICY_SHA` wrong-module import and the false-porcelain test mock—remain documented separately. This final 13/13 result establishes that both corrections are now working in the operator's actual environment. Do not erase prior failed gates from process-overhead accounting.

## Next authorization boundary

The source of truth for `projectctl run prepare` is `projectctl/cli/m11.py`. The actual command is `projectctl run prepare --strategy direct --project "$CTL" --json`, optionally with a separately frozen integration target ref. Unlike `--read-only`, this command invokes `prepare_next_run`; it allocates the canonical Beads claim, creates run/worktree and durable local manifests. **It must not be executed without a separate affirmative owner decision** because it mutates control-plane state, although it does not itself start an LLM worker.

At owner authorization, a single no-retry prepare package should independently (a) check pinned research code HEAD/clean state and the independent untouched Direct candidate, (b) refresh the official canonical Codex quota and Scheduler before claim, (c) restrict the new evidence output to the isolated D2 path with private permissions, (d) call prepare exactly once, and (e) inspect the resulting plan's `task_id=d2ctl-g4q`, `strategy=direct`, `base_commit=3c69dd...`, provider/model/effort and execution policy and Beads task/status/worktree. If anything fails, capture evidence and stop without retry; never silently fix a running pair.

`projectctl run start RUN_ID` is a **different paid authorization gate**, requiring a new fresh quota check, start instrumentation and an explicit separate owner go-ahead. Further independent verification, candidate adjudication, local integration and Beads task closure remain separate phases.

**State:** `D2_CTL_POST_DIRECT_READINESS_PASS / PREPARE_OWNER_AUTHORIZATION_PENDING / CTL_WORKER_NOT_STARTED / DIRECT_ARTIFACTS_FROZEN`.
