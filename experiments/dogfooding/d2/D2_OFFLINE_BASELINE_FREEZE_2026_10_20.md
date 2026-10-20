# D2 frozen paired-fixture baseline — operator evidence (2026-10-20)

**Observed:** `D2_OFFLINE_FIXTURES_FROZEN__NO_LIVE_RUN`, exit 0. D2 Beads, ProjectCTL adoption, worker task claims, or paid Codex turns **have not occurred**.

## Operator results

The operator fast-forwarded research branch through `cf1d1a1` and ran `bash -n experiments/dogfooding/d2/d2_prepare_offline.sh` plus the guarded `d2_prepare_offline.sh --create-new-fixtures`.

- Six of six builder qualification tests passed, including offline reproducibility in fresh temp Git repos and the expected failure of all 26 frozen acceptance tests on explicit unimplemented stubs; runtime for builder tests **0.187 seconds**.
- New local, independent, remote-free D2 repositories:
  `$HOME/.local/state/projectctl-dogfood-d2/fixtures/ctl`
  `$HOME/.local/state/projectctl-dogfood-d2/fixtures/direct`
- Matching Git baseline **`32836ea5633230e50fb9d907dcdba83e357bcfc6`**.
- Same `SPEC.md` SHA-256 **`8264746827bbb7300bf234023e6617324c78f37aecf524f2427a686925da8815`**.
- Same `POLICY.md` SHA-256 **`b2c4beb1ecb5947d8c10aa4c56ddf996ba7e361a5fb080299985c1a2d24bc203`**.
- Same protected tests-tree SHA-256 **`7fa3f486dfa9d54aa77f606b990e976c41f3c1608b630ec8f46521dd55c636c5`**.
- **11** files match and both fixture Git working trees were clean in the freeze check. No Beads state, ProjectCTL project metadata, model calls, SDK probes, or direct-arm changes observed at this stage.
- Evidence: `$HOME/.local/state/projectctl-dogfood-d2/observations/offline-setup-v1/`, including frozen `baseline-manifest.json`.

## Scope and next action

D2 is a multi-file JSONL activity reporter requiring only `d2events/parse.py`, `d2events/report.py`, and `d2events/cli.py` edits and passing 26 frozen tests. Both arms will use `gpt-6-luna` / medium subject to fresh actual runtime validation. Two source baselines are now identical and immutable; a later ProjectCTL ctl-only setup commit will legitimately make ctl HEAD differ. Preserve base SHA as an ancestor and do not copy solutions, commits, Beads state, or ProjectCTL state between arms.

The **next permitted** manual action is only one local `bd init` and one `bd create` inside D2 ctl, using `experiments/dogfooding/d2/d2_beads_setup_manual.sh --init-local-task`. The tool checks frozen source hashes, ignores D1, verifies the matching task description and sole unassigned `open` task, and captures any Beads-related `.gitignore` changes for review. It explicitly avoids a Git commit or ProjectCTL initialization. Its behavior is pending operator execution; a source audit is not an execution result.

After reviewing that output, use a separate gate to adopt only the ctl fixture into its own `PROJECTCTL_HOME`, write a required scope catalog with exactly the three allowed write paths, pin a deterministic independent unittest profile, and track human-managed fixture policy changes separately from application changes. No preparation, worker execution, retries or publication until those gates and fresh quota checks pass. No attempt under D2 is authorized to hotfix during a paired experiment.

**Gate state:** `D2_BASELINE_FROZEN / BEADS_AUTHORITY_NOT_INITIALIZED / INFERENCE_NOT_STARTED`. This is a new paired experiment, not a repeat of D1.
