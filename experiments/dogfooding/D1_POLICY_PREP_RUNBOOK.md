# D1 disposable fixture — human policy setup runbook

**Stage:** ProjectCTL \`init\` completed on the disposable \`ctl\` fixture. Policy preparation only; no \`run prepare/start\`, model calls or M6.0 changes. Operator's Beads task: \`d1ctl-lh4\`. Repo HEAD after Beads ignore setup: \`1b38e7526c00009fd44a910e438d74969f00b3c9\`. Source baseline: \`da9379c70571c9366f5adfccecdfab148c814fc2\`.

The helper \`experiments/dogfooding/d1_prepare_policy.py\` is guarded to this exact disposable fixture suffix, original task/source identities, SPEC hash, Git HEAD, clean task authority, expected set of untracked ProjectCTL bootstrap files, absent policy catalog files, and a freshly initialized matching \`PROJECTCTL_HOME\`. It refuses replacement of existing catalogs and has no task or model calls. Default invocation **only previews** hashes; \`--apply --ack-disposable\` creates policies and updates local fixture config.

## Operator commands

\`\`\`bash
cd /home/ai/project/My/projectctl-advisory-lab
git pull --ff-only origin research/advisory-skills-eval

CTL="$HOME/.local/state/projectctl-dogfood-d1/fixtures/ctl"
D0_VENV="$HOME/.local/share/projectctl-dogfood-d0/venv"
export PATH="$D0_VENV/bin:$PATH"
export PROJECTCTL_HOME="$HOME/.local/state/projectctl-dogfood-d1/ctl-home"
export BD_ACTOR=d1-dogfood-owner BD_DISABLE_METRICS=1 DOLT_DISABLE_EVENT_FLUSH=1 DO_NOT_TRACK=1

"$D0_VENV/bin/python" -m compileall -q experiments/dogfooding/d1_prepare_policy.py
"$D0_VENV/bin/python" experiments/dogfooding/d1_prepare_policy.py --repo "$CTL"
"$D0_VENV/bin/python" experiments/dogfooding/d1_prepare_policy.py --repo "$CTL" --apply --ack-disposable

# Inspect authoritative profile, new policy files and ignored runtime state.
"$D0_VENV/bin/projectctl" verification profile --project "$CTL" --json
git -C "$CTL" status --short --untracked-files=all
git -C "$CTL" diff -- .gitignore
cat "$CTL/projectctl.scope.yaml"
cat "$CTL/projectctl.verification.yaml"

# Review before running this explicit fixture-local commit.
git -C "$CTL" add -- .gitignore docs/PROJECT_STATE.yaml projectctl.scope.yaml projectctl.verification.yaml
git -C "$CTL" diff --cached --check
git -C "$CTL" diff --cached --name-only
# Require EXACTLY those four filenames; then:
git -C "$CTL" commit -m "chore(d1): pin test policy, model routing and state"
git -C "$CTL" status --short --untracked-files=all
\`\`\`

The helper sets \`scope_governance.mode=required\` and all fixture model profiles to the already-probed \`gpt-6-luna\`/\`medium\`. The scope catalog gives exactly one task \`d1ctl-lh4\` read access to the tracked SPEC/stub/fixed test/policy and write access only to \`user_id.py\`. The human verification catalog specifies \`python3 -B -m unittest -v test_user_id.py\`, with fixed inputs \`SPEC.md\`, \`POLICY.md\`, \`test_user_id.py\` and \`.gitignore\` additionally protected in diff policy. Config and SQLite inside \`.projectctl/\` are excluded from Git history; human-managed policy and generated Project State **are** committed in the disposable fixture only.

The standalone \`direct\` fixture must remain at its original commit and unchanged; these are control-plane setup-only commits in the \`ctl\` arm, not new application implementation. Preserve both original source-base identity and final setup HEAD for paired evaluation.

## Pre-worker gate after policy commit

Review \`bd -C "$CTL" ready --json\` still returns **one** \`d1ctl-lh4\` task; \`git status --short\` must be empty and Git remote list empty. Independently inspect \`projectctl quota --project "$CTL" --json\` and \`projectctl next --project "$CTL" --json\` (may write operational events under ignored \`.projectctl\`). If no selected eligible task or quota is stale/unknown/insufficient, stop and review the actual provider snapshot; **never forge quota values**. The ProjectCTL Beads adapter still lacks provider heartbeat and atomic release; restrict the first paid D1 to one actor/no concurrent reclaimer, checking claim and elapsed time. Do not invoke \`projectctl run prepare\` or a model automatically as part of this runbook.

**D1 status:** \`DISPOSABLE_POLICY_PREP_PENDING\`; no inference yet. The helper is newly written and must first pass the operator's compile and preview checks. Report any unexpected state instead of bypassing guards.
