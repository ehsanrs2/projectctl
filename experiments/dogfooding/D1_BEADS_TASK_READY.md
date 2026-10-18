# D1 local task authority initialization — operator evidence

**Date:** 2026-10-18. **State:** `D1_BEADS_TASK_READY`; ProjectCTL not initialized and no model/worker task yet.

## Supplied evidence

The owner ran the vetted, local-only Beads setup **inside the disposable `ctl` Git fixture only**, with `BD_ACTOR=d1-dogfood-owner`, telemetry disabled, and no remote.

- `bd init --non-interactive --skip-agents --skip-hooks --setup-exclude --prefix d1ctl` succeeded.
- Backend: embedded Dolt; database/prefix `d1ctl`. No Dolt remote configured, as intended for this purely local task authority.
- `bd create ... --json` succeeded, creating exactly one task `d1ctl-lh4`, status `open`, issue type `task`, priority `2`; task description matches the frozen specification (ASCII-only lowercasing, strip outer whitespace, keep internal whitespace, reject non-string and blank with `ValueError`, never edit `POLICY.md` or `test_user_id.py`).
- `bd ready --json` returned exactly one eligible task, `d1ctl-lh4`, with no dependencies or dependents.
- After setup, `git status --short` reported only `?? .gitignore`. `git rev-parse HEAD` remained `da9379c70571c9366f5adfccecdfab148c814fc2`.
- Beads added `.beads/`, `**/RECOVERY*.md`, `**/SESSION*.md` to the local `.git/info/exclude`; this is not committed/upstream. `bd` also created an untracked `.gitignore` whose contents have **not yet been supplied**. Preserve and inspect it rather than assuming its contents or using `--allow-dirty`.

## Next controlled setup

1. Inside `ctl`, show and review `.gitignore`. If its contents are expected Beads-generated ignore rules, stage **only** that file and make a disposable-local setup commit. Do not use `git add -A` or commit `.beads` Dolt operational data. Preserve original application baseline SHA separately.
2. Set `PROJECTCTL_HOME` to a new, unpopulated path under `$HOME/.local/state/projectctl-dogfood-d1/`; keep existing global ProjectCTL account state untouched.
3. Run `projectctl inspect CTL --json` then, only if classification is `existing_unmanaged` and task authority is unambiguous Beads, invoke `projectctl init CTL --non-interactive --yes --task-store beads --code-transport local --code-delivery local --json`.
4. Review ProjectCTL's newly generated local `.projectctl/` state and human-managed `docs/PROJECT_STATE.yaml` before preparing the canonical task scope, verification profile, model routing and quota snapshot. Do **not** invoke `run prepare/start/verify/integrate` yet.

This setup can create new disposable task/project metadata but no model calls. After init, recheck `bd ready --json`, Git status, no remotes and task identity before further mutations.

## Interpretations and limits

The `owner=d0-fixture@invalid.example` field shown in the Beads JSON is not proof that a worker has claimed the task: `status=open` and its appearance in `bd ready` establish readiness. Actual claim/assignee evidence must be checked at the later run preparation gate.

The existing ProjectCTL Beads Adapter has non-atomic release and no provider lease renewal. The proposed D1 trial is single-actor/no concurrent reclaimer, with owner checks and no live inference until independently reviewed policy/worker admission. These constraints do not establish production concurrency safety.

No source code, M6.0 artifacts, production Git remotes or real ProjectCTL task authority were changed by these reported commands.
