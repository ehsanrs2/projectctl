# D2 ProjectCTL adoption completed — operator evidence (2026-10-20)

**Observed decision:** `D2_PROJECTCTL_ADOPTED__SCOPE_AND_VERIFICATION_POLICY_PENDING`, `D2_ADOPTION_EXIT=0`. This is **ctl-only local project adoption**, not a worker run or inference request. The user manually ran `d2_adopt_projectctl_manual.sh --adopt --ack-local-git-commit` after a successful 21-test/preview gate.

## Verified operator output

- GitHub research branch was fast-forwarded `9db89cc..2fd49c0`; no ProjectCTL runtime file was modified in that pull.
- The exact five Beads-added ignore patterns matched the frozen setup snapshot; initial base rules were preserved; Beads root gate-lock audit passed; ignored application paths were checked.
- Sole ready canonical Beads Task `d2ctl-g4q` remained `open` and unclaimed, before and after ProjectCTL adoption.
- A **local** ctl-fixture metadata-only commit was created: **`ab34052b3cb2ece4452504ffa457ecf2d358891f`**, parent D2 application baseline `32836ea5633230e50fb9d907dcdba83e357bcfc6`. Git reported exactly **one file changed**, seven added `.gitignore` lines. This is NOT a commit to ProjectCTL main or the research branch.
- `D2_PROJECTCTL_INSPECT_PASS` confirmed the existing Beads repository was safe to adopt.
- `D2_PROJECTCTL_INITIALIZED_LOCAL_ONLY`: configuration resolved `task_store=beads`, `code_transport=local`, `code_delivery=local`, initial `scope_governance=optional` before the required freeze, and isolated PROJECTCTL_HOME under `$HOME/.local/state/projectctl-dogfood-d2/ctl-home`.
- Five files newly untracked in ctl (not committed):
  `.projectctl/adoption.yaml`, `.projectctl/config.yaml`, `.projectctl/state.sqlite`, `.projectctl/telemetry.sqlite`, `docs/PROJECT_STATE.yaml`.
- Direct D2 fixture still at the frozen application baseline with no reported control-plane setup or Git changes. No remote publication, ProjectCTL run prepare/start, Codex CLI, SDK inference or Beads claim.
- Local evidence: `$HOME/.local/state/projectctl-dogfood-d2/observations/projectctl-adoption-v1/`.
- `bd` warned `beads.role not configured`; adoption nevertheless exited successfully. Do not change global Git settings solely to silence the warning. No claim of role policy compliance is inferred from the warning.

## Prepared offline next gate

New research-only helper `experiments/dogfooding/d2/d2_freeze_policy.py` reproduces the *D1 proven policy-catalog shape* while pinning exactly **three** executable writable paths: `d2events/parse.py`, `d2events/report.py`, `d2events/cli.py`. The task authority stays `d2ctl-g4q`, scope becomes `required`, all model profile entries route `gpt-6-luna` / `medium`, verification uses one required `python3 -B -m unittest discover -s tests -p 'test_*.py' -v` command (26 frozen test cases; 120 s bound). The diff policy protects frozen SPEC, POLICY, test tree, `d2events/__init__.py`, `.gitignore`, management YAML paths, defaults, and sets `max_changed_paths=3` with symlink writes disallowed.

The policy file helper has a pure preview and an explicit `--apply-and-freeze --ack-local-commit` path. The latter creates `projectctl.scope.yaml` and `projectctl.verification.yaml`, updates isolated ignored `.projectctl/config.yaml` and tracked `.gitignore` to ignore local operational metadata, then *locally* commits exactly four human-managed control files (`.gitignore`, `docs/PROJECT_STATE.yaml`, scope and verification). It checks fixed D2 hashes, Beads Task state, direct-fixture untouched, exact post-adoption Git status, current Beads snapshot and ignored-path inventory before making any changes. No worker, claim, quota or paid inference action is part of this step.

Nine new unit tests of this helper cover the exact input/output contract, ProjectCTL catalog schema validation, preview non-mutating behavior, acknowledgement, correct Git porcelain whitespace, and fail-closed path guards. **These tests have been authored but not yet run on the operator's pinned local environment.**

## Execution boundary

Operator is asked first to fast-forward research, run 9 offline tests and run policy preview. If all pass with expected SHA and no unexpected status, one acknowledged `--apply-and-freeze` is permitted. Once a successful local policy commit exists, don't rerun that command; validate the resolved independent verification profile and normal Git status. Any errors after a partial write/commit require evidence review rather than rebuilding or resetting.

**State:** `D2_CTL_ADOPTED / REQUIRED_POLICY_PENDING / DIRECT_PRISTINE / INFERENCE_NOT_STARTED`. No production promotion, quota override, paid Codex call or direct-arm execution has been authorized.
