#!/usr/bin/env bash
# D2 Attempt-3 OFFLINE qualification ONLY. One-time sandbox evidence.
set -Eeuo pipefail
umask 077

bad(){ printf 'D2_ATTEMPT3_OFFLINE_BLOCKED: %s\n' "$*" >&2; exit 2; }
[[ $# -eq 2 && "$1" == "--expected-head" && "$2" =~ ^[0-9a-f]{40}$ ]] ||
  bad "Exact reviewed 40-character HEAD required"

PIN="$2"
RESEARCH="$HOME/project/My/projectctl-advisory-lab"
ROOT="$HOME/.local/state/projectctl-dogfood-d2"
VENV="$HOME/.local/share/projectctl-dogfood-d0/venv"
ATT1="$ROOT/observations/ctl-prepare-attempt-1"
ATT2="$ROOT/observations/ctl-prepare-attempt-2"
ATT3="$ROOT/observations/ctl-prepare-attempt-3"
OFFLINE="$ROOT/observations/ctl-attempt3-offline-qualification"

[[ -d "$RESEARCH" && ! -L "$RESEARCH" ]] || bad "Research checkout missing"
[[ -x "$VENV/bin/python" ]] || bad "Pinned Python missing"
[[ ! -e "$OFFLINE" && ! -L "$OFFLINE" ]] || bad "Qualification identity already used"
[[ ! -e "$ATT3" && ! -L "$ATT3" ]] || bad "Attempt-3 live identity already exists"
for dir in "$ATT1" "$ATT2"; do
  [[ -d "$dir" && ! -L "$dir" ]] || bad "Historical attempt unavailable"
  for name in prepare-summary.json quota-before-prepare.json scheduler-before-prepare.json; do
    [[ -f "$dir/$name" && ! -L "$dir/$name" ]] || bad "Historical evidence missing/symlinked"
  done
done
[[ "$(git -C "$RESEARCH" branch --show-current)" == "research/advisory-skills-eval" ]] ||
  bad "Wrong research branch"
[[ "$(git -C "$RESEARCH" rev-parse HEAD)" == "$PIN" ]] || bad "Research HEAD drift"
[[ -z "$(git -C "$RESEARCH" status --porcelain=v1 --untracked-files=all)" ]] ||
  bad "Research checkout dirty"

export PROJECTCTL_HOME="$ROOT/ctl-home" BD_ACTOR=d2-dogfood-owner
export BD_DISABLE_METRICS=1 DOLT_DISABLE_EVENT_FLUSH=1 DO_NOT_TRACK=1
export PYTHONDONTWRITEBYTECODE=1
mkdir -m 700 "$OFFLINE"
stage="allocated"
decision="D2_ATTEMPT3_OFFLINE_BLOCKED"
finish(){
  local rc=$?
  trap - EXIT
  set +e
  for a in 1 2; do
    dir="$ROOT/observations/ctl-prepare-attempt-$a"
    if [[ -f "$OFFLINE/attempt$a-before.sha256" ]]; then
      (cd "$dir" && sha256sum -c "$OFFLINE/attempt$a-before.sha256") \
        > "$OFFLINE/attempt$a-integrity.log" 2>&1 ||
        { rc=2; decision="D2_ATTEMPT3_OFFLINE_BLOCKED"; }
    fi
  done
  [[ ! -e "$ATT3" && ! -L "$ATT3" ]] ||
    { rc=2; decision="D2_ATTEMPT3_OFFLINE_BLOCKED"; }
  [[ -z "$(git -C "$RESEARCH" status --porcelain=v1 --untracked-files=all 2>/dev/null)" ]] ||
    { rc=2; decision="D2_ATTEMPT3_OFFLINE_BLOCKED"; }
  [[ "$rc" -eq 0 ]] || decision="D2_ATTEMPT3_OFFLINE_BLOCKED"
  {
    printf 'decision=%s\n' "$decision"
    printf 'last_step=%s\n' "$stage"
    printf 'exit_code=%s\n' "$rc"
    printf 'research_commit=%s\n' "$PIN"
    printf 'attempt3_prepare_dispatched=false\n'
    printf 'paid_worker_started=false\n'
  } > "$OFFLINE/result.txt"
  (cd "$OFFLINE" && find . -maxdepth 1 -type f ! -name FILE_SHA256.txt -print0 |
    LC_ALL=C sort -z | xargs -0 -r sha256sum > FILE_SHA256.txt)
  exit "$rc"
}
trap finish EXIT

for a in 1 2; do
  dir="$ROOT/observations/ctl-prepare-attempt-$a"
  (cd "$dir" && sha256sum prepare-summary.json quota-before-prepare.json scheduler-before-prepare.json) \
    > "$OFFLINE/attempt$a-before.sha256"
done

cd "$RESEARCH"
stage="source_parse"
echo "[1/3] Validate Python syntax"
"$VENV/bin/python" -B - <<'PY'
import ast
from pathlib import Path
base = Path("experiments/dogfooding/d2")
for name in ("d2_ctl_attempt3_offline.py","test_d2_ctl_attempt3_offline.py"):
    ast.parse((base/name).read_text(encoding="utf-8"),filename=name)
print("D2_ATTEMPT3_SYNTAX_PASS")
PY

stage="synthetic_tests"
echo "[2/3] Synthetic no-provider admission matrix"
"$VENV/bin/python" -B -m unittest -v \
  experiments.dogfooding.d2.test_d2_ctl_attempt3_offline \
  > "$OFFLINE/tests.stdout.log" 2> "$OFFLINE/tests.stderr.log"
# Verify test count by the actual suite summary, not an assumed pass on import.
grep -Eq '^Ran 36 tests? in ' "$OFFLINE/tests.stderr.log" ||
  bad "Unexpected synthetic test count"
grep -Eq '^OK$' "$OFFLINE/tests.stderr.log" || bad "Unit-test failure"

stage="real_read_only_preview"
echo "[3/3] Read-only frozen D2 preview (no live quota)"
"$VENV/bin/python" -B -m experiments.dogfooding.d2.d2_ctl_attempt3_offline \
  --preview --expected-head "$PIN" > "$OFFLINE/preview.json" \
  2> "$OFFLINE/preview.stderr.log"

"$VENV/bin/python" -B - "$OFFLINE/preview.json" "$PIN" <<'PY'
import json, sys
from pathlib import Path
data=json.loads(Path(sys.argv[1]).read_text())
assert data["decision"] == "D2_ATTEMPT3_OFFLINE_PREVIEW_PASS__NO_LIVE_QUOTA_NO_PREPARE"
assert data["research_head"] == sys.argv[2]
assert data["ctl_run_count"] == 0 and data["beads_task"] == "open_unclaimed"
for key in ("attempt3_identity_created","live_quota_checked",
            "scheduler_queried","prepare_dispatched","worker_started"):
    assert data[key] is False, key
assert len(data["attempt2_source_sha256"]) == 3
print("D2_ATTEMPT3_OFFLINE_PREVIEW_CONTRACT_VALIDATED")
PY

stage="complete"
decision="D2_ATTEMPT3_OFFLINE_QUALIFIED__PREPARE_NOT_AUTHORIZED"
printf '%s\n' "$decision"
printf 'Evidence: %s\n' "$OFFLINE"
