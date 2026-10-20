# D2 ProjectCTL adoption preview qualified (2026-10-20)

**Observed result:** `D2_PREVIEW_PASS / PREVIEW_ONLY__NO_GIT_COMMIT_NO_PROJECTCTL_INIT`. The operator has NOT run the mutation-bearing `--adopt --ack-local-git-commit` path, and no ProjectCTL worker, claim, Codex/model turn, new metadata commit, or D2 `direct` arm has run.

The user fast-forwarded `research/advisory-skills-eval` to `9db89cc6aacaae01c5d5b8813ec751a6b9288bf3`, ran all 21 regression tests in `experiments.dogfooding.d2.test_gitignore_review` (21/21 pass in 0.005 s), passed Bash syntax check, and ran the guarded read-only D2 ProjectCTL adoption preview.

## Preview evidence

- `D2_BEADS_GITIGNORE_REVIEW_PASS`.
- Recorded Beads 1.3.1 added rules exactly match the immutable setup snapshot: `.dolt/`, `*.db`, `.beads-credential-key`, `.beads/proxieddb/`, `*.gate.lock*`; the original `__pycache__/` and `*.py[cod]` remain intact.
- `snapshot_exact_match=true`, `original_tracked_lines_preserved=true`.
- `root_beads_gate_lock_observed=true`, and validation of the exact `.beads.gate.lock` root path passed.
- `ignored_application_paths_checked=true`; no unrelated ignored application files reported. The broad patterns `*.db` and `*.gate.lock*` remain a documented pre-worker and post-worker audit concern; preview acceptance does NOT waive the later audit.
- `D2_CANONICAL_TASK_OPEN_UNCLAIMED` and `D2_SOLE_TASK_READY`; canonical Beads task `d2ctl-g4q` remains sole ready task.
- The only tracked working-tree change printed is ` M .gitignore`, with seven added lines consisting of an empty separator, a Beads comment and the five rules above.
- Warnings from `bd`: JSON output format will change in 2.0, and `beads.role not configured`; neither prevented this preview. Do not unilaterally change system-wide Git config.
- Script printed `PREVIEW_ONLY__NO_GIT_COMMIT_NO_PROJECTCTL_INIT`.

## Allowed next operator action

The exact script on current research head remains `experiments/dogfooding/d2/d2_adopt_projectctl_manual.sh`. It repeats all guards, then performs one **local** commit of reviewed `.gitignore` inside D2 `ctl` only, calls `projectctl inspect`, initializes that brownfield fixture with local Beads and local code transport/delivery, and checks the Beads task and direct baseline remained unchanged. Command (explicit local commit acknowledgement):

```bash
cd /home/ai/project/My/projectctl-advisory-lab
bash experiments/dogfooding/d2/d2_adopt_projectctl_manual.sh --adopt --ack-local-git-commit
```

Expected successful markers include `D2_PROJECTCTL_INSPECT_PASS`, `D2_PROJECTCTL_INITIALIZED_LOCAL_ONLY`, `D2_TASK_UNCLAIMED_AFTER_ADOPTION`, `D2_PROJECTCTL_ADOPTED__SCOPE_AND_VERIFICATION_POLICY_PENDING`, and `D2_ADOPTION_EXIT=0`. The actual future result is **not yet observed**.

If the script stops after a Git metadata commit but before initialization, preserve `$HOME/.local/state/projectctl-dogfood-d2/observations/projectctl-adoption-v1/` and inspect instead of rerunning; the preconditions intentionally prevent treating a partial run as pristine. No permission for paid Codex invocation, production promotion, or hotfix during paired execution is implied.

## Scientific state

`D2_BEADS_PREVIEW_PASS / ADOPTION_PENDING / PROJECTCTL_SCOPE_AND_VERIFICATION_NOT_FROZEN / INFERENCE_NOT_STARTED`.

Frozen D2 application baseline before ctl metadata setup: `32836ea5633230e50fb9d907dcdba83e357bcfc6`. Frozen SPEC SHA-256: `8264746827bbb7300bf234023e6617324c78f37aecf524f2427a686925da8815`. Protected 26 acceptance tests remain unchanged in both fixtures.
