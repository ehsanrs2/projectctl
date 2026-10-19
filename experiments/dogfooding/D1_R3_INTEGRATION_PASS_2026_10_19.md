# D1-R3 integrated locally — ProjectCTL arm complete (2026-10-19)

**Observed result:** `D1_R3_LOCAL_INTEGRATION_PASS`. Research-patched ProjectCTL has completed its first end-to-end `prepare → start → verify → integrate` task in the disposable D1 `ctl` fixture. The direct Codex CLI arm is **still unrun**.

## Operator integration evidence

- Research branch fast-forwarded from `842618f` to `71efbc3`, and `d1_r3_integrate_manual.sh` passed Bash syntax check.
- One manual `run integrate` command invoked at `2026-10-19T11:59:12Z` for run `run-e467c1fa8f0f448b8497c9530c49b326` and approved candidate `2089c04c5fc679cfb4353a2cef2c2f25c83fa40d`.
- Preflight printed `D1_INTEGRATION_PRECHECK_PASS; BEADS_CLAIM_VALIDATED`: durable candidate, passing evidence and canonical Beads claim matched.
- Postflight `run.status=passed`, `task.status=closed`, `task_completed=true`, `worktree_cleaned=true`, `remote_publication=false`. `claim_released=false` is consistent with task-native Beads claim policy, not evidence of active orphan ownership after canonical closure.
- Primary `ctl` target was fast-forwarded locally to `2089c04c5fc679cfb4353a2cef2c2f25c83fa40d`. `direct` still at frozen source baseline `da9379c70571c9366f5adfccecdfab148c814fc2`.
- Script returned `D1_R3_INTEGRATED_LOCAL_ONLY; DIRECT_ARM_UNTOUCHED`, exit 0.
- Isolated evidence: `$HOME/.local/state/projectctl-dogfood-d1/observations/ctl-attempt-4/integration/`.

## End-to-end feasibility interpretation

The sole implemented code change was `user_id.py`, reviewed independently for the frozen spec (trim outer whitespace; strings only; ASCII-only lowercasing; preserve interior whitespace and non-ASCII; reject invalid or blank input). The independent frozen six-test unittest, scope, diff and workspace-stability checks passed. Verified candidate and target SHAs matched.

This successful patched D1-R3 run **does not erase** the original preclaim `UNKNOWN` quota mismatch, R1 metadata-only capability mismatch or R2 Codex HTTP 400 invalid structured-output schema. At least three orchestration defects and owner diagnostic/patching interventions occurred before the successful run. Worker command time on R3 start was 24 s; complete wall time, patch development overhead, and all token usage are not fully measured. No statistical performance claim is defensible from one pair.

## Direct comparison gate

The next manual arm uses the pristine `direct` fixture at `da9379c70571c9366f5adfccecdfab148c814fc2`, identical `SPEC.md` and protected tests, fresh Codex CLI session, explicit `gpt-6-luna` / `medium`, `workspace-write` sandbox and network-disabled tool policy, approval `never`. It must not use ProjectCTL, Beads, project state, or any output from the successful `ctl` arm as context, and must not perform Git-history writes. Its JSONL usage data, wall seconds, code diff, fixed independent unittest and protected-file digests should be preserved under a separate `direct-attempt-1` evidence directory.

Do not conflate identical task/spec and model with a perfectly matched prompt or orchestration surface: the ProjectCTL SDK uses a structured task message and Codex CLI uses a noninteractive prompt. Record this deliberate interface difference. If the local CLI's actual model or reasoning selection cannot be established, mark comparison equivalence uncertain.
