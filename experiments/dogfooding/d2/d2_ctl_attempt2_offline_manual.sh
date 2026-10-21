#!/usr/bin/env bash
# D2 CTL Attempt 2: operator-run OFFLINE qualification only.
# No quota/next provider probe, Codex, Claim, Prepare, Worker, Retry, git fetch or pull.
# Read-only Git/Beads queries from readiness may update local operational caches.
set -Eeuo pipefail
umask 077

blocked() { printf 'D2_ATTEMPT2_OFFLINE_BLOCKED: %s\n' "$*" >&2; exit 2; }
[[ $# -eq 2 && "$1" == "--expected-head" && "$2" =~ ^[0-9a-f]{40}$ ]] ||
  blocked 'Pass --expected-head with the exact reviewed 40-character Git commit SHA'
PIN="$2"
RESEARCH="$HOME/project/My/projectctl-advisory-lab"
ROOT="$HOME/.local/state/projectctl-dogfood-d2"
VENV="$HOME/.local/share/projectctl-dogfood-d0/venv"
ATTEMPT1="$ROOT/observations/ctl-prepare-attempt-1"
ATTEMPT2="$ROOT/observations/ctl-prepare-attempt-2"
OFFLINE="$ROOT/observations/ctl-attempt2-offline-qualification"

# All checks below run before creating the single-use evidence identity.
[[ -d "$RESEARCH" && ! -L "$RESEARCH" ]] || blocked 'Research checkout unavailable or symlinked'
git -C "$RESEARCH" rev-parse --is-inside-work-tree >/dev/null 2>&1 ||
  blocked 'Research location is not a Git checkout'
[[ -x "$VENV/bin/python" ]] || blocked 'Pinned isolated D0 Python not installed'
[[ -d "$ATTEMPT1" && ! -L "$ATTEMPT1" ]] || blocked 'Historical Attempt-1 directory missing or symlinked'
for file in prepare-summary.json quota-before-prepare.json scheduler-before-prepare.json; do
  [[ -f "$ATTEMPT1/$file" && ! -L "$ATTEMPT1/$file" ]] ||
    blocked "Historical evidence missing/symlinked: $file"
done
[[ ! -e "$ATTEMPT2" && ! -L "$ATTEMPT2" ]] ||
  blocked 'Prepare Attempt-2 evidence identity is already occupied'
[[ ! -e "$OFFLINE" && ! -L "$OFFLINE" ]] ||
  blocked 'Offline qualification evidence identity already exists; no reuse'
[[ "$(git -C "$RESEARCH" branch --show-current)" == "research/advisory-skills-eval" ]] ||
  blocked 'Unexpected research branch'
[[ "$(git -C "$RESEARCH" rev-parse HEAD)" == "$PIN" ]] ||
  blocked 'Research HEAD differs from owner-reviewed SHA; sync separately'
[[ -z "$(git -C "$RESEARCH" status --porcelain=v1 --untracked-files=all)" ]] ||
  blocked 'Research checkout is dirty'

export PATH="$VENV/bin:$PATH"
export PROJECTCTL_HOME="$ROOT/ctl-home"
export BD_ACTOR=d2-dogfood-owner
export BD_DISABLE_METRICS=1
export DOLT_DISABLE_EVENT_FLUSH=1
export DO_NOT_TRACK=1
export PYTHONDONTWRITEBYTECODE=1

mkdir -m 700 "$OFFLINE" || blocked 'Cannot allocate fresh offline evidence identity'
decision="D2_ATTEMPT2_OFFLINE_BLOCKED"
step="begin"
finish() {
  local exit_code=$?
  trap - EXIT
  set +e
  if [[ -f "$OFFLINE/attempt1-input-sha256.txt" ]]; then
    (cd "$ATTEMPT1" && sha256sum -c "$OFFLINE/attempt1-input-sha256.txt") \
      > "$OFFLINE/attempt1-integrity.log" 2>&1
    if [[ $? -ne 0 ]]; then exit_code=2; decision="D2_ATTEMPT2_OFFLINE_BLOCKED"; fi
  fi
  if [[ -e "$ATTEMPT2" || -L "$ATTEMPT2" ]]; then
    exit_code=2
    decision="D2_ATTEMPT2_OFFLINE_BLOCKED"
  fi
  if [[ -n "$(git -C "$RESEARCH" status --porcelain=v1 --untracked-files=all 2>/dev/null)" ]]; then
    exit_code=2
    decision="D2_ATTEMPT2_OFFLINE_BLOCKED"
  fi
  if [[ "$exit_code" -ne 0 ]]; then decision="D2_ATTEMPT2_OFFLINE_BLOCKED"; fi
  {
    printf 'decision=%s\n' "$decision"
    printf 'last_step=%s\n' "$step"
    printf 'exit_code=%s\n' "$exit_code"
    printf 'research_commit=%s\n' "$PIN"
    printf 'attempt2_prepare_dispatched=false\n'
    printf 'paid_worker_started=false\n'
  } > "$OFFLINE/result.txt"
  (cd "$OFFLINE" &&
    find . -maxdepth 1 -type f ! -name FILE_SHA256.txt -print0 |
    LC_ALL=C sort -z | xargs -0 -r sha256sum > FILE_SHA256.txt)
  exit "$exit_code"
}
trap finish EXIT

(cd "$ATTEMPT1" &&
  sha256sum prepare-summary.json quota-before-prepare.json scheduler-before-prepare.json) \
  > "$OFFLINE/attempt1-input-sha256.txt"

cd "$RESEARCH"
step="unit_tests"
printf '[1/4] Run 23 synthetic tests (no provider calls)\n'
"$VENV/bin/python" -B -m unittest -v \
  experiments.dogfooding.d2.test_d2_ctl_attempt2_offline \
  > "$OFFLINE/tests.stdout.log" 2> "$OFFLINE/tests.stderr.log"
grep -Eq '^Ran 23 tests? in ' "$OFFLINE/tests.stderr.log" ||
  blocked 'Unexpected offline unit-test count'
grep -Eq '^OK$' "$OFFLINE/tests.stderr.log" ||
  blocked 'Offline unit tests did not finish successfully'

step="historical_replay"
printf '[2/4] Replay only retained Attempt-1 evidence\n'
"$VENV/bin/python" -B -m experiments.dogfooding.d2.d2_ctl_attempt2_offline \
  --replay-attempt1 > "$OFFLINE/replay.json" 2> "$OFFLINE/replay.stderr.log"

step="attempt2_preview"
printf '[3/4] Preview isolated frozen CTL readiness\n'
"$VENV/bin/python" -B -m experiments.dogfooding.d2.d2_ctl_attempt2_offline \
  --preview-attempt2 > "$OFFLINE/preview.json" 2> "$OFFLINE/preview.stderr.log"

step="contract_validation"
printf '[4/4] Check JSON contract and input hashes\n'
"$VENV/bin/python" -B - "$OFFLINE" <<'PY'
import json
from pathlib import Path
import sys

root = Path(sys.argv[1])
replay = json.loads((root / "replay.json").read_text(encoding="utf-8"))
preview = json.loads((root / "preview.json").read_text(encoding="utf-8"))
manifest = {}
for line in (root / "attempt1-input-sha256.txt").read_text().splitlines():
    hexdigest, filename = line.split("  ", 1)
    manifest[filename] = hexdigest

assert replay["decision"] == "D2_ATTEMPT1_FALLBACK_REPLAY_PASS__NO_PROVIDER_CALLS"
assert replay["source_sha256"] == manifest
assert replay["scheduler_equals_canonical_unknown"] is True
assert replay["scheduler_equals_official"] is False
assert replay["provider_exception_class"] == "NOT_RECORDED"
assert replay["prepare_dispatched"] is False
assert replay["paid_worker_started"] is False
assert preview["decision"] == "D2_ATTEMPT2_OFFLINE_PREVIEW_PASS__NO_CLAIM_NO_INFERENCE"
assert preview["ctl_runs"] == 0
assert preview["beads_task"] == "open_unclaimed"
assert preview["attempt2_evidence_directory_created"] is False
assert preview["live_quota_checked"] is False
assert preview["run_prepare_called"] is False
assert preview["worker_started"] is False
print("D2_ATTEMPT2_OFFLINE_CONTRACT_VALIDATED")
PY

step="complete"
decision="D2_ATTEMPT2_OFFLINE_QUALIFIED__PREPARE_NOT_AUTHORIZED"
printf '%s\n' "$decision"
printf 'Evidence: %s\n' "$OFFLINE"
