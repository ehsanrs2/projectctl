# D1 policy and official quota gate — operator evidence (2026-10-19)

**Decision:** `D1_POLICY_PREPARATION_PASS`; `D1_INFERENCE_NO_GO_QUOTA_INSUFFICIENT`. No ProjectCTL worker or direct Codex task executed. Research-only documentation; production M6.0 unaffected.

## Validated fixture policy

Operator fast-forwarded research branch to `4815c54`, ran **8/8 D1 policy-preparation unit tests successfully**, then obtained:
- `PREVIEW_ONLY` followed by one `POLICY_FILES_WRITTEN` for task `d1ctl-lh4`. Four generated/updated paths are `.gitignore`, ignored local `.projectctl/config.yaml`, `projectctl.scope.yaml`, `projectctl.verification.yaml`.
- The independently read verification profile came from `projectctl.verification.yaml` and executed `python3 -B -m unittest -v test_user_id.py`, required, timeout 60s; diff protection includes `SPEC.md`, `POLICY.md`, `test_user_id.py`, `.gitignore` and default ProjectCTL protected paths, including `.projectctl/**`.
- The operator staged exactly four human-managed fixture files and committed them **only in the external disposable `ctl` repository**. `D1_POLICY_PREPARATION_PASS` and HEAD `7388896be4a7ba46770ae76c7cd5480f0cd9e27b`. Script's final Git cleanliness check returned success. The original shared application base remains `da9379c70571c9366f5adfccecdfab148c814fc2`; task ID `d1ctl-lh4`.
- The `direct` arm has not been reported changed or run.

## Official quota snapshot, no guessed values

The owner enabled `codex_app_server` in the **isolated** D1 account's ProjectCTL home using `projectctl quota provider --project CTL --set codex_app_server`. This was followed by official, high-confidence Codex quota data:
- Observed at `2026-10-19T07:15:15.052487Z`; `stale=false`, `ordinary_usage_allowed=true`, `selected_limit_id=codex`.
- Five-hour **remaining ratio 0.18**, five-hour reset `2026-10-19T09:55:21Z`.
- Weekly **remaining ratio 0.65**, weekly reset `2026-10-25T04:45:52Z`.
- Policy reserves 0.10 in each window: five-hour **effective 0.08**; weekly **effective 0.55**; mode `conservation`.
- `projectctl next` found `d1ctl-lh4` as the only candidate but returned `eligible=false`, reason `quota_insufficient`, and `selected_task_id=null`.

## Why admission failed

At this source revision, Beads normalized `issue_type=task` to `TaskType.TASK` and `resource_class=UNKNOWN`. `scheduler/resource.py` maps generic tasks to **MEDIUM** (unless explicitly classed otherwise); `QuotaManager.eligible_for_resource` requires effective five-hour ≥ 0.18 and weekly ≥ 0.08 for MEDIUM. With the default five-hour reserve 0.10, raw five-hour quota would need to be **at least ~0.28**. Current observed five-hour raw 0.18 yields effective 0.08 and is insufficient. Do not falsify manual quota or demote task to a cheaper class solely to bypass the gate.

## Practical continuation

At or after the snapshot's five-hour reset `2026-10-19T09:55:21Z`, the operator may rerun, from the disposable fixture with the *same* isolated PROJECTCTL_HOME:

```bash
CTL="$HOME/.local/state/projectctl-dogfood-d1/fixtures/ctl"
D0_VENV="$HOME/.local/share/projectctl-dogfood-d0/venv"
export PATH="$D0_VENV/bin:$PATH"
export PROJECTCTL_HOME="$HOME/.local/state/projectctl-dogfood-d1/ctl-home"
export BD_ACTOR=d1-dogfood-owner BD_DISABLE_METRICS=1 DOLT_DISABLE_EVENT_FLUSH=1 DO_NOT_TRACK=1
"$D0_VENV/bin/projectctl" quota --project "$CTL" --json
"$D0_VENV/bin/projectctl" next --project "$CTL" --json
```

Proceed toward `run prepare` only after a fresh quota snapshot admits the unchanged canonical task; ensure clean/remote-free repo, correct policy hashes, and single actor/no competing Beads claimant. `run prepare` claims a task while Beads provider leases can expire; avoid long delay between `prepare` and a separately intentional worker execution. Do not call `run auto`, change M6.0, or trigger a direct Codex comparison before admission.

**Evaluation meaning:** D1 will test *comparative product utility* rather than just model capabilities. The paired arms remain pending; no quality/time/cost comparison is possible yet.
