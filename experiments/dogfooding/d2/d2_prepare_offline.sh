#!/usr/bin/env bash
# D2 only: qualify fixture builder and freeze pristine independent repositories.
# No model calls, no Beads/ProjectCTL mutations, no retry, no existing D1 paths.
if [[ "$0" != *d2_prepare_offline.sh || $# -ne 1 || "$1" != "--create-new-fixtures" ]]; then
  echo "Usage: bash experiments/dogfooding/d2/d2_prepare_offline.sh --create-new-fixtures" >&2
  exit 2
fi
set -Eeuo pipefail
umask 077
export PYTHONDONTWRITEBYTECODE=1
RESEARCH="$HOME/project/My/projectctl-advisory-lab"
ROOT="$HOME/.local/state/projectctl-dogfood-d2"
FIXTURES="$ROOT/fixtures"
CTL="$FIXTURES/ctl"
DIRECT="$FIXTURES/direct"
OUT="$ROOT/observations/offline-setup-v1"
PYTHON="$(command -v python3)"

[[ "$(git -C "$RESEARCH" branch --show-current)" == "research/advisory-skills-eval" ]]
[[ -z "$(git -C "$RESEARCH" status --porcelain)" ]]
[[ -x "$PYTHON" ]]
[[ ! -L "$ROOT" && ! -L "$FIXTURES" ]]
[[ ! -e "$CTL" && ! -L "$CTL" && ! -e "$DIRECT" && ! -L "$DIRECT" ]]
[[ ! -e "$OUT" && ! -L "$OUT" ]]
[[ ! -e "$ROOT/ctl-home" && ! -e "$ROOT/direct-home" ]]
mkdir -p "$FIXTURES" "$ROOT/observations"
mkdir -m 700 "$OUT"
exec > >(tee "$OUT/console.log") 2>&1
trap 'rc=$?; echo "D2_OFFLINE_SETUP_EXIT=$rc"; echo "EVIDENCE_DIR=$OUT"' EXIT

cd "$RESEARCH"
echo "=== 1. OFFLINE FIXTURE BUILDER QUALIFICATION ==="
"$PYTHON" -B -m unittest -v experiments.dogfooding.d2.test_fixture_builder

echo "=== 2. CREATE TWO FRESH REPOSITORIES (NO PAID ACTIVITY) ==="
"$PYTHON" -B experiments/dogfooding/d2/build_fixture.py ctl \
  --output-root "$FIXTURES" | tee "$OUT/ctl-build.txt"
"$PYTHON" -B experiments/dogfooding/d2/build_fixture.py direct \
  --output-root "$FIXTURES" | tee "$OUT/direct-build.txt"

echo "=== 3. VERIFY IDENTICAL FROZEN BASELINES ==="
"$PYTHON" - "$CTL" "$DIRECT" "$OUT" <<'PY'
import hashlib, json, subprocess, sys
from datetime import datetime, timezone
from pathlib import Path
ctl,direct,out=map(Path,sys.argv[1:4])
def git(path,*args):
    return subprocess.run(["git","-C",str(path),*args],
                          capture_output=True,text=True,check=True,timeout=15).stdout.strip()
assert ctl.resolve()!=direct.resolve()
assert ctl.parent.resolve()==direct.parent.resolve()
a,b=git(ctl,"rev-parse","HEAD"),git(direct,"rev-parse","HEAD")
assert a==b,"D2 source baselines not identical"
assert git(ctl,"status","--porcelain")==git(direct,"status","--porcelain")==""
assert git(ctl,"remote")==git(direct,"remote")==""
assert git(ctl,"ls-tree","-r","HEAD")==git(direct,"ls-tree","-r","HEAD")
names=git(ctl,"ls-files").splitlines()
assert len(names)==11
def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()
hashes={}
for name in names:
    assert (ctl/name).is_file() and (direct/name).is_file()
    assert not (ctl/name).is_symlink() and not (direct/name).is_symlink()
    hashes[name]=sha(ctl/name)
    assert hashes[name]==sha(direct/name)
assert {"d2events/parse.py","d2events/report.py","d2events/cli.py"}.issubset(names)
manifest={
 "status":"D2_OFFLINE_BASELINES_FROZEN",
 "observed_at_utc":datetime.now(timezone.utc).isoformat(),
 "ctl_path":str(ctl.resolve()),
 "direct_path":str(direct.resolve()),
 "base_sha":a,
 "spec_sha256":hashes["SPEC.md"],
 "protected_file_sha256":{k:v for k,v in hashes.items()
       if k in {"SPEC.md","POLICY.md","d2events/__init__.py"} or k.startswith("tests/")},
 "all_files_sha256":hashes,
 "allowed_worker_paths":["d2events/parse.py","d2events/report.py","d2events/cli.py"],
 "paid_inference_started":False,
 "projectctl_setup_started":False,
 "direct_arm_started":False
}
(out/"baseline-manifest.json").write_text(json.dumps(manifest,indent=2,sort_keys=True)+"\n")
print(json.dumps({"status":manifest["status"],"baseline_commit":a,
 "spec_sha256":hashes["SPEC.md"],"file_count":len(names),"all_files_match":True},indent=2))
PY
echo "=== 4. STOP BEFORE PROJECTCTL / BEADS / CODEX ==="
echo "D2_OFFLINE_FIXTURES_FROZEN__NO_LIVE_RUN"
