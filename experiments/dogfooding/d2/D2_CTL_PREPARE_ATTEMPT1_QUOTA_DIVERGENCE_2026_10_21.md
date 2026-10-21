# D2 CTL Prepare Attempt 1 — quota vs Scheduler disagreement (2026-10-21)

**Decision:** `D2_CTL_PREPARE_ATTEMPT1_PRECLAIM_BLOCKED / NO_CLAIM / NO_WORKER / NO_RETRY`. This is a scheduler disagreement to diagnose, **not evidence of exhausted quota**.

## Operator-supplied selective historical JSON

```json
{
  "attempt": {
    "decision": "D2_CTL_PREPARE_PRECLAIM_BLOCKED__NO_RETRY",
    "reason": "Scheduler did not select sole D2 task",
    "run_id": null, "prepare_dispatched": false
  },
  "quota": {
    "mode": "normal", "stale": false,
    "effective": {"five_hour": 0.7200000000000001, "weekly": 0.87},
    "provider": "codex_app_server", "limit_id": "codex",
    "observed_at": "2026-10-21T08:13:53.465342Z"
  },
  "scheduler": {
    "quota_mode": "conservation", "selected_task_id": null,
    "candidates": [{
      "task_id": "d2ctl-g4q", "eligible": false,
      "reasons": ["quota_unknown"], "model": null
    }]
  }
}
```

The direct official quota read was healthy (remaining effective .72 five-hour and .87 weekly), well above the frozen admission minima .18/.08. The *second, independent* quota read inside `projectctl next` yielded an unknown/stale/partial-capacity quota state, so the scheduler refused to select the sole D2 task. Importantly, `conservation` here is **not** proof of insufficient quota: policy `unknown_quota_mode` defaults to `conservation`.

## Source analysis of the precise mismatch

- `projectctl quota` and `projectctl next` are separate CLI subprocesses; `projectctl/application/scheduling.py::collect_scheduling_bundle()` calls `read_current_quota` on its own. They do **not** share the first successful QuotaSnapshot.
- `projectctl/quota/resolver.py::read_current_quota` defaults to `fail_closed=True`. On `ProviderUnavailableError` or `QuotaError`, it quietly yields `unknown_quota_snapshot(account,provider)` with `observed_at=1970-01-01T00:00:00Z`, missing window remaining ratios, and null ordinary-usage authorization. This is a protective, non-fabricated unknown snapshot, not permission for work.
- `projectctl/quota/manager.py::state` marks stale/unknown-window results `conservation` because `QuotaPolicy.unknown_quota_mode=conservation` (see `projectctl/schemas/config.py`). `projectctl/scheduler/eligibility.py` assigns `quota_unknown` for an ineligible MEDIUM task when quota is stale or a window's effective ratio is `None`; `projectctl/scheduler/service.py` consequently emits no `selected_task_id` and no model recommendation.
- A transient Codex App Server start/initialize/rate-limit read failure during the second read would exactly explain the observations. This is the **leading hypothesis**, not yet proof: a second snapshot with missing windows or an otherwise stale observation can also make quota unknown. The saved scheduler decision contains a canonical `quota_snapshot_digest`, but not the full provider error. The first snapshot's `observed_at` alone does not prove the second snapshot's state.

## Non-invasive proof from *immutable* existing evidence

Using the isolated project's Python venv, load:
`$HOME/.local/state/projectctl-dogfood-d2/observations/ctl-prepare-attempt-1/quota-before-prepare.json` and `scheduler-before-prepare.json`.
Read `QuotaSnapshot.model_validate(quota["snapshot"])`; construct `unknown_quota_snapshot(original.account, original.provider)`; compare their `projectctl.core.digest.digest` values to `scheduler["quota_snapshot_digest"]`. Output only boolean equality and non-identifying times, NEVER the account field or entire raw quotas. **No new app-server requests are required**.

- `scheduler_equals_fallback_unknown=true` demonstrates Scheduler consumed the resolver's canonical synthetic unknown snapshot, strongly confirming the second read's fail-closed provider error path. It cannot tell which precise provider error occurred, since resolver masks the exception.
- If false, Scheduler used another snapshot. Missing windows/staleness remain hypotheses; do not claim transient provider failure definitively.
- `scheduler_equals_first_official=true` would instead indicate an unanticipated state/digest inconsistency requiring further study.

No changes to runtime/provider fallback or quota thresholds are authorized. Avoid a retry in the same preserved Attempt-1 evidence directory. The original one-time Prepare authorization led to one **outer** attempt that was blocked before dispatch; any *new* Prepare attempt must have a new observation identity and an explicit separate owner go-ahead after read-only diagnosis. Never issue `run start` until new independent approval.

**State:** `D2_SCHEDULER_QUOTA_SNAPSHOT_DIVERGENCE_DIAGNOSIS_PENDING / DIRECT_FROZEN / CTL_UNPREPARED / NO_PAID_CTL_WORKER`.
