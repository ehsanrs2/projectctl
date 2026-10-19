#!/usr/bin/env bash
# D1-R3: one explicitly operator-invoked, local-only, verified-candidate integration.
# No Codex/model call, no new verification, no retry, no direct-arm mutation.
if [[ "$0" != *d1_r3_integrate_manual.sh || $# -ne 2 || "$1" != "--integrate" || "$2" != "--ack-local-ff" ]]; then
  echo "Usage: bash experiments/dogfooding/d1_r3_integrate_manual.sh --integrate --ack-local-ff" >&2
  exit 2
fi
set -Eeuo pipefail
umask 077

RESEARCH="$HOME/project/My/projectctl-advisory-lab"
CTL="$HOME/.local/state/projectctl-dogfood-d1/fixtures/ctl"
DIRECT="$HOME/.local/state/projectctl-dogfood-d1/fixtures/direct"
VENV="$HOME/.local/share/projectctl-dogfood-d0/venv"
export PATH="$VENV/bin:$PATH"
export PROJECTCTL_HOME="$HOME/.local/state/projectctl-dogfood-d1/ctl-home"
export BD_ACTOR=d1-dogfood-owner BD_DISABLE_METRICS=1 DOLT_DISABLE_EVENT_FLUSH=1 DO_NOT_TRACK=1
export PYTHONDONTWRITEBYTECODE=1

RUN_ID="run-e467c1fa8f0f448b8497c9530c49b326"
BASE="7388896be4a7ba46770ae76c7cd5480f0cd9e27b"
CAND="2089c04c5fc679cfb4353a2cef2c2f25c83fa40d"
DIRECT_BASE="da9379c70571c9366f5adfccecdfab148c814fc2"
SPEC_SHA="aac3d5e847cd24849e92860553459bae9f7cbf70cbf00073eba140270160253d"
POLICY_SHA="ce2d1fa410a7ea3ba5eeb62d6e48610de44bcd84cadbc98f537b564918ed6e6d"
TEST_SHA="ba12648bfa7357c501925b5fa1dd4f9685efaf9f44e748285716dd8579aa5a0f"

[[ "$(git -C "$RESEARCH" branch --show-current)" == "research/advisory-skills-eval" ]]
[[ -z "$(git -C "$RESEARCH" status --porcelain)" ]]
[[ "$(git -C "$CTL" rev-parse HEAD)" == "$BASE" ]]
[[ "$(git -C "$DIRECT" rev-parse HEAD)" == "$DIRECT_BASE" ]]
[[ -z "$(git -C "$CTL" status --porcelain --untracked-files=all)" ]]
[[ -z "$(git -C "$DIRECT" status --porcelain --untracked-files=all)" ]]
[[ -z "$(git -C "$CTL" remote)" && -z "$(git -C "$DIRECT" remote)" ]]
for path in "$CTL/SPEC.md" "$DIRECT/SPEC.md"; do
  [[ "$(sha256sum "$path" | cut -d' ' -f1)" == "$SPEC_SHA" ]]
done
for path in "$CTL/POLICY.md" "$DIRECT/POLICY.md"; do
  [[ "$(sha256sum "$path" | cut -d' ' -f1)" == "$POLICY_SHA" ]]
done
for path in "$CTL/test_user_id.py" "$DIRECT/test_user_id.py"; do
  [[ "$(sha256sum "$path" | cut -d' ' -f1)" == "$TEST_SHA" ]]
done

OUT="$HOME/.local/state/projectctl-dogfood-d1/observations/ctl-attempt-4/integration"
if [[ -e "$OUT" || -L "$OUT" ]]; then
  echo "Integration evidence already exists; refusing second invocation: $OUT" >&2
  exit 3
fi
mkdir -m 700 -p "$OUT"
exec > >(tee "$OUT/console.log") 2>&1
trap 'rc=$?; echo "D1_R3_INTEGRATION_EXIT=$rc"; echo "EVIDENCE_DIR=$OUT"' EXIT

echo "=== 1. DURABLE RUN / EVIDENCE / EXACT TASK OWNERSHIP ==="
"$VENV/bin/projectctl" run show "$RUN_ID" --project "$CTL" --json > "$OUT/run-before.json"
bd -C "$CTL" show d1ctl-lh4 --json > "$OUT/task-before.json"
"$VENV/bin/python" - "$CTL" "$PROJECTCTL_HOME" "$RUN_ID" "$BASE" "$CAND" "$OUT" <<'PY'
import json, subprocess, sys
from pathlib import Path
from projectctl.application.claims import load_durable_claim
from projectctl.integrations.beads.claim import BeadsTaskClaimer
from projectctl.project.loader import load_project_config
from projectctl.storage.runs import RunStore

root, home, run_id, base, candidate, output = (
    Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3], sys.argv[4], sys.argv[5], Path(sys.argv[6])
)
cfg = load_project_config(root)
assert cfg.task_store.provider == "beads"
assert cfg.code_transport.mode == cfg.code_delivery.mode == "local"
assert cfg.orchestration.max_active_runs == 1
assert cfg.scope_governance.mode == "required"

shown = json.loads((output/"run-before.json").read_text())["run"]
store = RunStore(root)
record = store.get(run_id)
assert shown["run_id"] == record.run_id == run_id
assert shown["status"] == record.status.value == "ready_to_integrate"
assert shown["base_commit"] == record.base_commit == base
assert shown["candidate_commit"] == record.candidate_commit == candidate
assert shown["task_id"] == record.task_id == "d1ctl-lh4"
assert shown["terminal_reason"] is None and shown["lease_owner"] is None

run_dir = root/".projectctl"/"runs"/run_id
plan = json.loads((run_dir/"execution-plan.json").read_text())
verification = json.loads((run_dir/"verification-manifest.json").read_text())
evidence = json.loads((run_dir/"evidence-manifest.json").read_text())
assert plan["integration_target_ref"] == subprocess.check_output(
    ["git", "-C", str(root), "branch", "--show-current"], text=True
).strip()
assert plan["base_commit"] == base
assert plan["strategy"] == "direct"
assert plan["worker"]["actual_model"] == "gpt-6-luna"
assert plan["worker"]["reasoning"] == "medium"
assert verification["overall_pass"] is True and evidence["overall_pass"] is True
assert verification["policy_violations"] == []
assert verification["changed_paths"] == evidence["changed_paths"] == ["user_id.py"]
assert evidence["candidate_commit"] == candidate
assert len(verification["checks"]) == 4
assert all(check["status"] == "passed" for check in verification["checks"])
assert any(check["id"] == "fixed-unittest" and check["exit_code"] == 0
           and check["argv"] == ["python3", "-B", "-m", "unittest", "-v", "test_user_id.py"]
           for check in verification["checks"])

worktree = Path(record.worktree_path).resolve()
assert worktree.is_dir() and worktree.is_relative_to(home.resolve()/"worktrees")
def git(path, *args):
    return subprocess.check_output(["git", "-C", str(path), *args], text=True).strip()
assert git(root, "rev-parse", "HEAD") == base
assert git(root, "status", "--porcelain") == ""
assert git(root, "remote") == ""
assert git(worktree, "rev-parse", "HEAD") == candidate
assert git(worktree, "rev-parse", "HEAD^") == base
assert git(worktree, "status", "--porcelain") == ""
assert git(worktree, "diff", "--name-only", base, candidate, "--") == "user_id.py"
for name in ("SPEC.md", "POLICY.md", "test_user_id.py"):
    assert (worktree/name).read_bytes() == (root/name).read_bytes()

tasks = json.loads((output/"task-before.json").read_text())
assert len(tasks) == 1 and tasks[0]["id"] == "d1ctl-lh4"
assert tasks[0]["status"] == "in_progress"
_, claim = load_durable_claim(root, store=store, run_id=run_id)
assert claim.acquired and claim.provider == "beads"
assert tasks[0].get("assignee") == claim.actor, "Beads claimant changed; stop"
assert BeadsTaskClaimer(root).validate(claim), "Durable Beads claim no longer held"
(output/"worktree-path.txt").write_text(str(worktree)+"\n")
print("D1_INTEGRATION_PRECHECK_PASS; BEADS_CLAIM_VALIDATED")
PY

WT="$(cat "$OUT/worktree-path.txt")"
git -C "$WT" --no-pager diff --binary "$BASE" "$CAND" -- user_id.py > "$OUT/approved-candidate.patch"
cp "$CTL/.projectctl/runs/$RUN_ID/evidence-manifest.json" "$OUT/evidence-before.json"

echo "=== 2. PROJECTCTL LOCAL INTEGRATION (ONCE; NO RETRY) ==="
date -u +%FT%TZ
if ! "$VENV/bin/projectctl" run integrate "$RUN_ID" --project "$CTL" --json \
       > "$OUT/integrate.json" 2> "$OUT/integrate.stderr"; then
  cat "$OUT/integrate.stderr"
  echo "INTEGRATION_FAILED_OR_PARTIAL: inspect local Git and task; do NOT rerun blindly"
  "$VENV/bin/projectctl" run show "$RUN_ID" --project "$CTL" --json > "$OUT/run-after-failure.json" || true
  bd -C "$CTL" show d1ctl-lh4 --json > "$OUT/task-after-failure.json" || true
  git -C "$CTL" status --short || true
  git -C "$CTL" rev-parse HEAD || true
  exit 4
fi

echo "=== 3. POST-INTEGRATION RECONCILIATION ==="
"$VENV/bin/projectctl" run show "$RUN_ID" --project "$CTL" --json > "$OUT/run-after.json"
bd -C "$CTL" show d1ctl-lh4 --json > "$OUT/task-after.json"
"$VENV/bin/python" - "$OUT/integrate.json" "$OUT/run-after.json" "$OUT/task-after.json" "$BASE" "$CAND" <<'PY'
import json,sys
from pathlib import Path
data=json.loads(Path(sys.argv[1]).read_text())
after=json.loads(Path(sys.argv[2]).read_text())["run"]
tasks=json.loads(Path(sys.argv[3]).read_text())
base,candidate=sys.argv[4],sys.argv[5]
run, manifest = data["run"],data["integration"]
assert run["status"] == after["status"] == "passed"
assert run["candidate_commit"] == after["candidate_commit"] == candidate
assert manifest["target_before"] == base and manifest["target_after"] == candidate
assert manifest["candidate_commit"] == candidate and manifest["base_commit"] == base
assert manifest["delivery_mode"] == "local" and manifest["publication_required"] is False
assert manifest["task_completed"] is True
assert len(tasks)==1 and tasks[0]["id"]=="d1ctl-lh4"
assert tasks[0]["status"] in ("closed","done","completed")
print(json.dumps({
    "decision":"D1_R3_LOCAL_INTEGRATION_PASS",
    "run_id":run["run_id"], "status":run["status"],
    "candidate":candidate, "task_status":tasks[0]["status"],
    "task_completed":manifest["task_completed"],
    "claim_released":manifest["claim_released"],
    "worktree_cleaned":manifest["worktree_cleaned"],
    "remote_publication":manifest["publication_required"]
},indent=2))
PY

[[ "$(git -C "$CTL" rev-parse HEAD)" == "$CAND" ]]
[[ "$(git -C "$DIRECT" rev-parse HEAD)" == "$DIRECT_BASE" ]]
[[ -z "$(git -C "$CTL" status --porcelain --untracked-files=all)" ]]
[[ -z "$(git -C "$DIRECT" status --porcelain --untracked-files=all)" ]]
[[ -z "$(git -C "$CTL" remote)" && -z "$(git -C "$DIRECT" remote)" ]]
[[ "$(git -C "$CTL" diff --name-only "$BASE" "$CAND" --)" == "user_id.py" ]]
for path in SPEC.md POLICY.md test_user_id.py; do
  cmp -s "$CTL/$path" "$DIRECT/$path"
done
echo "D1_R3_INTEGRATED_LOCAL_ONLY; DIRECT_ARM_UNTOUCHED"
