#!/usr/bin/env bash
# D1-R3: single operator-invoked ProjectCTL independent verification gate.
# Passing verification creates an isolated candidate Git commit but does NOT integrate.
if [[ "$0" != *d1_r3_verify_manual.sh || $# -ne 1 || "$1" != "--verify" ]]; then
  echo "Usage: bash experiments/dogfooding/d1_r3_verify_manual.sh --verify" >&2
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
SETUP="7388896be4a7ba46770ae76c7cd5480f0cd9e27b"
DIRECT_BASE="da9379c70571c9366f5adfccecdfab148c814fc2"
SPEC_SHA="aac3d5e847cd24849e92860553459bae9f7cbf70cbf00073eba140270160253d"

[[ "$(git -C "$RESEARCH" branch --show-current)" == "research/advisory-skills-eval" ]]
[[ -z "$(git -C "$RESEARCH" status --porcelain)" ]]
[[ "$(git -C "$CTL" rev-parse HEAD)" == "$SETUP" ]]
[[ "$(git -C "$DIRECT" rev-parse HEAD)" == "$DIRECT_BASE" ]]
[[ -z "$(git -C "$CTL" status --porcelain --untracked-files=all)" ]]
[[ -z "$(git -C "$DIRECT" status --porcelain --untracked-files=all)" ]]
[[ -z "$(git -C "$CTL" remote)" && -z "$(git -C "$DIRECT" remote)" ]]
[[ "$(sha256sum "$CTL/SPEC.md" | cut -d' ' -f1)" == "$SPEC_SHA" ]]
[[ "$(sha256sum "$DIRECT/SPEC.md" | cut -d' ' -f1)" == "$SPEC_SHA" ]]
[[ -x "$VENV/bin/projectctl" && -x "$VENV/bin/python" ]]

RUN_DIR="$CTL/.projectctl/runs/$RUN_ID"
OUT="$HOME/.local/state/projectctl-dogfood-d1/observations/ctl-attempt-4/verification"
if [[ -e "$OUT" || -L "$OUT" ]]; then
  echo "Verification evidence directory already exists. Refusing re-run: $OUT" >&2
  exit 3
fi
mkdir -m 700 -p "$OUT"
exec > >(tee "$OUT/console.log") 2>&1
trap 'code=$?; echo "D1_R3_VERIFICATION_EXIT=$code"; echo "EVIDENCE_DIR=$OUT"' EXIT

echo "=== 1. VERIFY PRE-RUN STATE AND EXACT WRITE SCOPE ==="
"$VENV/bin/projectctl" run show "$RUN_ID" --project "$CTL" --json > "$OUT/run-before.json"
"$VENV/bin/python" - "$OUT/run-before.json" "$CTL" "$PROJECTCTL_HOME" "$RUN_DIR" "$SETUP" "$RUN_ID" "$OUT" <<'PY'
import json, subprocess, sys
from pathlib import Path

record_path, root_s, home_s, run_dir_s, expected_base, run_id, out_s = sys.argv[1:8]
root, home, run_dir, out = map(Path, (root_s, home_s, run_dir_s, out_s))
payload = json.loads(Path(record_path).read_text())
run = payload["run"]
assert run["run_id"] == run_id and run["task_id"] == "d1ctl-lh4"
assert run["status"] == "verifying" and run["terminal_reason"] is None
assert run["base_commit"] == expected_base and run["candidate_commit"] is None
assert run["started_at"] is not None and run["lease_owner"] is None
assert run["worker_provider"] == "codex"
assert run["worktree_id"] == run_id
worktree = Path(run["worktree_path"]).resolve()
assert worktree.is_dir() and worktree.is_relative_to(home.resolve() / "worktrees")
assert (run_dir / "worker-result.json").is_file()
worker = json.loads((run_dir / "worker-result.json").read_text())
assert worker["run_id"] == run_id and worker["task_id"] == "d1ctl-lh4"
assert worker["status"] == "implemented"
assert (run_dir / "execution-plan.json").is_file()

def git(*args):
    return subprocess.run(
        ["git", "-C", str(worktree), *args],
        check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    ).stdout

assert git("rev-parse", "HEAD").decode().strip() == expected_base
changed = set()
for command in (
    ("diff", "--no-renames", "--name-only", "-z", "HEAD", "--"),
    ("diff", "--cached", "--no-renames", "--name-only", "-z", "HEAD", "--"),
    ("ls-files", "--others", "--exclude-standard", "-z", "--"),
):
    changed.update(x.decode("utf-8") for x in git(*command).split(b"\0") if x)
assert changed == {"user_id.py"}, f"Unexpected worker diff paths: {sorted(changed)}"
target = worktree / "user_id.py"
assert target.is_file() and not target.is_symlink()
out.joinpath("worktree-path.txt").write_text(str(worktree) + "\n")
print("PRE_VERIFICATION_SCOPE_PASS; changes:", sorted(changed))
PY

WT="$(cat "$OUT/worktree-path.txt")"
git -C "$WT" status --short --untracked-files=all > "$OUT/worker-git-status-before.txt"
git -C "$WT" diff --binary --no-ext-diff HEAD -- > "$OUT/worker-preverify.patch"
cp "$WT/user_id.py" "$OUT/worker-user_id-before.py"

echo "=== 2. INDEPENDENT PROJECTCTL VERIFICATION (ONCE) ==="
date -u +%FT%TZ
if ! "$VENV/bin/projectctl" run verify "$RUN_ID" \
       --project "$CTL" --json > "$OUT/verify.json" 2> "$OUT/verify.stderr"; then
  cat "$OUT/verify.stderr"
  echo "VERIFY_FAILED: no automatic retry or integrate; inspect ProjectCTL run and evidence."
  "$VENV/bin/projectctl" run show "$RUN_ID" --project "$CTL" --json > "$OUT/run-after-failure.json" || true
  exit 4
fi

echo "=== 3. VERIFY RESULTS, CANDIDATE COMMIT, AND MAIN BRANCH ==="
"$VENV/bin/projectctl" run show "$RUN_ID" --project "$CTL" --json > "$OUT/run-after.json"
"$VENV/bin/python" - "$OUT/verify.json" "$OUT/run-after.json" "$CTL" "$RUN_ID" "$SETUP" <<'PY'
import json, subprocess, sys
from pathlib import Path

verification = json.loads(Path(sys.argv[1]).read_text())
shown = json.loads(Path(sys.argv[2]).read_text())
root, run_id, base = Path(sys.argv[3]), sys.argv[4], sys.argv[5]
run, manifest, evidence = verification["run"], verification["verification"], verification["evidence"]
assert run["run_id"] == run_id and shown["run"]["run_id"] == run_id
assert run["status"] == "ready_to_integrate"
assert shown["run"]["status"] == "ready_to_integrate"
assert run["terminal_reason"] is None
assert run["candidate_commit"] is not None
assert manifest["overall_pass"] is True
assert evidence["overall_pass"] is True
assert manifest["policy_violations"] == []
assert manifest["changed_paths"] == ["user_id.py"]
assert evidence["changed_paths"] == ["user_id.py"]
assert manifest["base_commit"] == base
assert evidence["base_commit"] == base
assert evidence["candidate_commit"] == run["candidate_commit"]
assert manifest["profile"] == "default"
checks = {c["id"]: c for c in manifest["checks"]}
assert set(checks) == {"diff-policy", "execution-write-scope", "fixed-unittest", "workspace-stability"}
for check in checks.values():
    assert check["status"] == "passed", f"Failed check: {check['id']}: {check['status']}"
assert checks["fixed-unittest"]["argv"] == ["python3", "-B", "-m", "unittest", "-v", "test_user_id.py"]
assert checks["fixed-unittest"]["exit_code"] == 0
candidate = run["candidate_commit"]
worktree = Path(run["worktree_path"])

def git(path, *args):
    return subprocess.run(
        ["git", "-C", str(path), *args], check=True,
        capture_output=True, text=True,
    ).stdout.strip()

assert git(root, "rev-parse", "HEAD") == base, "Main changed unexpectedly"
assert git(root, "status", "--porcelain") == ""
assert git(worktree, "rev-parse", "HEAD") == candidate
assert git(worktree, "status", "--porcelain") == ""
parents = git(worktree, "rev-list", "--parents", "-n", "1", candidate).split()
assert parents == [candidate, base]
assert git(worktree, "diff", "--name-only", base, candidate) == "user_id.py"
assert git(root, "remote") == ""
print(json.dumps({
    "decision": "D1_R3_VERIFICATION_PASS__PENDING_HUMAN_ADJUDICATION",
    "run_id": run_id,
    "status": run["status"],
    "candidate_commit": candidate,
    "checks": {key: value["status"] for key, value in checks.items()},
    "changed_paths": evidence["changed_paths"],
    "integration_performed": False,
}, indent=2))
PY

git -C "$WT" diff --binary "$SETUP" HEAD -- > "$OUT/candidate.patch"
git -C "$WT" show --format=fuller --stat HEAD > "$OUT/candidate-commit.txt"
cp "$RUN_DIR/verification-manifest.json" "$OUT/verification-manifest.json"
cp "$RUN_DIR/evidence-manifest.json" "$OUT/evidence-manifest.json"
if [[ -f "$RUN_DIR/verification/fixed-unittest.stderr.log" ]]; then
  cp "$RUN_DIR/verification/fixed-unittest.stderr.log" "$OUT/fixed-unittest.stderr.log"
fi
if [[ -f "$RUN_DIR/verification/fixed-unittest.stdout.log" ]]; then
  cp "$RUN_DIR/verification/fixed-unittest.stdout.log" "$OUT/fixed-unittest.stdout.log"
fi
echo "VERIFIED_CANDIDATE_READY_FOR_REVIEW; INTEGRATION_NOT_PERFORMED"
