# D2 CTL read-only readiness: 12/13 with test-double boundary error — 2026-10-21

## Observed owner-run result

The operator pulled the research branch from `59ef6d7` to `227e327`, ran `experiments.dogfooding.d2.test_d2_ctl_readiness` under the pinned D0 venv, and saw **12 of 13 tests pass**; the one failing test was `test_git_preserves_porcelain_marker`.

```
AssertionError: ' M source.py\n' != ' M source.py'
Ran 13 tests in 0.002s
FAILED (failures=1)
D2_CTL_READINESS_EXIT=1
```

The cause is a **false failure in the assistant-authored unit-test double**, not evidence of a real Git/head or frozen D2 policy problem. The production helper `read_command` runs `subprocess.run(..., text=True)`, verifies the exit status and applies `stdout.rstrip("\\n")` (preserves porcelain's leading status-space). The failing test mocked **`read_command` itself** to return the raw unnormalized `" M source.py\n"`, bypassing the exact normalization it purported to test.

## Research-only correction

**No changes to `d2_ctl_readiness.py`, D2 fixtures, protected source, Scope, or Codex run artifacts.**

Modify only the single test in `test_d2_ctl_readiness.py` so that `check.subprocess.run` is mocked to return a normal `subprocess.CompletedProcess` with `stdout=" M source.py\n"`, `returncode=0`. The *real* `read_command` and `git` then execute, and the test verifies the normalized result equals `" M source.py"` and asserts the expected subprocess call arguments. This tests the actual boundary rather than sidestepping it. Test count remains **13**.

The child shell's `set -e` stopped immediately after the test failure, so the real `d2_ctl_readiness --read-only` audit **did not run**. No ProjectCTL `run prepare`, Beads claim, paid `run start`, or Direct repeat was called. The Direct accepted evidence and unchanged CTL fixture remain the last independently verified state, pending a new read-only observation.

## Next operator-only check — safe, no paid model call

```bash
bash -c '
set -euo pipefail
cd /home/ai/project/My/projectctl-advisory-lab
git pull --ff-only origin research/advisory-skills-eval
VENV="$HOME/.local/share/projectctl-dogfood-d0/venv"
export PATH="$VENV/bin:$PATH"
export PROJECTCTL_HOME="$HOME/.local/state/projectctl-dogfood-d2/ctl-home"
export BD_ACTOR=d2-dogfood-owner
export BD_DISABLE_METRICS=1 DOLT_DISABLE_EVENT_FLUSH=1 DO_NOT_TRACK=1 PYTHONDONTWRITEBYTECODE=1
"$VENV/bin/python" -B -m unittest -v experiments.dogfooding.d2.test_d2_ctl_readiness
"$VENV/bin/python" -B -m experiments.dogfooding.d2.d2_ctl_readiness --read-only
'
echo "D2_CTL_READINESS_EXIT=$?"
```

Expected (not yet observed): `Ran 13 tests`, `OK`, `D2_CTL_READ_ONLY_PREPARE_GATE_PASS__CLAIM_NOT_AUTHORIZED`, exit 0. If any issue appears, preserve it and stop; do not prepare/start a run or reset the Direct fixture.

**Decision:** `D2_CTL_TEST_DOUBLE_FIXED_RESEARCH_ONLY / READ_ONLY_AUDIT_PENDING / NO_CLAIM / NO_INFERENCE`.
