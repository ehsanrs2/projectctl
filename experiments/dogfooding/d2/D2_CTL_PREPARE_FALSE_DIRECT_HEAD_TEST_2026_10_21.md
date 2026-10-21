# D2 CTL Prepare offline mock mismatch — corrected before any Claim (2026-10-21)

**Observed failure:** `D2_CTL_PREPARE_OFFLINE_14_OF_15 / PREVIEW_NOT_RUN / PREPARE_NOT_DISPATCHED / NO_INFERENCE`.

## Owner terminal evidence

The operator fast-forwarded research `01f7479..38e6305` and ran the 15 pure offline tests of `test_d2_ctl_prepare_once.py`. Fourteen reported `ok`; `test_prepared_policy_positive_with_isolated_fake_worktree` raised:

```text
ValueError: Direct source baseline moved unexpectedly
Ran 15 tests in 0.011s
FAILED (errors=1)
D2_CTL_PREPARE_EXIT=1
```

Because the run was enclosed in a child shell using `set -euo pipefail`, it **stopped before the Preview and the authorized `--prepare --ack-claim`**. Neither the Beads claim nor the CTL worker/run execution happened in this observed sequence. The existing one-time owner permission to perform a first Prepare has not yet been exercised. Direct artifacts remain frozen; do not reset/reuse/modify them.

## Root cause and scope of fix

The assistant-authored *synthetic test* mocked `git(root, "rev-parse", "HEAD")` to return the **CTL policy SHA** for every repository path. The real production function `check_preparation` intentionally checks **two different frozen HEADs**: CTL and the new CTL worktree must have policy SHA `3c69dd42497acadadc5d64e7b4abe5d412b309f5`, whereas the unchanged Direct fixture must have BASE SHA `32836ea5633230e50fb9d907dcdba83e357bcfc6`. The mock therefore *manufactured* a Direct drift and yielded a false error. The positive test's fake Git command now chooses the appropriate frozen SHA for `h.DIRECT` and the CTL SHA for other test fixture paths. In the same test, a separate negative check deliberately returns the CTL SHA for the Direct HEAD and confirms the implementation **still refuses genuine Direct drift**.

Changes are restricted to `experiments/dogfooding/d2/test_d2_ctl_prepare_once.py`; no changes to the production Prepare harness, ProjectCTL runtime, spec, frozen policy, paired fixtures, historical evidence or owner authorization. The suite still defines 15 tests. The correction has been inspected in GitHub but **not executed on the operator's pinned venv**.

## Next safe operator step

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
"$VENV/bin/python" -B -m unittest -v experiments.dogfooding.d2.test_d2_ctl_prepare_once
"$VENV/bin/python" -B -m experiments.dogfooding.d2.d2_ctl_prepare_once --preview
# The user has separately authorized ONE Prepare, but observe the actual
# offline tests/Preview result before executing the state-mutating command.
'
echo "D2_CTL_PREPARE_PREVIEW_EXIT=$?"
```

**Expected but not yet observed:** `Ran 15 tests; OK` and `D2_CTL_PREPARE_PREVIEW_PASS__NO_CLAIM_NO_INFERENCE`. If there is a failure, stop before the actual Prepare and preserve logs. The actual one-time `--prepare --ack-claim` must be invoked separately in a child shell only once the preconditions pass; it cannot be automatically retried if it is dispatched or if an evidence directory already exists.

**State:** `D2_DIRECT_ACCEPTED / CTL_PREPARE_MOCK_FIXED_RESEARCH_ONLY / PREPARE_OWNER_AUTHORIZED_UNEXERCISED / CTL_PAID_START_NOT_AUTHORIZED`.
