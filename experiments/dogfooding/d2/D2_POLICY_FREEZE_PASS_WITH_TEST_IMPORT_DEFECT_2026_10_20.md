# D2 required policy freeze — observed success with offline-test qualification deviation

**Date:** 2026-10-20. **Status:** `D2_POLICY_FROZEN_LOCAL_ONLY`; post-freeze independent read-only audit pending; no worker or paid Codex turns observed.

## Operator evidence (not inferred)

The operator fast-forwarded research branch `2fd49c0..e43c83a`, then attempted the nine test cases in `experiments.dogfooding.d2.test_d2_freeze_policy`. The unittest module failed **during import, before any tests ran**, because the test file had `from unittest.mock import patch, SimpleNamespace`; `SimpleNamespace` lives in `types`. The output `Ran 1 test` and `FAILED (errors=1)` refers to loader `_FailedTest`, **not one failed assertion in the nine tests**. No successful test run of this suite has yet been reported.

Despite this pre-execution test gate failure, the operator invoked the D2 policy `--preview` and then `--apply-and-freeze --ack-local-commit`. The preview returned `D2_POLICY_PREVIEW_PASS__NO_FILES_WRITTEN`. The authorized local mutation returned:

- `D2_POLICY_FROZEN_LOCAL_ONLY`.
- Exactly one new local **ctl-only** Git policy commit: `3c69dd42497acadadc5d64e7b4abe5d412b309f5`; parent `ab34052b3cb2ece4452504ffa457ecf2d358891f`.
- Beads Task `d2ctl-g4q`. Original paired application baseline `32836ea5633230e50fb9d907dcdba83e357bcfc6`; SPEC SHA `8264746827bbb7300bf234023e6617324c78f37aecf524f2427a686925da8815`.
- Output file SHA-256:
  - `.gitignore`: `42e957af9d0cb01303304932893e705324025272f8d77d1a6a4c854912690627`
  - `.projectctl/config.yaml`: `c9178fa44b85bf122cecbe614b0c5bb112b7cf2869a8018e63c0303be48d53e2`
  - `projectctl.scope.yaml`: `cc97841324e26c49541db1b935c7e66c79e4d14f6a4a4b213c13b9bb6e155f9f`
  - `projectctl.verification.yaml`: `2b989d2b151f8bc4e3fa6044e09bbd4e421006fb64896ab7ad71dded74d985e4`.
- After freeze, `projectctl verification profile --project CTL --json` independently resolved human-managed `projectctl.verification.yaml`, profile digest `canonical-json-sha256-v1:3e8b2ad56b3306fc92ce5e98034e1e4766a496448d49810d2d29a9240b614cbc`, one **required** `python3 -B -m unittest discover -s tests -p 'test_*.py' -v` command, timeout 120 seconds.
- Diff policy protects frozen SPEC, POLICY, `tests/**`, `d2events/__init__.py`, `.projectctl/**`, all declared management files and default protected paths; `max_changed_paths=3` and symlinks prohibited.
- `expected_worker_changes` are exactly `d2events/cli.py`, `d2events/parse.py`, `d2events/report.py`.
- The user-provided output after `git log -1` and `git status --short` included no Git lines. The freeze script itself asserted a clean ctl worktree before returning, but **an additional independent Git state audit has not yet been run**.
- Freeze manifest location: `$HOME/.local/state/projectctl-dogfood-d2/observations/policy-freeze-v1/freeze-report.json`.

## Research-only repair and next gate

The faulty test import was corrected **only** on `research/advisory-skills-eval` to use `from types import SimpleNamespace` and `from unittest.mock import patch`. The frozen paired D2 application fixtures, Beads task, local ctl policy commit and official ProjectCTL runtime are untouched. No rewrite, reset, repeat `--apply-and-freeze`, or backdated assertion that the tests already passed.

A separate `experiments/dogfooding/d2/d2_post_freeze_audit.py` is prepared to verify frozen source SHA values, both local Git commit chains/clean states, exact four policy artifact SHAs, sole unclaimed Beads task, required three-file execution scope, model pin, resolved verification profile and digest, **26 frozen acceptance test definitions**, ignored application paths and absence of D2 run records. This is a read-only **local verification program**; its actual PASS is pending operator execution. After this and the now-fixed nine offline tests pass, proceed only to **official quota and runtime identity observation** (separate gate), not directly to worker dispatch.

**Scientific note:** The declared test-before-apply procedure was deviated from. Count the offline validation failure and premature policy apply as orchestration/procedural overhead in D2, not erase them from an eventual comparative report. A passing post-freeze test suite establishes current qualification, not retroactive compliance.

**State:** `D2_CTL_POLICY_COMMITTED / TEST_MODULE_IMPORT_FIXED_IN_RESEARCH / POST_FREEZE_AUDIT_PENDING / DIRECT_ARM_NOT_RUN / NO_INFERENCE`.
