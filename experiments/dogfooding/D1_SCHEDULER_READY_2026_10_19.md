# D1 quota admission — operator evidence, 2026-10-19

**Decision:** `D1_SCHEDULER_READY`, not yet `D1_WORKER_STARTED`.

The operator supplied a new official, high-confidence Codex App Server quota observation for the isolated ProjectCTL D1 fixture `ctl`:

- `observed_at=2026-10-19T10:09:30.332109Z`; `stale=false`; `ordinary_usage_allowed=true`; `selected_limit_id=codex`.
- Five-hour raw remaining `0.98`; five-hour effective after reserve `0.88`; reset `2026-10-19T15:02:03Z`.
- Weekly raw remaining `0.61`; weekly effective after reserve `0.51`; reset `2026-10-25T04:45:52Z`.
- Quota mode `normal`; no manual quota fabrication or policy relaxation.
- `projectctl next` selected exactly `d1ctl-lh4`; its eligibility is `true` with `reasons=[]` and model routing recommendation is profile `balanced`, reasoning `medium`.
- Existing isolated config pins the `balanced` actual model to `gpt-6-luna`, as confirmed by the earlier successful policy setup; the `next` payload only reports the profile, not the actual model name.
- The stored fixture policy/setup HEAD is `7388896be4a7ba46770ae76c7cd5480f0cd9e27b`; shared pre-setup source baseline is `da9379c70571c9366f5adfccecdfab148c814fc2`. Direct arm has not run.

**Interpretation:** The previous `quota_insufficient` Scheduler gate is closed at the observed time. The first D1 paid worker run remains unexecuted. A fresh quota check is still required immediately before run preparation/start because usage and age can change.

## Immediate manual next run

At the owner's chosen time, in the same isolated `PROJECTCTL_HOME` with the same single ready Beads task and no concurrent client/reclaimer: check Git cleanliness and zero remotes, source/spec hashes, `bd ready --json`, scope catalog and verifier; confirm that fresh `projectctl next --json` selects `d1ctl-lh4`. Then invoke `projectctl run prepare --strategy direct --project CTL --json` once. Confirm the returned plan has task `d1ctl-lh4`, `worker.actual_model=gpt-6-luna`, `worker.reasoning=medium`, `execution_policy` with `workspace_write`, `network=disabled`, `approval=deny_all`, strategy `direct`, base at setup HEAD, run `claimed`, and a worktree under isolated `PROJECTCTL_HOME`. Start that exact run promptly with `projectctl run start RUN_ID --project CTL --json` and retain the evidence; do not retry or auto-integrate on failure.

**Lease caveat:** ProjectCTL's Beads adapter neither renews the provider's expiring lease nor releases ownership atomically. Keep execution single-owner, do not use concurrent Beads clients or reclaimer, and report any lease/claim loss as a real compatibility defect. Do not silently heartbeat with a custom watchdog when measuring ProjectCTL's native control-plane behavior.

No product code or M6.0 state was changed in documenting this result.
