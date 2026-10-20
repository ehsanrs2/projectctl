#!/usr/bin/env bash
# D2: bounded local Git metadata commit + ProjectCTL brownfield adoption.
# Preview is read-only. Adoption requires explicit approval, does not prepare/run a worker.
if [[ "$0" != *d2_adopt_projectctl_manual.sh ]]; then
  echo "Execute with bash; do not source this script." >&2
  exit 2
fi
if [[ $# -eq 1 && "$1" == "--preview" ]]; then
  MODE=preview
elif [[ $# -eq 2 && "$1" == "--adopt" && "$2" == "--ack-local-git-commit" ]]; then
  MODE=adopt
else
  echo "Usage: bash experiments/dogfooding/d2/d2_adopt_projectctl_manual.sh --preview" >&2
  echo "   or: bash experiments/dogfooding/d2/d2_adopt_projectctl_manual.sh --adopt --ack-local-git-commit" >&2
  exit 2
fi
set -Eeuo pipefail
umask 077
export BD_ACTOR=d2-dogfood-owner
export BD_DISABLE_METRICS=1 DOLT_DISABLE_EVENT_FLUSH=1 DO_NOT_TRACK=1
export PYTHONDONTWRITEBYTECODE=1

RESEARCH="$HOME/project/My/projectctl-advisory-lab"
ROOT="$HOME/.local/state/projectctl-dogfood-d2"
CTL="$ROOT/fixtures/ctl"
DIRECT="$ROOT/fixtures/direct"
OUT="$ROOT/observations/projectctl-adoption-v1"
BEADS_EVIDENCE="$ROOT/observations/beads-setup-v1"
OFFLINE="$ROOT/observations/offline-setup-v1/baseline-manifest.json"
BASE="32836ea5633230e50fb9d907dcdba83e357bcfc6"
SPEC_SHA="8264746827bbb7300bf234023e6617324c78f37aecf524f2427a686925da8815"
TASK="d2ctl-g4q"
VENV="$HOME/.local/share/projectctl-dogfood-d0/venv"
export PROJECTCTL_HOME="$ROOT/ctl-home"
export PATH="$VENV/bin:$PATH"

[[ "$(git -C "$RESEARCH" branch --show-current)" == "research/advisory-skills-eval" ]]
[[ -z "$(git -C "$RESEARCH" status --porcelain --untracked-files=all)" ]]
[[ -x "$VENV/bin/python" && -x "$VENV/bin/projectctl" ]]
[[ -d "$BEADS_EVIDENCE" && -f "$OFFLINE" ]]
[[ "$(cat "$BEADS_EVIDENCE/task-id.txt")" == "$TASK" ]]
[[ "$(git -C "$CTL" rev-parse --show-toplevel)" == "$CTL" ]]
[[ "$(git -C "$DIRECT" rev-parse --show-toplevel)" == "$DIRECT" ]]
[[ "$(git -C "$CTL" rev-parse HEAD)" == "$BASE" ]]
[[ "$(git -C "$DIRECT" rev-parse HEAD)" == "$BASE" ]]
[[ "$(git -C "$CTL" status --porcelain=v1 --untracked-files=all)" == " M .gitignore" ]]
[[ -z "$(git -C "$DIRECT" status --porcelain=v1 --untracked-files=all)" ]]
[[ -z "$(git -C "$CTL" remote)" && -z "$(git -C "$DIRECT" remote)" ]]
[[ -d "$CTL/.beads" && ! -L "$CTL/.beads" ]]
[[ ! -e "$CTL/.projectctl" && ! -L "$CTL/.projectctl" ]]
[[ ! -e "$DIRECT/.beads" && ! -e "$DIRECT/.projectctl" ]]
[[ ! -e "$PROJECTCTL_HOME" && ! -L "$PROJECTCTL_HOME" ]]
[[ "$(sha256sum "$CTL/SPEC.md" | cut -d' ' -f1)" == "$SPEC_SHA" ]]
[[ "$(sha256sum "$DIRECT/SPEC.md" | cut -d' ' -f1)" == "$SPEC_SHA" ]]
[[ ! -e "$OUT" && ! -L "$OUT" ]]

"$VENV/bin/python" - "$OFFLINE" "$CTL" "$DIRECT" "$BASE" <<'PY'
import hashlib,json,subprocess,sys
from pathlib import Path
f,ctl,direct,base=Path(sys.argv[1]),Path(sys.argv[2]),Path(sys.argv[3]),sys.argv[4]
m=json.loads(f.read_text())
assert m["status"]=="D2_OFFLINE_BASELINES_FROZEN" and m["base_sha"]==base
assert Path(m["ctl_path"]).resolve()==ctl.resolve()
assert Path(m["direct_path"]).resolve()==direct.resolve()
for name,expected in m["all_files_sha256"].items():
    for repo in [direct,ctl]:
        if repo == ctl and name == ".gitignore":
            continue
        file=repo/name
        assert file.is_file() and not file.is_symlink()
        assert hashlib.sha256(file.read_bytes()).hexdigest()==expected, name

base_ignore=subprocess.run(["git","-C",str(ctl),"show","HEAD:.gitignore"],
   check=True,capture_output=True,text=True).stdout
current_ignore=(ctl/".gitignore").read_text(encoding="utf-8")
original=base_ignore.splitlines()
current=current_ignore.splitlines()
old=iter(current)
assert all(any(line==next_line for next_line in old) for line in original), \
    "Original ignore rules changed or were reordered"
from collections import Counter
added=list((Counter(current)-Counter(original)).elements())
# Fail closed if Beads introduced anything except known local-only ignore rules
# or comments/blank lines. Top-level .beads/ is forbidden: would hide evidence.
allowed={
 ".dolt/", ".beads/proxieddb/", ".beads/.dolt/",
 "**/RECOVERY*.md", "**/SESSION*.md",
}
rules=[x.strip() for x in added if x.strip() and not x.lstrip().startswith("#")]
assert len(rules)==len(set(rules)), "Duplicate added rules"
assert set(rules).issubset(allowed), f"Unexpected Beads .gitignore entries: {rules}"
assert ".dolt/" in rules, "Missing required local Dolt ignore rule"
assert ".beads/" not in rules and ".projectctl/" not in rules
assert not (ctl/".gitignore").is_symlink()
print(json.dumps({"decision":"D2_BEADS_GITIGNORE_REVIEW_PASS",
 "baseline_rules":original,"added_rules":rules,
 "original_tracked_lines_preserved":True},indent=2))
PY

bd -C "$CTL" show "$TASK" --json | "$VENV/bin/python" -c '
import json,sys
data=json.load(sys.stdin)
items=data if isinstance(data,list) else [data]
assert len(items)==1
task=items[0]
assert task["id"]=="d2ctl-g4q" and task["status"]=="open"
assert not task.get("assignee")
print("D2_CANONICAL_TASK_OPEN_UNCLAIMED")
'
bd -C "$CTL" ready --json | "$VENV/bin/python" -c '
import json,sys
data=json.load(sys.stdin)
items=data if isinstance(data,list) else data.get("issues",data.get("ready",[]))
assert len(items)==1 and items[0]["id"]=="d2ctl-g4q"
print("D2_SOLE_TASK_READY")
'

echo "=== BEADS CHANGED .gitignore (ONLY) ==="
git -C "$CTL" --no-pager diff -- .gitignore
git -C "$CTL" diff --check
echo "D2_PREVIEW_PASS"

if [[ "$MODE" == preview ]]; then
  echo "PREVIEW_ONLY__NO_GIT_COMMIT_NO_PROJECTCTL_INIT"
  exit 0
fi

mkdir -m 700 "$OUT"
exec > >(tee "$OUT/console.log") 2>&1
trap 'rc=$?; printf "D2_ADOPTION_EXIT=%s\nEVIDENCE_DIR=%s\n" "$rc" "$OUT"' EXIT
date -u +%FT%TZ | tee "$OUT/start-utc.txt"
git -C "$CTL" --no-pager diff -- .gitignore > "$OUT/gitignore-reviewed.patch"
bd -C "$CTL" show "$TASK" --json > "$OUT/task-before.json"
bd -C "$CTL" ready --json > "$OUT/ready-before.json"

echo "=== 1. COMMIT ONLY REVIEWED BEADS .gitignore IN ISOLATED CTL FIXTURE ==="
git -C "$CTL" add -- .gitignore
[[ "$(git -C "$CTL" diff --cached --name-only)" == ".gitignore" ]]
git -C "$CTL" diff --cached --check
git -C "$CTL" -c commit.gpgsign=false \
  -c user.name="D2 Fixture" -c user.email="d2-fixture@invalid.example" \
  commit -m "chore(d2): record local Beads ignore metadata"
COMMITTED_HEAD="$(git -C "$CTL" rev-parse HEAD)"
[[ "$(git -C "$CTL" rev-parse HEAD^)" == "$BASE" ]]
[[ "$(git -C "$CTL" diff --name-only "$BASE" "$COMMITTED_HEAD")" == ".gitignore" ]]
[[ -z "$(git -C "$CTL" status --porcelain=v1 --untracked-files=all)" ]]
echo "D2_BEADS_GITIGNORE_COMMIT=$COMMITTED_HEAD"
printf '%s\n' "$COMMITTED_HEAD" > "$OUT/beads-gitignore-commit.txt"

echo "=== 2. PROJECTCTL BROWNFIELD READ-ONLY INSPECTION ==="
"$VENV/bin/projectctl" inspect "$CTL" --json > "$OUT/inspect-before.json"
"$VENV/bin/python" - "$OUT/inspect-before.json" <<'PY'
import json,sys
from pathlib import Path
d=json.loads(Path(sys.argv[1]).read_text())
assert d["classification"]=="existing_unmanaged",d
assert d["dirty"] is False
assert d["detected_task_systems"] == ["beads"]
assert not d.get("unresolved_decisions")
print("D2_PROJECTCTL_INSPECT_PASS")
PY

echo "=== 3. ADOPT EXACT DISPOSABLE CTL FIXTURE (NO MODEL OR TASK CLAIM) ==="
"$VENV/bin/projectctl" init "$CTL" --non-interactive --yes \
 --task-store beads --code-transport local --code-delivery local --json \
 > "$OUT/init.json"
"$VENV/bin/python" - "$OUT/init.json" "$CTL" "$PROJECTCTL_HOME" <<'PY'
import json,sys
from pathlib import Path
from projectctl.project.loader import load_project_config
d=json.loads(Path(sys.argv[1]).read_text())
root,home=Path(sys.argv[2]),Path(sys.argv[3])
assert d["status"]=="initialized" and d["mode"]=="brownfield",d
assert Path(d["project_root"]).resolve()==root.resolve()
assert d.get("unresolved_decisions",[])==[]
cfg=load_project_config(root)
assert cfg.task_store.provider=="beads"
assert cfg.code_transport.mode=="local" and cfg.code_delivery.mode=="local"
assert cfg.scope_governance.mode=="optional"
assert (root/".projectctl/state.sqlite").is_file()
assert (home/"state.sqlite").is_file()
print("D2_PROJECTCTL_INITIALIZED_LOCAL_ONLY")
PY

echo "=== 4. PRESERVE FOLLOW-UP POLICY GATE AND DIRECT INTEGRITY ==="
bd -C "$CTL" show "$TASK" --json > "$OUT/task-after.json"
bd -C "$CTL" ready --json > "$OUT/ready-after.json"
"$VENV/bin/python" - "$OUT/task-after.json" "$OUT/ready-after.json" <<'PY'
import json,sys
from pathlib import Path
s=json.loads(Path(sys.argv[1]).read_text())
r=json.loads(Path(sys.argv[2]).read_text())
s=s if isinstance(s,list) else [s]
r=r if isinstance(r,list) else r.get("issues",r.get("ready",[]))
assert len(s)==len(r)==1
assert s[0]["id"]==r[0]["id"]=="d2ctl-g4q"
assert s[0]["status"]=="open" and not s[0].get("assignee")
print("D2_TASK_UNCLAIMED_AFTER_ADOPTION")
PY
git -C "$CTL" status --porcelain=v1 --untracked-files=all > "$OUT/git-status-after.txt"
cat "$OUT/git-status-after.txt"
[[ "$(git -C "$CTL" rev-parse HEAD)" == "$COMMITTED_HEAD" ]]
[[ "$(git -C "$DIRECT" rev-parse HEAD)" == "$BASE" ]]
[[ -z "$(git -C "$DIRECT" status --porcelain=v1 --untracked-files=all)" ]]
[[ -z "$(git -C "$CTL" remote)" && -z "$(git -C "$DIRECT" remote)" ]]
[[ "$(sha256sum "$CTL/SPEC.md" | cut -d' ' -f1)" == "$SPEC_SHA" ]]
[[ "$(sha256sum "$DIRECT/SPEC.md" | cut -d' ' -f1)" == "$SPEC_SHA" ]]
[[ ! -e "$DIRECT/.beads" && ! -e "$DIRECT/.projectctl" ]]
date -u +%FT%TZ | tee "$OUT/end-utc.txt"
echo "D2_PROJECTCTL_ADOPTED__SCOPE_AND_VERIFICATION_POLICY_PENDING"
