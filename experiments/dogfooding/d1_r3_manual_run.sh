#!/usr/bin/env bash
# D1-R3: manual, explicitly authorized fourth ProjectCTL attempt.
# Offline checks first, one paid start at most, no retry/verification/integration.
if [[ "$0" != *d1_r3_manual_run.sh || $# -ne 2 || "$1" != "--execute" || "$2" != "--ack-paid" ]]; then
  echo "Usage: bash experiments/dogfooding/d1_r3_manual_run.sh --execute --ack-paid" >&2
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

SETUP="7388896be4a7ba46770ae76c7cd5480f0cd9e27b"
DIRECT_BASE="da9379c70571c9366f5adfccecdfab148c814fc2"
SPEC_SHA="aac3d5e847cd24849e92860553459bae9f7cbf70cbf00073eba140270160253d"
FAILED_0="run-88361fe2431e4e299a0f4b9c506c50fa"
DECISION_1="run-10e606ca532c403487131ea092db232c"
FAILED_2="run-b5785a14e0ab4961a970c43b0dc2b303"

[[ "$(git -C "$RESEARCH" branch --show-current)" == "research/advisory-skills-eval" ]]
[[ -z "$(git -C "$RESEARCH" status --porcelain)" ]]
[[ "$(git -C "$CTL" rev-parse HEAD)" == "$SETUP" ]]
[[ "$(git -C "$DIRECT" rev-parse HEAD)" == "$DIRECT_BASE" ]]
[[ -z "$(git -C "$CTL" status --porcelain --untracked-files=all)" ]]
[[ -z "$(git -C "$DIRECT" status --porcelain --untracked-files=all)" ]]
[[ -z "$(git -C "$CTL" remote)" && -z "$(git -C "$DIRECT" remote)" ]]
[[ "$(sha256sum "$CTL/SPEC.md" | cut -d' ' -f1)" == "$SPEC_SHA" ]]
[[ "$(sha256sum "$DIRECT/SPEC.md" | cut -d' ' -f1)" == "$SPEC_SHA" ]]
[[ -f "$PROJECTCTL_HOME/state.sqlite" ]]
[[ -x "$VENV/bin/projectctl" && -x "$VENV/bin/python" ]]

OUT="$HOME/.local/state/projectctl-dogfood-d1/observations/ctl-attempt-4"
if [[ -e "$OUT" || -L "$OUT" ]]; then
  echo "Refusing duplicate attempt: $OUT already exists." >&2
  exit 3
fi
mkdir -m 700 -p "$OUT"
exec > >(tee "$OUT/console.log") 2>&1
trap 'code=$?; echo "D1_R3_EXIT=$code"; echo "EVIDENCE_DIR=$OUT"' EXIT

cd "$RESEARCH"
echo "=== 1. OFFLINE REGRESSION TESTS: 24 EXPECTED ==="
"$VENV/bin/python" -m unittest -v \
  experiments/dogfooding/test_d1_codex_strict_output_schema.py \
  experiments/dogfooding/test_d1_capability_version_identity.py \
  experiments/dogfooding/test_d1_quota_resource_consistency.py

echo "=== 2. RESEARCH RUNTIME / LOCAL STRICT SCHEMA ==="
"$VENV/bin/python" - "$RESEARCH" "$CTL" <<'PY'
import sys
from pathlib import Path
import projectctl.application.execution as execution
import projectctl.workers.codex.adapter as adapter
from projectctl.project.loader import load_project_config
from projectctl.core.enums import ModelProfile

research, root = Path(sys.argv[1]), Path(sys.argv[2])
assert Path(execution.__file__).resolve() == (research/"projectctl/application/execution.py").resolve()
assert Path(adapter.__file__).resolve() == (research/"projectctl/workers/codex/adapter.py").resolve()
cfg=load_project_config(root)
assert cfg.task_store.provider == "beads"
assert cfg.scope_governance.mode == "required"
assert cfg.code_transport.mode == "local" and cfg.code_delivery.mode == "local"
assert cfg.orchestration.max_active_runs == 1
assert cfg.model_profiles[ModelProfile.BALANCED].model == "gpt-6-luna"
assert cfg.model_profiles[ModelProfile.BALANCED].reasoning.value == "medium"
schema=adapter._strict_worker_output_schema()
assert schema["additionalProperties"] is False
assert set(schema["properties"]) == set(schema["required"])
assert "blockers" in schema["required"]
assert set(schema["$defs"]["PermissionRequest"]["properties"]) == set(schema["$defs"]["PermissionRequest"]["required"])
print("D1_STRICT_SCHEMA_AND_RESEARCH_RUNTIME_PASS")
PY

echo "=== 3. THREE PREVIOUS RUNS AND BEADS STATE ==="
"$VENV/bin/projectctl" runs --project "$CTL" --json > "$OUT/runs-before.json"
bd -C "$CTL" show d1ctl-lh4 --json > "$OUT/task-before.json"
bd -C "$CTL" ready --json > "$OUT/ready-before.json"
"$VENV/bin/python" - "$OUT/runs-before.json" "$OUT/task-before.json" "$OUT/ready-before.json" "$FAILED_0" "$DECISION_1" "$FAILED_2" <<'PY'
import json, sys
from pathlib import Path
runs=json.loads(Path(sys.argv[1]).read_text())
task=json.loads(Path(sys.argv[2]).read_text())
ready=json.loads(Path(sys.argv[3]).read_text())
by_id={r["run_id"]:r for r in runs}
assert len(runs)==3 and set(by_id)==set(sys.argv[4:7]), "Unexpected run inventory: stop"
r0,r1,r2=(by_id[x] for x in sys.argv[4:7])
assert r0["status"]=="failed" and r0["terminal_reason"]=="quota_exhausted"
assert r1["status"]=="needs_decision" and r1["terminal_reason"]=="capability_changed"
assert r2["status"]=="failed" and r2["terminal_reason"]=="worker_error"
assert all(r["lease_owner"] is None for r in runs)
assert r2["candidate_commit"] is None
assert len(task)==1 and task[0]["id"]=="d1ctl-lh4"
assert task[0]["status"]=="open" and not task[0].get("assignee")
assert [x["id"] for x in ready]==["d1ctl-lh4"]
print("THREE_PREVIOUS_D1_RUNS_PRESERVED; TASK_READY_AND_UNCLAIMED")
PY

echo "=== 4. FRESH OFFICIAL QUOTA AND SCHEDULER ==="
"$VENV/bin/projectctl" quota --project "$CTL" --json > "$OUT/quota-before.json"
"$VENV/bin/projectctl" next --project "$CTL" --json > "$OUT/next-before.json"
"$VENV/bin/python" - "$OUT/quota-before.json" "$OUT/next-before.json" <<'PY'
import json, sys
from pathlib import Path
q=json.loads(Path(sys.argv[1]).read_text())
decision=json.loads(Path(sys.argv[2]).read_text())
assert q["snapshot"]["provider"]=="codex_app_server"
assert q["snapshot"]["selected_limit_id"]=="codex"
assert q["snapshot"]["ordinary_usage_allowed"] is True and q["stale"] is False
assert q["effective"]["five_hour"] is not None and q["effective"]["five_hour"]>=0.18
assert q["effective"]["weekly"] is not None and q["effective"]["weekly"]>=0.08
assert decision["selected_task_id"]=="d1ctl-lh4" and len(decision["candidates"])==1
candidate=decision["candidates"][0]
assert candidate["eligibility"]["eligible"] is True and not candidate["eligibility"]["reasons"]
assert candidate["model"]["profile"]=="balanced" and candidate["model"]["reasoning"]=="medium"
print("D1_FRESH_QUOTA_AND_SCHEDULER_PASS")
PY

echo "=== 5. PREPARE (ONE NEW CLAIM) ==="
date -u +%FT%TZ
if ! "$VENV/bin/projectctl" run prepare --strategy direct --project "$CTL" --json \
     > "$OUT/prepare.json" 2> "$OUT/prepare.stderr"; then
  cat "$OUT/prepare.stderr"
  echo "PREPARE_FAILED: no retry"
  exit 4
fi

RUN_ID=$("$VENV/bin/python" - "$OUT/prepare.json" "$PROJECTCTL_HOME" "$SETUP" "$OUT" <<'PY'
import json,sys
from pathlib import Path
d=json.loads(Path(sys.argv[1]).read_text())
p,r,w=d["plan"],d["run"],d["worktree"]
rid=r["run_id"]
(Path(sys.argv[4])/"run-id.txt").write_text(rid+"\n")
assert rid.startswith("run-") and r["status"]=="claimed"
assert p["task_id"]==r["task_id"]=="d1ctl-lh4"
assert p["strategy"]=="direct" and p["base_commit"]==sys.argv[3]
assert p["worker"]["provider"]=="codex" and p["worker"]["actual_model"]=="gpt-6-luna"
assert p["worker"]["reasoning"]=="medium"
pol=p["execution_policy"]
assert pol["sandbox"]=="workspace_write" and pol["network"]=="disabled"
assert pol["approval"]=="deny_all" and not any(pol["git"].values())
assert w["id"]==rid and w["base_commit"]==p["base_commit"]
assert Path(w["path"]).resolve().is_relative_to(Path(sys.argv[2]).resolve()/"worktrees")
assert Path(w["path"]).is_dir()
print(rid)
PY
)
echo "PREPARE_PASS=$RUN_ID"

echo "=== 6. START (ONE PAID WORKER TURN MAXIMUM; NO RETRY) ==="
date -u +%FT%TZ
SECONDS=0
if ! "$VENV/bin/projectctl" run start "$RUN_ID" --project "$CTL" --json \
    > "$OUT/start.json" 2> "$OUT/start.stderr"; then
  cat "$OUT/start.stderr"
  echo "START_FAILED_OR_DEFERRED: no retry"
  echo "RUN_ID=$RUN_ID"
  exit 5
fi
echo "START_COMMAND_WALL_SECONDS=$SECONDS"
date -u +%FT%TZ
"$VENV/bin/python" - "$OUT/start.json" <<'PY'
import json,sys
from pathlib import Path
d=json.loads(Path(sys.argv[1]).read_text())
r=d["run"]; w=d.get("worker_result")
print(json.dumps({
 "run_id":r["run_id"],
 "run_status":r["status"],
 "worker_status":w.get("status") if w else None,
 "checkpointed":d.get("checkpoint") is not None
}, indent=2))
PY
echo "D1_R3_START_FINISHED; VERIFY_AND_INTEGRATE_NOT_RUN"
