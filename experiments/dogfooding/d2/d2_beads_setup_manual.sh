#!/usr/bin/env bash
# D2 local-only Beads authority: initialize exactly one frozen SPEC task.
# This script does NOT commit, initialize ProjectCTL, claim, run Codex or call a model.
if [[ "$0" != *d2_beads_setup_manual.sh || $# -ne 1 || "$1" != "--init-local-task" ]]; then
  echo "Usage: bash experiments/dogfooding/d2/d2_beads_setup_manual.sh --init-local-task" >&2
  exit 2
fi
set -Eeuo pipefail
umask 077
export BD_ACTOR="d2-dogfood-owner"
export BD_DISABLE_METRICS=1
export DOLT_DISABLE_EVENT_FLUSH=1
export DO_NOT_TRACK=1
export PYTHONDONTWRITEBYTECODE=1

RESEARCH="$HOME/project/My/projectctl-advisory-lab"
ROOT="$HOME/.local/state/projectctl-dogfood-d2"
CTL="$ROOT/fixtures/ctl"
DIRECT="$ROOT/fixtures/direct"
OFFLINE="$ROOT/observations/offline-setup-v1/baseline-manifest.json"
OUT="$ROOT/observations/beads-setup-v1"
BASE="32836ea5633230e50fb9d907dcdba83e357bcfc6"
SPEC="8264746827bbb7300bf234023e6617324c78f37aecf524f2427a686925da8815"
BD="$(command -v bd)"
PYTHON="$(command -v python3)"

[[ -x "$BD" && -x "$PYTHON" ]]
[[ "$(git -C "$RESEARCH" branch --show-current)" == "research/advisory-skills-eval" ]]
[[ -z "$(git -C "$RESEARCH" status --porcelain --untracked-files=all)" ]]
[[ -d "$CTL" && -d "$DIRECT" && -f "$OFFLINE" ]]
[[ ! -e "$CTL/.beads" && ! -L "$CTL/.beads" ]]
[[ ! -e "$CTL/.projectctl" && ! -e "$DIRECT/.beads" && ! -e "$DIRECT/.projectctl" ]]
[[ ! -e "$ROOT/ctl-home" ]]
[[ ! -e "$OUT" && ! -L "$OUT" ]]
[[ "$(git -C "$CTL" rev-parse --show-toplevel)" == "$CTL" ]]
[[ "$(git -C "$DIRECT" rev-parse --show-toplevel)" == "$DIRECT" ]]
[[ "$(git -C "$CTL" rev-parse HEAD)" == "$BASE" ]]
[[ "$(git -C "$DIRECT" rev-parse HEAD)" == "$BASE" ]]
[[ -z "$(git -C "$CTL" status --porcelain --untracked-files=all)" ]]
[[ -z "$(git -C "$DIRECT" status --porcelain --untracked-files=all)" ]]
[[ -z "$(git -C "$CTL" remote)" && -z "$(git -C "$DIRECT" remote)" ]]
[[ "$(sha256sum "$CTL/SPEC.md" | cut -d' ' -f1)" == "$SPEC" ]]
[[ "$(sha256sum "$DIRECT/SPEC.md" | cut -d' ' -f1)" == "$SPEC" ]]

"$PYTHON" - "$OFFLINE" "$CTL" "$DIRECT" "$BASE" "$SPEC" <<'PY'
import hashlib,json,sys
from pathlib import Path
manifest=Path(sys.argv[1])
ctl,direct=Path(sys.argv[2]),Path(sys.argv[3])
m=json.loads(manifest.read_text())
assert m["status"]=="D2_OFFLINE_BASELINES_FROZEN"
assert m["base_sha"]==sys.argv[4] and m["spec_sha256"]==sys.argv[5]
assert Path(m["ctl_path"]).resolve()==ctl.resolve()
assert Path(m["direct_path"]).resolve()==direct.resolve()
assert len(m["all_files_sha256"])==11
for relative,expected in m["all_files_sha256"].items():
    for root in (ctl,direct):
        p=root/relative
        assert p.is_file() and not p.is_symlink()
        assert hashlib.sha256(p.read_bytes()).hexdigest()==expected,relative
print("FROZEN_PAIR_MANIFEST_VALIDATED")
PY

VERSION="$("$BD" --version)"
if [[ "$VERSION" != *"1.3.1"* ]]; then
  echo "Unexpected Beads version: $VERSION. Refusing setup." >&2
  exit 3
fi
for opt in --non-interactive --skip-agents --skip-hooks --setup-exclude --prefix; do
  if ! "$BD" init --help | grep -Fq -- "$opt"; then
    echo "Beads init is missing $opt; refusing setup." >&2
    exit 3
  fi
done

mkdir -m 700 "$OUT"
exec > >(tee "$OUT/console.log") 2>&1
trap 'rc=$?; echo "D2_BEADS_SETUP_EXIT=$rc"; echo "EVIDENCE_DIR=$OUT"' EXIT
printf '%s\n' "$VERSION" > "$OUT/beads-version.txt"

echo "=== 1. INITIALIZE BEADS, LOCAL CTL FIXTURE ONLY ==="
cd "$CTL"
"$BD" init --non-interactive --skip-agents --skip-hooks --setup-exclude \
  --prefix d2ctl > "$OUT/beads-init.stdout" 2> "$OUT/beads-init.stderr"
echo "BEADS_INIT_PASS"

echo "=== 2. CREATE ONE TASK FROM IMMUTABLE SPEC ==="
"$BD" create "D2: Implement offline JSONL activity reporting" \
  --description "$(cat "$CTL/SPEC.md")" --type task --priority 2 --json \
  > "$OUT/task-created.json"
"$PYTHON" - "$OUT/task-created.json" "$CTL/SPEC.md" "$OUT/task-id.txt" <<'PY'
import json,re,sys
from pathlib import Path
data=json.loads(Path(sys.argv[1]).read_text())
item=data[0] if isinstance(data,list) else data
if not isinstance(item,dict) or "id" not in item:
    raise ValueError("Task create returned an unknown JSON structure")
assert re.fullmatch(r"d2ctl-[a-z0-9]+",item["id"])
if item.get("description") is not None:
    assert item["description"]==Path(sys.argv[2]).read_text()
assert item.get("status")=="open" and item.get("issue_type",item.get("type")) in ("task",None)
Path(sys.argv[3]).write_text(item["id"]+"\n")
print("ONE_D2_TASK_CREATED:",item["id"])
PY

TASK="$(cat "$OUT/task-id.txt")"
"$BD" show "$TASK" --json > "$OUT/task-after.json"
"$BD" ready --json > "$OUT/ready-after.json"

echo "=== 3. VERIFY BEADS AND GIT STATE; NO PROJECTCTL INIT ==="
"$PYTHON" - "$OUT/task-after.json" "$OUT/ready-after.json" "$CTL/SPEC.md" "$TASK" <<'PY'
import json,sys
from pathlib import Path
def items(data):
    if isinstance(data,list): return data
    if "id" in data: return [data]
    for key in ("issues","ready","results","items"):
        if isinstance(data.get(key),list): return data[key]
    raise ValueError("Unsupported Beads response structure")
task=items(json.loads(Path(sys.argv[1]).read_text()))
ready=items(json.loads(Path(sys.argv[2]).read_text()))
assert len(task)==1 and task[0]["id"]==sys.argv[4]
assert task[0]["description"]==Path(sys.argv[3]).read_text()
assert task[0]["status"]=="open" and not task[0].get("assignee")
assert len(ready)==1 and ready[0]["id"]==sys.argv[4]
print("D2_SOLE_BEADS_TASK_READY_UNCLAIMED")
PY
git -C "$CTL" status --short --untracked-files=all | tee "$OUT/ctl-git-status.txt"
git -C "$CTL" diff -- .gitignore > "$OUT/gitignore-working-diff.patch"
git -C "$CTL" diff --cached -- .gitignore > "$OUT/gitignore-staged-diff.patch"
if [[ -f "$CTL/.gitignore" ]]; then
  cp "$CTL/.gitignore" "$OUT/gitignore-after.txt"
fi
[[ "$(git -C "$CTL" rev-parse HEAD)" == "$BASE" ]]
[[ "$(git -C "$DIRECT" rev-parse HEAD)" == "$BASE" ]]
[[ -z "$(git -C "$DIRECT" status --porcelain --untracked-files=all)" ]]
[[ -z "$(git -C "$CTL" remote)" && -z "$(git -C "$DIRECT" remote)" ]]
[[ "$(sha256sum "$CTL/SPEC.md" | cut -d' ' -f1)" == "$SPEC" ]]
[[ "$(sha256sum "$DIRECT/SPEC.md" | cut -d' ' -f1)" == "$SPEC" ]]
[[ ! -e "$DIRECT/.beads" && ! -e "$DIRECT/.projectctl" ]]
echo "D2_BEADS_LOCAL_READY__REVIEW_GIT_CHANGES_BEFORE_PROJECTCTL_INIT"
