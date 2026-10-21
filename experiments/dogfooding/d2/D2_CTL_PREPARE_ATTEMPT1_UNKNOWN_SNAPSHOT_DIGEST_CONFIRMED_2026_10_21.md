# D2 CTL Attempt 1 — synthetic fallback quota proved by digest (2026-10-21)

**Decision:** `D2_CTL_SCHEDULER_FALLBACK_UNKNOWN_CONFIRMED / PREPARE_NOT_DISPATCHED / NO_CLAIM / NO_MODEL / PRESERVE_ATTEMPT1`.

## Operator-provided local, read-only digest comparison

The operator used the pinned isolated D0 Python venv and original retained artifacts under `$HOME/.local/state/projectctl-dogfood-d2/observations/ctl-prepare-attempt-1`. They loaded `quota-before-prepare.json` as a `QuotaSnapshot`, constructed the resolver's canonical `unknown_quota_snapshot(official.account, official.provider)`, and compared both using `projectctl.core.digest.digest` to the saved scheduler's `quota_snapshot_digest`.

The observed output was:

```json
{
  "scheduler_equals_first_official": false,
  "scheduler_equals_fallback_unknown": true,
  "first_quota_mode": "normal",
  "scheduler_quota_mode": "conservation",
  "scheduler_selected_task": null,
  "scheduler_evaluated_at": "2026-10-21T08:13:53.922083Z"
}
```

The first direct official quota observation was timestamped `2026-10-21T08:13:53.465342Z`, was fresh/non-stale, and had effective five-hour `0.72` and weekly `0.87`. The scheduler's second snapshot did **not** equal that first official observation. It matched *exactly* the synthetic fallback produced by `projectctl/quota/resolver.py::unknown_quota_snapshot` (including its epoch timestamp and unknown windows). In current ProjectCTL source, `read_current_quota(...,fail_closed=True)` returns this fallback when the provider raises `ProviderUnavailableError` or `QuotaError`.

Together, these facts **confirm the scheduler consumed the resolver-style synthetic unknown quota** rather than the preceding successful official snapshot. The consistent explanation is an independent second provider-read failure and a fail-closed substitution; **the precise exception is not preserved** and cannot be reconstructed from the digest alone. Do not claim a specific RPC timeout or malformed response without further evidence. The scheduler evaluation timestamp does not itself timestamp the failing RPC.

## Root-cause pathway from pinned source

1. `d2_ctl_prepare_once.py` reads `projectctl quota --json` and then `projectctl next --json`, both as separate subprocesses, saving distinct evidence files.
2. `projectctl/application/scheduling.py::collect_scheduling_bundle` calls `read_current_quota(config.quota.account)` again for the scheduler; it does not reuse the official snapshot from the prior quota CLI subprocess.
3. `projectctl/quota/resolver.py::read_current_quota` converts `ProviderUnavailableError` / `QuotaError` into an `unknown_quota_snapshot` when `fail_closed=True`.
4. `projectctl/quota/manager.py::QuotaManager.state` flags that observation stale with missing effective windows and uses `unknown_quota_mode=conservation` (frozen default).
5. `projectctl/scheduler/eligibility.py` rejects this medium task with reason `quota_unknown`; `projectctl/scheduler/service.py` selects no task, giving `selected_task_id=null`.
6. The outer D2 prepare's preserved `validate_admission` blocks **before** `projectctl run prepare`. Its reported `prepare_dispatched=false`, `prepare_exit_code=null` and `run_id=null` are consistent with the observed provenance; no worker inference, claim or integration was initiated.

## Interpretation and recommended non-mutating next phase

**Safety:** The unknown-quota fail-closed policy functioned as intended; it should not be bypassed or weakened.

**Reliability:** The two independent Codex App Server reads can disagree, and opaque fallback conversion makes transient outages hard to diagnose. Future *separate* research may add sanitized exception-class provenance and bounded refresh/reconciliation or a single authoritative quota snapshot with explicit freshness/identity checks. But changing the frozen D2 runtime or admission policy mid-pair is **not approved** and would impair comparability.

**Owner gate:** Preserve `ctl-prepare-attempt-1` as immutable evidence. No repeat of `--prepare --ack-claim` under the same evidence path; no user-approved paid `run start` exists. A future **Attempt 2** with a new evidence identity, unchanged frozen model/task/Scope/quotas, a single guarded prepare dispatch and explicit fresh owner permission is the conservative recovery path, ideally only after a targeted offline diagnostic qualification. Distinguish pre-dispatch evidence failure from any post-dispatch ambiguous task state. Do not reset Direct artifacts or change CTL fixture history.

**State:** `D2_SCHEDULER_SYNTHETIC_UNKNOWN_DIGEST_MATCH / SECOND_READ_FAILURE_CLASS_UNKNOWN / CTL_PREPARE_ATTEMPT1_TERMINAL_PRECLAIM / ATTEMPT2_UNAUTHORIZED`.
