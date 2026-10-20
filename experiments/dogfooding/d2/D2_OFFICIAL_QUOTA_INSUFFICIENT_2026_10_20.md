# D2 official Codex quota observation — insufficient at initial snapshot (2026-10-20)

## Decision and immutable operator evidence

**Decision at observation:** `D2_OFFICIAL_QUOTA_OBSERVED__INFERENCE_NO_GO_QUOTA_INSUFFICIENT`. This is a real fresh provider observation, not the earlier `quota_unknown` failure. No D2 model inference, ProjectCTL run prepare/start, direct CLI coding turn, Beads claim, or fixture code change was reported. The configured official provider is not a waiver of resource admission.

The operator pulled research branch `00ef8f6..6090356`, configured the isolated environment:

- `PROJECTCTL_HOME=$HOME/.local/state/projectctl-dogfood-d2/ctl-home`
- `CTL=$HOME/.local/state/projectctl-dogfood-d2/fixtures/ctl`
- task `d2ctl-g4q`, unchanged from the independently verified `D2_POST_FREEZE_READ_ONLY_PASS`.
- `projectctl quota provider --project CTL --json` initially reported `provider=manual`, `account=openai-default`.
- The operator explicitly switched **only this isolated account-level control DB's provider selection** with `projectctl quota provider --project CTL --set codex_app_server --json`. It reported `provider=codex_app_server`. No manual quota values were inserted.

`projectctl quota --project CTL --json` used the authenticated official Codex App Server bucket:

| Field | Officially observed |
|---|---|
| observed_at | `2026-10-20T11:08:38.574610Z` |
| provider, confidence | `codex_app_server`, `high` |
| selected_limit_id / available_limit_ids | `codex` / `[codex]` |
| stale / ordinary_usage_allowed | `false` / `true` |
| five-hour remaining ratio | `0.06999999999999995` (approximately 7%) |
| five-hour reset | `2026-10-20T11:34:16Z` |
| weekly remaining ratio | `0.85` (85%) |
| weekly reset | `2026-10-27T06:34:16Z` |
| five-hour effective ratio | `0.0` |
| weekly effective ratio | `0.75` |
| quota mode | `conservation` |

`projectctl next --project CTL --json` evaluated at `2026-10-20T11:08:38.889733Z`, `candidate.task_id=d2ctl-g4q`, `eligible=false`, reason **`quota_insufficient`**, `selected_task_id=null`. Config digest stayed `canonical-json-sha256-v1:15876f61956e8f88bcf44d1baa563cd65702caf546b879b4aefbcb8daa416351`. Quota snapshot digest was `canonical-json-sha256-v1:a4d3916acd8696d2ac93dde144461549dc5e732ca022d432855170e530806e79`.

Source-qualified ProjectCTL policy: `QuotaManager._effective` subtracts the configured reserve from raw quota, clipping at zero. D2 default `resource_requirements.medium` requires effective five-hour >=0.18 and weekly >=0.08. With a 0.10 five-hour reserve, the raw five-hour balance must be at least approximately 0.28 for a MEDIUM admission *if no other gate fails*. The 0.07 observed balance fails the five-hour gate; weekly effective 0.75 passes its threshold. Do not demote the task resource class, write manual quota, lower reserve, assert quota refilled at reset, or run `run prepare` while no task is selected.

## Next observation, not an execution authorization

After the observed five-hour reset at `2026-10-20T11:34:16Z` (or at a later operator-chosen time), re-observe **fresh** quota and Scheduler once. The previous observation is a historical snapshot and cannot authorize a later coding run. Use the exact D2-specific state root and CLI:

```bash
cd /home/ai/project/My/projectctl-advisory-lab
VENV="$HOME/.local/share/projectctl-dogfood-d0/venv"
CTL="$HOME/.local/state/projectctl-dogfood-d2/fixtures/ctl"
export PATH="$VENV/bin:$PATH"
export PROJECTCTL_HOME="$HOME/.local/state/projectctl-dogfood-d2/ctl-home"
export BD_ACTOR=d2-dogfood-owner BD_DISABLE_METRICS=1 DOLT_DISABLE_EVENT_FLUSH=1 DO_NOT_TRACK=1
"$VENV/bin/projectctl" quota --project "$CTL" --json &&
"$VENV/bin/projectctl" next --project "$CTL" --json
```

Pass only if the official canonical `codex` bucket is high-confidence, source `official`, fresh, ordinary usage allowed, and the *actual* scheduler selects exactly `d2ctl-g4q`. If insufficient, unknown, stale, unavailable or a different task is selected, retain the no-go decision. Reset time is **not** proof of an adequate new balance.

For the next *separate, non-inference* compatibility gate, the repo's `projectctl worker capabilities --provider codex --json` is version-only by default, and `projectctl worker strategy d2ctl-g4q --project CTL --provider codex --requested direct --json` checks strategy compatibility without dispatching a worker. Compare actual SDK/CLI versions, `gpt-6-luna`/medium model pin, sandbox workspace-write, approvals deny-all, network disabled and plugin/tool assumptions. The D2 plan specifies **direct arm first, then ProjectCTL** and no hotfix during a pair, but paid execution requires a distinct owner decision, a bounded evidence harness, and **another fresh quota/admission gate just before dispatch**.

No asynchronous monitor or auto-run is installed; no repeated quota polling is requested. Quota read may append an official operational observation in the isolated D2 SQLite and contact Codex App Server, but never starts a model task.

**State:** `D2_CTL_POLICY_VERIFIED / OFFICIAL_QUOTA_OBSERVED_INSUFFICIENT / DIRECT_ARM_PRISTINE / NO_WORKER`.
