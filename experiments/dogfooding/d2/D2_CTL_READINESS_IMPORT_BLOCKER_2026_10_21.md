# D2 CTL readiness import blocker — corrected on research branch (2026-10-21)

**Observed decision:** `D2_CTL_READINESS_TEST_IMPORT_BLOCKED / NO_CLAIM / NO_INFERENCE`.

The owner fast-forwarded `research/advisory-skills-eval` from `c2b305d` to `59ef6d7`, then ran the proposed child-Bash offline checks. Python `unittest` could not import `experiments.dogfooding.d2.test_d2_ctl_readiness` because `d2_ctl_readiness.py` attempted:

```python
from experiments.dogfooding.d2.d2_freeze_policy import POLICY_SHA, SPEC_SHA
```

**This was an assistant-authored wrong-module import, not a failing assertion or a user fixture/environment issue.** Source inspection confirmed `d2_freeze_policy.py` defines only `SPEC_SHA`, whereas the proven `d2_post_freeze_audit.py` defines the frozen four-file `POLICY_SHA` mapping. The loader emitted `Ran 1 test`, `FAILED (errors=1)`: this is the single `_FailedTest` placeholder; **none of the twelve intended tests ran**. `set -e` in the child Bash caused exit `D2_CTL_READINESS_EXIT=1` *before* calling the read-only readiness audit. No direct/ctl fixture Git or policy mutation, ProjectCTL run preparation, Beads claim, worker call or quota-refresh operation was requested in that sequence.

## Research-only fix and offline regression gate

In `experiments/dogfooding/d2/d2_ctl_readiness.py`, import `SPEC_SHA` from `d2_freeze_policy` and `POLICY_SHA` from `d2_post_freeze_audit`, where those values were already defined and qualified independently. This is a one-location import change; **do not** add a duplicate mapping of frozen hashes or modify frozen D2 files.

In `test_d2_ctl_readiness.py`, add a regression test asserting the readiness module's mapping equals the already trusted `d2_post_freeze_audit.POLICY_SHA` and the original freeze script's `SPEC_SHA`, with exactly the four frozen management paths. The test suite now defines **13** tests, all pending actual operator execution; the original 12 never ran.

### Safe operator rerun (child shell, NO inference)

```bash
bash -c '
set -euo pipefail
cd /home/ai/project/My/projectctl-advisory-lab
git pull --ff-only origin research/advisory-skills-eval
VENV="$HOME/.local/share/projectctl-dogfood-d0/venv"
export PATH="$VENV/bin:$PATH"
export PROJECTCTL_HOME="$HOME/.local/state/projectctl-dogfood-d2/ctl-home"
export BD_ACTOR=d2-dogfood-owner
export BD_DISABLE_METRICS=1
export DOLT_DISABLE_EVENT_FLUSH=1
export DO_NOT_TRACK=1
export PYTHONDONTWRITEBYTECODE=1
"$VENV/bin/python" -B -m unittest -v experiments.dogfooding.d2.test_d2_ctl_readiness
"$VENV/bin/python" -B -m experiments.dogfooding.d2.d2_ctl_readiness --read-only
'
echo "D2_CTL_READINESS_EXIT=$?"
```

**Expected, not yet observed:** `Ran 13 tests; OK` and `D2_CTL_READ_ONLY_PREPARE_GATE_PASS__CLAIM_NOT_AUTHORIZED` with exit code zero. Any failure stops the gate, no automated retry or fixture reset. The prior Direct result and evidence remain unchanged; there is **no permission to `projectctl run prepare`, `run start`, or perform any additional paid Codex call** in this repair.

**Current state:** `D2_DIRECT_ONE_TURN_SUCCESS / CTL_READINESS_IMPORT_FIXED_IN_RESEARCH / 13_OFFLINE_TESTS_PENDING / CTL_UNPREPARED`.
