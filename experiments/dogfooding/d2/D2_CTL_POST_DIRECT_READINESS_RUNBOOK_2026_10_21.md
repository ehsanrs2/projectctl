# D2 CTL-arm read-only readiness (after accepted Direct source review)

**Current scientific state:** Direct CLI first paid turn completed and passed its 26 frozen tests, three-file scope and independent evidence reconciliation. Static semantic assessment is **PASS WITH EDGE RISK**; owner's eventual final adjudication is separate. ProjectCTL arm has not performed `run prepare` or `run start`.

This gate is **not** permission to execute ProjectCTL. It intentionally prevents accidental reuse of the earlier D2 pre-inference preflight, which expected the Direct worktree to be clean. The Direct worktree now holds a valid, deliberately uncommitted solution; do not reset it, re-run Direct, or copy its content into CTL.

The new `d2_ctl_readiness.py` is read-only of the fixture/application content (Git/Beads reads may update operational caches). It re-validates the completed Direct audit and frozen source SHA-256, pinned D2 policy commit, canonical sole ready/unclaimed Beads task, exact 3-file ProjectCTL write scope, local-only code delivery, model pin `gpt-6-luna`/medium, 26 fixed acceptance tests, verification profile digest, zero CTL runs and an unchanged clean CTL target. It does not run an LLM, refresh Codex rate limits, call `run prepare`, create a worktree, claim a task, verify, integrate or publish.

Twelve new pure offline regression tests are defined for the provenance checks, source/Scope drift, task claimed/description drift and CLI read-only boundary. They are **operator execution pending**. If any test or the actual readiness gate fails, stop and record the exact mismatch; do not reset the Direct fixture or force ProjectCTL forward.

## One operator-controlled observation (NO PAID TURN, NO CLAIM)

```bash
bash -c '
set -euo pipefail
cd /home/ai/project/My/projectctl-advisory-lab
git pull --ff-only origin research/advisory-skills-eval
VENV="$HOME/.local/share/projectctl-dogfood-d0/venv"
export PATH="$VENV/bin:$PATH"
export PROJECTCTL_HOME="$HOME/.local/state/projectctl-dogfood-d2/ctl-home"
export BD_ACTOR=d2-dogfood-owner
export BD_DISABLE_METRICS=1
export DOLT_DISABLE_EVENT_FLUSH=1
export DO_NOT_TRACK=1
export PYTHONDONTWRITEBYTECODE=1
"$VENV/bin/python" -B -m unittest -v \
  experiments.dogfooding.d2.test_d2_ctl_readiness
"$VENV/bin/python" -B -m \
  experiments.dogfooding.d2.d2_ctl_readiness --read-only
'
echo "D2_CTL_READINESS_EXIT=$?"
```

Expected: `Ran 12 tests`, `OK`, and `D2_CTL_READ_ONLY_PREPARE_GATE_PASS__CLAIM_NOT_AUTHORIZED`. Do not treat an expected marker as observed success until the user reports the actual terminal output.

## Next, separately owner-authorized stages

**Stage CTL-PREPARE** is a control-plane mutation, not a paid model call: `projectctl run prepare --strategy direct --project CTL --json` acquires the canonical Beads claim, creates a run and separate worktree, writes durable manifests and potentially changes operational task metadata. Require explicit owner permission, fresh official quota and scheduler selection, frozen exact branches/prompt and clean snapshots before this action. An unsuccessful prepare is evidence and **not** grounds for an in-pair retry.

**Stage CTL-START** invokes paid Codex SDK with a separate explicit approval; verify the prepared plan's `actual_model=gpt-6-luna`, `reasoning=medium`, `sandbox=workspace_write`, `network=disabled`, `approval=deny_all`, no privileged Git operations, same frozen scope and current official quota before starting. Record monotonic start wall, start/finish timestamps and actual SDK usage if available. Do **not** automatically verify or integrate in the start stage.

**Stage CTL-VERIFY** is independent ProjectCTL verification and candidate-commit creation; require a separate human review before the **Stage CTL-INTEGRATE** local-only completion and Beads closure. Preserve failure/run/claim/verification evidence. The Direct solution is never used as input to CTL; keep its original modified worktree and attempt evidence intact for independent comparison.

**Experimental caveats:** This is one paired task, not statistical evidence of ProjectCTL benefit. The SDK bundled Codex runtime `0.160.0` differs from independent direct CLI `0.163.0`. If SDK usage data is unavailable, mark unknown rather than fabricate comparable tokens. Do not apply any hotfix to either trial arm or runner mid-pair and then count a retry as the same trial.

**State:** `D2_CTL_READ_ONLY_READINESS_OPERATOR_PENDING / PREPARE_NOT_AUTHORIZED / START_NOT_AUTHORIZED / DIRECT_IMMUTABLE`.
