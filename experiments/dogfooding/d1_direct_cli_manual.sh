#!/usr/bin/env bash
# D1 direct control arm: operator explicitly invokes one Codex CLI run.
# Never source. No retry, no ProjectCTL worker, no Beads, no git commit/integration.
if [[ "$0" != *d1_direct_cli_manual.sh || $# -ne 2 || "$1" != "--execute" || "$2" != "--ack-paid" ]]; then
  echo "Usage: bash experiments/dogfooding/d1_direct_cli_manual.sh --execute --ack-paid" >&2
  exit 2
fi
set -Eeuo pipefail
umask 077

RESEARCH="$HOME/project/My/projectctl-advisory-lab"
CTL="$HOME/.local/state/projectctl-dogfood-d1/fixtures/ctl"
DIRECT="$HOME/.local/state/projectctl-dogfood-d1/fixtures/direct"
OUT="$HOME/.local/state/projectctl-dogfood-d1/observations/direct-attempt-1"
export DO_NOT_TRACK=1
export PYTHONDONTWRITEBYTECODE=1

CTL_CAND="2089c04c5fc679cfb4353a2cef2c2f25c83fa40d"
DIRECT_BASE="da9379c70571c9366f5adfccecdfab148c814fc2"
SPEC_SHA="aac3d5e847cd24849e92860553459bae9f7cbf70cbf00073eba140270160253d"
POLICY_SHA="ce2d1fa410a7ea3ba5eeb62d6e48610de44bcd84cadbc98f537b564918ed6e6d"
TEST_SHA="ba12648bfa7357c501925b5fa1dd4f9685efaf9f44e748285716dd8579aa5a0f"

[[ "$(git -C "$RESEARCH" branch --show-current)" == "research/advisory-skills-eval" ]]
[[ -z "$(git -C "$RESEARCH" status --porcelain)" ]]
[[ "$(git -C "$CTL" rev-parse HEAD)" == "$CTL_CAND" ]]
[[ "$(git -C "$DIRECT" rev-parse HEAD)" == "$DIRECT_BASE" ]]
[[ -z "$(git -C "$CTL" status --porcelain --untracked-files=all)" ]]
[[ -z "$(git -C "$DIRECT" status --porcelain --untracked-files=all)" ]]
[[ -z "$(git -C "$CTL" remote)" && -z "$(git -C "$DIRECT" remote)" ]]
[[ ! -e "$DIRECT/.projectctl" && ! -e "$DIRECT/.beads" ]]
for file in "$CTL/SPEC.md" "$DIRECT/SPEC.md"; do
  [[ "$(sha256sum "$file" | cut -d' ' -f1)" == "$SPEC_SHA" ]]
done
for file in "$CTL/POLICY.md" "$DIRECT/POLICY.md"; do
  [[ "$(sha256sum "$file" | cut -d' ' -f1)" == "$POLICY_SHA" ]]
done
for file in "$CTL/test_user_id.py" "$DIRECT/test_user_id.py"; do
  [[ "$(sha256sum "$file" | cut -d' ' -f1)" == "$TEST_SHA" ]]
done
[[ "$(git -C "$DIRECT" show HEAD:user_id.py)" == $'def normalize_user_id(value):\n    raise NotImplementedError' ]]

CODEX="$(command -v codex)"
VERSION="$("$CODEX" --version)"
if [[ "$VERSION" != "codex-cli 0.163.0" ]]; then
  echo "Codex version drift: '$VERSION' != 'codex-cli 0.163.0'. No paid call." >&2
  exit 3
fi
# Offline option checks: fail closed rather than weaken the isolation policy.
HELP="$("$CODEX" exec --help)"
ROOT_HELP="$("$CODEX" --help)"
for option in '--ignore-user-config' '--ignore-rules' '--ephemeral' '--json' '--model' '--sandbox' '--cd'; do
  if ! grep -Fq -- "$option" <<< "$HELP"; then
    echo "Pinned Codex CLI lacks required exec option $option; no paid call." >&2
    exit 4
  fi
done
if ! grep -Fq -- '--disable' <<< "$ROOT_HELP"; then
  echo "Pinned CLI lacks feature disable control; no paid call." >&2
  exit 4
fi
if [[ -e "$OUT" || -L "$OUT" ]]; then
  echo "Direct attempt evidence directory already exists; refusing duplicate execution: $OUT" >&2
  exit 5
fi

mkdir -m 700 -p "$OUT"
exec > >(tee "$OUT/console.log") 2>&1
trap 'rc=$?; echo "D1_DIRECT_EXIT=$rc"; echo "EVIDENCE_DIR=$OUT"' EXIT

echo "$VERSION" > "$OUT/codex-version.txt"
printf '%s\n' "CLI 0.163.0; model=gpt-6-luna; effort=medium; sandbox=workspace-write;" \
  "approval=never; sandbox_workspace_write.network_access=false;" \
  "ignore-user-config=true; ignore-rules=true; disable apps/plugins; ephemeral=true;" \
  "no ProjectCTL/Beads; no shared Codex session; no Git history writes allowed." \
  > "$OUT/invocation-policy.txt"

# Prompt is derived only from the original direct fixture, never from the ctl solution.
{
  printf '%s\n' "This is one independent coding task in this local Git repository."
  printf '%s\n' "Implement the following frozen SPEC exactly in user_id.py."
  printf '%s\n' "Only modify user_id.py. Do not edit SPEC.md, POLICY.md, test_user_id.py,"
  printf '%s\n' "or any other file. Do not create or modify Git commits, branches or tags."
  printf '%s\n' "Do not use network services or external tools. No delegation or subagents."
  printf '%s\n' "Do not access files outside this repository or any other project/worktree."
  printf '%s\n' "You may inspect the frozen tests, but do not edit them."
  printf '%s\n' "Do not run ProjectCTL. Implement and provide a brief final description."
  printf '\n=== SPEC.md ===\n'
  cat "$DIRECT/SPEC.md"
  printf '\n=== POLICY.md ===\n'
  cat "$DIRECT/POLICY.md"
} > "$OUT/direct-prompt.txt"

echo "=== PRE-FLIGHT DIRECT FIXTURE ==="
printf "ctl_candidate=%s\n" "$(git -C "$CTL" rev-parse HEAD)"
printf "direct_base=%s\n" "$(git -C "$DIRECT" rev-parse HEAD)"
printf "codex_version=%s\n" "$VERSION"
printf "prompt_sha256=%s\n" "$(sha256sum "$OUT/direct-prompt.txt" | cut -d' ' -f1)"
date -u +%FT%TZ

echo "=== ONE PAID DIRECT CODEX CLI TURN (NO RETRY) ==="
SECONDS=0
if "$CODEX" --disable apps --disable plugins exec \
    --ignore-user-config --ignore-rules --strict-config --ephemeral \
    --cd "$DIRECT" --model gpt-6-luna --sandbox workspace-write \
    --config 'approval_policy="never"' \
    --config 'model_reasoning_effort="medium"' \
    --config 'sandbox_workspace_write.network_access=false' \
    --json - < "$OUT/direct-prompt.txt" \
      > "$OUT/codex-events.jsonl" 2> "$OUT/codex-stderr.log"; then
  EXEC_RC=0
else
  EXEC_RC=$?
fi
echo "DIRECT_CODEX_EXEC_RC=$EXEC_RC"
echo "DIRECT_CODEX_EXEC_WALL_SECONDS=$SECONDS"
date -u +%FT%TZ

# Parse telemetry even if the CLI failed. No default made-up token values.
python3 - "$OUT/codex-events.jsonl" <<'PY'
import json, sys
from collections import Counter
from pathlib import Path
p = Path(sys.argv[1])
counts = Counter()
usage = None
threads = []
errors = []
for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
    if not line.strip():
        continue
    try:
        item = json.loads(line)
    except json.JSONDecodeError:
        errors.append("non_json_line")
        continue
    kind = item.get("type", "missing_type")
    counts[kind] += 1
    if kind == "thread.started":
        threads.append(item.get("thread_id"))
    if kind == "turn.completed" and isinstance(item.get("usage"), dict):
        usage = item["usage"]
    if kind in ("turn.failed", "error"):
        errors.append(str(item.get("error", item.get("message", kind)))[:250])
print(json.dumps({"event_counts": dict(counts), "thread_count": len(threads),
                  "usage": usage if usage is not None else "unknown",
                  "errors": errors}, ensure_ascii=False, indent=2))
if counts["turn.started"] > 1:
    print("MULTIPLE_TURNS_REPORTED: do not interpret as a single-turn comparison.")
PY

echo "=== FROZEN SOURCE / GIT POST-CONDITIONS ==="
if [[ "$EXEC_RC" -ne 0 ]]; then
  echo "DIRECT_CODEX_FAILED; preserve event/stderr logs, do not retry or test as success."
  git -C "$DIRECT" status --short --untracked-files=all || true
  exit 6
fi
if [[ "$(git -C "$DIRECT" rev-parse HEAD)" != "$DIRECT_BASE" ]]; then
  echo "DIRECT_GIT_HISTORY_CHANGED; STOP." >&2
  exit 7
fi
if [[ ! -z "$(git -C "$DIRECT" remote)" ]]; then
  echo "DIRECT_REMOTE_ADDED; STOP." >&2
  exit 7
fi
if [[ "$(git -C "$CTL" rev-parse HEAD)" != "$CTL_CAND" ]] ||
   [[ ! -z "$(git -C "$CTL" status --porcelain --untracked-files=all)" ]]; then
  echo "CTL_ARM_CHANGED_UNEXPECTEDLY; STOP." >&2
  exit 7
fi
for path in SPEC.md POLICY.md test_user_id.py; do
  if ! cmp -s "$DIRECT/$path" "$CTL/$path"; then
    echo "PROTECTED_PATH_CHANGED: $path; STOP." >&2
    exit 7
  fi
done

git -C "$DIRECT" status --short --untracked-files=all > "$OUT/direct-git-status.txt"
git -C "$DIRECT" diff --binary --no-ext-diff HEAD -- > "$OUT/direct.patch"
git -C "$DIRECT" diff --check HEAD
python3 - "$DIRECT" <<'PY'
import subprocess, sys
from pathlib import Path
root = Path(sys.argv[1])
def git(*args):
    return subprocess.check_output(["git", "-C", str(root), *args])
changed=set()
for cmd in (
    ("diff", "--no-renames", "--name-only", "-z", "HEAD", "--"),
    ("diff", "--cached", "--no-renames", "--name-only", "-z", "HEAD", "--"),
    ("ls-files", "--others", "--exclude-standard", "-z", "--"),
):
    changed.update(x.decode() for x in git(*cmd).split(b"\0") if x)
print("DIRECT_CHANGED_PATHS:", sorted(changed))
assert changed == {"user_id.py"}, f"Direct out-of-scope paths: {changed}"
assert (root/"user_id.py").is_file() and not (root/"user_id.py").is_symlink()
print("DIRECT_SCOPE_AND_HISTORY_PASS")
PY

echo "=== INDEPENDENT FROZEN UNITTEST (AFTER CODEX EXITS) ==="
(
  cd "$DIRECT"
  python3 -B -m unittest -v test_user_id.py
) > "$OUT/fixed-unittest.stdout.log" 2> "$OUT/fixed-unittest.stderr.log" ||
{
  echo "DIRECT_FIXED_TEST_FAILED; no automatic repair/retry"
  cat "$OUT/fixed-unittest.stderr.log"
  exit 8
}
cat "$OUT/fixed-unittest.stderr.log"
[[ "$(git -C "$DIRECT" rev-parse HEAD)" == "$DIRECT_BASE" ]]
[[ "$(git -C "$CTL" rev-parse HEAD)" == "$CTL_CAND" ]]
[[ -z "$(git -C "$CTL" status --porcelain --untracked-files=all)" ]]
[[ "$(git -C "$DIRECT" diff --name-only HEAD --)" == "user_id.py" ]]
for path in SPEC.md POLICY.md test_user_id.py; do
  cmp -s "$DIRECT/$path" "$CTL/$path"
done
echo "D1_DIRECT_CLI_IMPLEMENTED_AND_FIXED_TEST_PASS__PENDING_HUMAN_ADJUDICATION"
