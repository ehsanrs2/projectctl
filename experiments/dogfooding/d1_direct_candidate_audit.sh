#!/usr/bin/env bash
# D1 direct control arm: semantic source evidence, READ ONLY. No commands that write.
if [[ "$0" != *d1_direct_candidate_audit.sh || $# -ne 1 || "$1" != "--read-only" ]]; then
  echo "Usage: bash experiments/dogfooding/d1_direct_candidate_audit.sh --read-only" >&2
  exit 2
fi
set -Eeuo pipefail

RESEARCH="$HOME/project/My/projectctl-advisory-lab"
CTL="$HOME/.local/state/projectctl-dogfood-d1/fixtures/ctl"
DIRECT="$HOME/.local/state/projectctl-dogfood-d1/fixtures/direct"
OUT="$HOME/.local/state/projectctl-dogfood-d1/observations/direct-attempt-1"
CTL_CAND="2089c04c5fc679cfb4353a2cef2c2f25c83fa40d"
DIRECT_BASE="da9379c70571c9366f5adfccecdfab148c814fc2"
SPEC_SHA="aac3d5e847cd24849e92860553459bae9f7cbf70cbf00073eba140270160253d"
POLICY_SHA="ce2d1fa410a7ea3ba5eeb62d6e48610de44bcd84cadbc98f537b564918ed6e6d"
TEST_SHA="ba12648bfa7357c501925b5fa1dd4f9685efaf9f44e748285716dd8579aa5a0f"

[[ "$(git -C "$RESEARCH" branch --show-current)" == "research/advisory-skills-eval" ]]
[[ "$(git -C "$CTL" rev-parse HEAD)" == "$CTL_CAND" ]]
[[ "$(git -C "$DIRECT" rev-parse HEAD)" == "$DIRECT_BASE" ]]
[[ -z "$(git -C "$CTL" status --porcelain --untracked-files=all)" ]]
[[ -z "$(git -C "$CTL" remote)" && -z "$(git -C "$DIRECT" remote)" ]]
[[ ! -e "$DIRECT/.projectctl" && ! -e "$DIRECT/.beads" ]]
[[ -d "$OUT" && -f "$OUT/direct.patch" ]]
for file in "$CTL/SPEC.md" "$DIRECT/SPEC.md"; do
  [[ "$(sha256sum "$file" | cut -d' ' -f1)" == "$SPEC_SHA" ]]
done
for file in "$CTL/POLICY.md" "$DIRECT/POLICY.md"; do
  [[ "$(sha256sum "$file" | cut -d' ' -f1)" == "$POLICY_SHA" ]]
done
for file in "$CTL/test_user_id.py" "$DIRECT/test_user_id.py"; do
  [[ "$(sha256sum "$file" | cut -d' ' -f1)" == "$TEST_SHA" ]]
done

echo "=== 1. EXACT DIRECT SOURCE AND SCOPE ==="
python3 - "$DIRECT" <<'PY'
from pathlib import Path
import subprocess, sys

root = Path(sys.argv[1])
def git(*args):
    return subprocess.check_output(["git", "-C", str(root), *args])
changed = set()
for cmd in (
    ("diff", "--no-renames", "--name-only", "-z", "HEAD", "--"),
    ("diff", "--cached", "--no-renames", "--name-only", "-z", "HEAD", "--"),
    ("ls-files", "--others", "--exclude-standard", "-z", "--"),
):
    changed.update(p.decode("utf-8") for p in git(*cmd).split(b"\0") if p)
assert changed == {"user_id.py"}, f"Unexpected changed paths: {sorted(changed)}"
assert (root / "user_id.py").is_file() and not (root / "user_id.py").is_symlink()
assert git("rev-parse", "HEAD").decode().strip() == "da9379c70571c9366f5adfccecdfab148c814fc2"
assert git("remote").strip() == b""
print("DIRECT_AUDIT_SCOPE_PASS; paths:", sorted(changed))
PY

echo "=== 2. FROZEN SPEC ==="
cat "$DIRECT/SPEC.md"

echo "=== 3. DIRECT USER_ID.PY (ACTUAL CODE) ==="
cat "$DIRECT/user_id.py"

echo "=== 4. DIRECT DIFF FROM FROZEN BASE ==="
git -C "$DIRECT" --no-pager diff --binary --no-ext-diff HEAD -- user_id.py
git -C "$DIRECT" --no-pager diff --cached --binary --no-ext-diff HEAD -- user_id.py
git -C "$DIRECT" diff --check HEAD

echo "=== 5. PROJECTCTL VERIFIED IMPLEMENTATION (COMPARISON ONLY) ==="
cat "$CTL/user_id.py"
echo "source_equal=$(if cmp -s "$DIRECT/user_id.py" "$CTL/user_id.py"; then echo yes; else echo no; fi)"

echo "=== 6. PROTECTED FILES: DIRECT / CTL SHA256 ==="
for file in SPEC.md POLICY.md test_user_id.py; do
  sha256sum "$DIRECT/$file" "$CTL/$file"
  cmp -s "$DIRECT/$file" "$CTL/$file"
done

echo "=== 7. FROZEN TEST RESULTS FROM COMPLETED DIRECT RUN ==="
[[ -f "$OUT/fixed-unittest.stderr.log" ]]
cat "$OUT/fixed-unittest.stderr.log"

echo "=== 8. RECORDED DIRECT USAGE (NO NEW CODEX CALL) ==="
python3 - "$OUT/codex-events.jsonl" <<'PY'
import json,sys
from pathlib import Path
from collections import Counter
counts=Counter()
usage=None
bad_lines=0
for line in Path(sys.argv[1]).read_text(errors="replace").splitlines():
    if not line.strip(): continue
    try: item=json.loads(line)
    except json.JSONDecodeError:
        bad_lines+=1
        continue
    t=item.get("type","missing_type")
    counts[t]+=1
    if t=="turn.completed" and isinstance(item.get("usage"),dict): usage=item["usage"]
print(json.dumps({"event_types":dict(counts),"usage":usage if usage else "unknown","malformed_lines":bad_lines},indent=2))
assert counts["thread.started"]==1 and counts["turn.started"]==1
assert counts["turn.completed"]==1 and counts["turn.failed"]==0
assert bad_lines==0
PY

echo "=== 9. BOTH REPOSITORY STATES ==="
echo "ctl_HEAD=$(git -C "$CTL" rev-parse HEAD)"
echo "direct_HEAD=$(git -C "$DIRECT" rev-parse HEAD)"
echo "direct_status:"
git -C "$DIRECT" status --short --untracked-files=all

echo "D1_DIRECT_CANDIDATE_AUDIT_READ_ONLY_PASS__PENDING_SEMANTIC_ADJUDICATION"
