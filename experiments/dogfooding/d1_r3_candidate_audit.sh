#!/usr/bin/env bash
# Read-only human adjudication packet for the verified D1-R3 candidate.
# Safe to run more than once; no worker, no new tests, no mutation, no integration.
if [[ "$0" != *d1_r3_candidate_audit.sh || $# -ne 1 || "$1" != "--read-only" ]]; then
  echo "Usage: bash experiments/dogfooding/d1_r3_candidate_audit.sh --read-only" >&2
  exit 2
fi
set -Eeuo pipefail
RESEARCH="$HOME/project/My/projectctl-advisory-lab"
CTL="$HOME/.local/state/projectctl-dogfood-d1/fixtures/ctl"
DIRECT="$HOME/.local/state/projectctl-dogfood-d1/fixtures/direct"
VENV="$HOME/.local/share/projectctl-dogfood-d0/venv"
export PROJECTCTL_HOME="$HOME/.local/state/projectctl-dogfood-d1/ctl-home"
export BD_ACTOR=d1-dogfood-owner BD_DISABLE_METRICS=1 DOLT_DISABLE_EVENT_FLUSH=1 DO_NOT_TRACK=1
RUN_ID="run-e467c1fa8f0f448b8497c9530c49b326"
BASE="7388896be4a7ba46770ae76c7cd5480f0cd9e27b"
CAND="2089c04c5fc679cfb4353a2cef2c2f25c83fa40d"
DIRECT_BASE="da9379c70571c9366f5adfccecdfab148c814fc2"
SPEC_SHA="aac3d5e847cd24849e92860553459bae9f7cbf70cbf00073eba140270160253d"
RUN_DIR="$CTL/.projectctl/runs/$RUN_ID"

[[ "$(git -C "$RESEARCH" branch --show-current)" == "research/advisory-skills-eval" ]]
[[ "$(git -C "$CTL" rev-parse HEAD)" == "$BASE" ]]
[[ "$(git -C "$DIRECT" rev-parse HEAD)" == "$DIRECT_BASE" ]]
[[ -z "$(git -C "$CTL" status --porcelain --untracked-files=all)" ]]
[[ -z "$(git -C "$DIRECT" status --porcelain --untracked-files=all)" ]]
[[ -z "$(git -C "$CTL" remote)" && -z "$(git -C "$DIRECT" remote)" ]]
[[ "$(sha256sum "$CTL/SPEC.md" | cut -d' ' -f1)" == "$SPEC_SHA" ]]
[[ "$(sha256sum "$DIRECT/SPEC.md" | cut -d' ' -f1)" == "$SPEC_SHA" ]]

echo "=== 1. VERIFIED RUN STATUS ==="
"$VENV/bin/projectctl" run show "$RUN_ID" --project "$CTL" --json |
"$VENV/bin/python" -c '
import json,sys
d=json.load(sys.stdin)
r=d["run"]
assert r["run_id"]=="run-e467c1fa8f0f448b8497c9530c49b326"
assert r["status"]=="ready_to_integrate"
assert r["base_commit"]=="7388896be4a7ba46770ae76c7cd5480f0cd9e27b"
assert r["candidate_commit"]=="2089c04c5fc679cfb4353a2cef2c2f25c83fa40d"
assert r["terminal_reason"] is None and r["lease_owner"] is None
print(json.dumps({"run_id":r["run_id"],"status":r["status"],"candidate_commit":r["candidate_commit"],"run_started_at":r["started_at"],"run_completed_at":r["completed_at"],"event_types":[e.get("event_type",e.get("type")) for e in d["events"]]},indent=2))
'

WT="$("$VENV/bin/python" - "$RUN_DIR" "$PROJECTCTL_HOME" "$BASE" "$CAND" <<'PY'
import json,sys
from pathlib import Path
run_dir,home,base,candidate=Path(sys.argv[1]),Path(sys.argv[2]),sys.argv[3],sys.argv[4]
p=json.loads((run_dir/"execution-plan.json").read_text())
assert p["base_commit"]==base and p["task_id"]=="d1ctl-lh4"
assert p["worker"]["actual_model"]=="gpt-6-luna"
assert p["worker"]["reasoning"]=="medium"
v=json.loads((run_dir/"verification-manifest.json").read_text())
e=json.loads((run_dir/"evidence-manifest.json").read_text())
assert v["overall_pass"] is True and e["overall_pass"] is True
assert v["changed_paths"]==e["changed_paths"]==["user_id.py"]
assert e["candidate_commit"]==candidate
print((home/"worktrees"/"2de16938-f06b-4d25-8ea3-52a097c7d98c"/"run-e467c1fa8f0f448b8497c9530c49b326").resolve())
PY
)"
[[ -d "$WT" ]]
[[ "$(git -C "$WT" rev-parse HEAD)" == "$CAND" ]]
[[ "$(git -C "$WT" rev-parse HEAD^)" == "$BASE" ]]
[[ -z "$(git -C "$WT" status --porcelain --untracked-files=all)" ]]
[[ "$(git -C "$WT" diff --name-only "$BASE" "$CAND" --)" == "user_id.py" ]]
git -C "$WT" diff --check "$BASE" "$CAND"

for path in SPEC.md POLICY.md test_user_id.py; do
  cmp -s "$WT/$path" "$DIRECT/$path"
  cmp -s "$CTL/$path" "$DIRECT/$path"
done

echo "=== 2. PROTECTED-FILE HASHES (CTL / DIRECT / CANDIDATE) ==="
for path in SPEC.md POLICY.md test_user_id.py; do
  echo "$path"
  sha256sum "$CTL/$path" "$DIRECT/$path" "$WT/$path"
done

echo "=== 3. SOURCE USER_ID.PY ==="
cat "$WT/user_id.py"
echo
echo "=== 4. FULL CANDIDATE DIFF ==="
git -C "$WT" --no-pager diff --binary --no-ext-diff "$BASE" "$CAND" -- user_id.py

echo "=== 5. VERIFICATION MANIFEST (SUMMARY) ==="
"$VENV/bin/python" - "$RUN_DIR" <<'PY'
import json,sys
from pathlib import Path
root=Path(sys.argv[1])
v=json.loads((root/"verification-manifest.json").read_text())
e=json.loads((root/"evidence-manifest.json").read_text())
print(json.dumps({
"overall_pass":v["overall_pass"],
"changed_paths":v["changed_paths"],
"policy_violations":v["policy_violations"],
"checks":[{"id":c["id"],"status":c["status"],"exit_code":c.get("exit_code"),"argv":c["argv"],"duration_ms":c["duration_ms"]} for c in v["checks"]],
"evidence_candidate":e["candidate_commit"],
"evidence_diff_digest":e["diff_digest"]
},indent=2))
PY

echo "=== 6. FROZEN UNITTEST LOG ==="
if [[ -f "$RUN_DIR/verification/fixed-unittest.stderr.log" ]]; then
  cat "$RUN_DIR/verification/fixed-unittest.stderr.log"
else
  echo "NO_STDERR_LOG_FILE"
fi

echo "=== 7. TARGET UNCHANGED / DIRECT UNTOUCHED ==="
echo "ctl=$(git -C "$CTL" rev-parse HEAD)"
echo "direct=$(git -C "$DIRECT" rev-parse HEAD)"
echo "candidate=$(git -C "$WT" rev-parse HEAD)"
echo "D1_R3_AUDIT_READ_ONLY_PASS__NO_INTEGRATION"
