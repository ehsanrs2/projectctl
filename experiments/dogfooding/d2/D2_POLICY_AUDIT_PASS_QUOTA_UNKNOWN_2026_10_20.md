# D2 post-freeze audit PASS — official quota unknown (2026-10-20)

## Observed operator evidence

**Decision:** `D2_POST_FREEZE_READ_ONLY_PASS / D2_QUOTA_UNKNOWN_NO_GO`. No ProjectCTL worker, direct Codex CLI turn, run prepare/start, task claim, or paid inference occurred during this operator step. This conclusion pertains only to the supplied observations.

The operator pulled research branch `e43c83a..00ef8f6` and reran the repaired nine `test_d2_freeze_policy` unit tests; **9/9 passed in 0.012 s**. They then ran `d2_post_freeze_audit` and received `D2_POST_FREEZE_READ_ONLY_PASS`. Its reported evidence:

- Source baseline: `32836ea5633230e50fb9d907dcdba83e357bcfc6`.
- Local ctl policy commit: `3c69dd42497acadadc5d64e7b4abe5d412b309f5`.
- Task `d2ctl-g4q` is `open_unclaimed`, sole ready; source and frozen management artifact digests match.
- Scope mode `required`, exactly `d2events/cli.py`, `d2events/parse.py`, `d2events/report.py` allowed writes; 26 frozen acceptance test definitions verified.
- Independent verification is `python3 -B -m unittest discover -s tests -p 'test_*.py' -v`, digest `canonical-json-sha256-v1:3e8b2ad56b3306fc92ce5e98034e1e4766a496448d49810d2d29a9240b614cbc`.
- CTL Git worktree clean, original `direct` untouched, ignored application artifacts not observed, no inference started.
- Policy and fixtures have **not** been amended after freeze.

## Fresh CLI observations: quota and scheduler

Operator then ran `projectctl quota --project CTL --json`:

- Provider `manual`, account `openai-default`, `observed_at=1970-01-01T00:00:00Z`, `stale=true`; both five-hour and weekly remaining/effective ratios are **null** with `unknown` confidence and source. `ordinary_usage_allowed=null`; `selected_limit_id=null`.
- Mode `conservation` due to unknown quota, not a measured insufficient live rate-limit balance.
- `projectctl next --project CTL --json` evaluated at `2026-10-20T11:00:19.444305Z`: only candidate `d2ctl-g4q`, `eligible=false`, reason `quota_unknown`; `selected_task_id=null`.
- Scheduler config digest `canonical-json-sha256-v1:15876f61956e8f88bcf44d1baa563cd65702caf546b879b4aefbcb8daa416351`.
- Scheduler quota snapshot digest `canonical-json-sha256-v1:b799bc428a2b8fc6c89bd53a6711f8be38eb8cac9ca84d5c2b7798b3b8bb2119`.

**No-go** for any `projectctl run prepare` or paid `run start`. No manual quota number, fake `observed_at`, reserve adjustment, task demotion or `--allow-stale-quota` policy bypass is justified.

## Narrow, proven D1 analogue: official Codex App Server quota provider

Prior D1 local-only experiment used `projectctl quota provider --project CTL --set codex_app_server`, after which `projectctl quota` read a high-confidence, fresh official rate-limit snapshot through the Codex App Server `account/rateLimits/read` JSON-RPC method. Present source inspection of `projectctl/cli/m04.py`, `projectctl/quota/resolver.py` and `projectctl/quota/codex_app_server.py` confirms:

1. `quota provider --set codex_app_server` writes the account-level provider selection only into the active isolated `PROJECTCTL_HOME/state.sqlite`; it does not create a ProjectCTL run or initiate a Codex completion.
2. `quota --project CTL --json` starts a temporary Codex App Server and requests only the authenticated account's rate limits; that operation can contact the provider and persist quota observations in the isolated SQLite, **but is not a model-task inference call**.
3. `next --project CTL --json` independently evaluates the fresh snapshot and eligibility; model choice remains unavailable unless quota and all other policy gates permit it.
4. Do not reuse D1 quota observations as D2 evidence: account limit and time can change. `codex_app_server` failure, stale/unknown data, wrong account, ambiguous rate-limit bucket, or explicit insufficient quota still blocks D2.

### Owner's next local, bounded observation

Use **only** D2 isolated environment and CTL, after fresh read-only policy audit already succeeded:

```bash
cd /home/ai/project/My/projectctl-advisory-lab
VENV="$HOME/.local/share/projectctl-dogfood-d0/venv"
CTL="$HOME/.local/state/projectctl-dogfood-d2/fixtures/ctl"
export PATH="$VENV/bin:$PATH"
export PROJECTCTL_HOME="$HOME/.local/state/projectctl-dogfood-d2/ctl-home"
export BD_ACTOR=d2-dogfood-owner BD_DISABLE_METRICS=1 DOLT_DISABLE_EVENT_FLUSH=1 DO_NOT_TRACK=1
"$VENV/bin/projectctl" quota provider --project "$CTL" --json
"$VENV/bin/projectctl" quota provider --project "$CTL" --set codex_app_server --json
"$VENV/bin/projectctl" quota --project "$CTL" --json
"$VENV/bin/projectctl" next --project "$CTL" --json
```

The explicit provider selection is a **small authorized local control-plane mutation**; the last two commands observe live official state and may append operational quota observations. No `run prepare`, `run auto`, `run start`, `quota set`, or direct CLI coding is part of this gate. If a command errors or returns unknown / stale / insufficient, stop and preserve the output rather than switching manually entered quota.

After an **actual** scheduler selection of exactly `d2ctl-g4q`, the remaining gates before **separately owner-approved paid work** are Codex SDK/CLI capability and model identity, exact sandbox/network/approval settings, pre-declared arms order and timing/usage evidence, and no concurrent Beads claim. D2 plan recommends `direct` then `ctl`, but do not execute either arm at the quota-observation stage.

**State:** `D2_POLICY_VERIFIED / OFFICIAL_QUOTA_NOT_OBSERVED / INFERENCE_NO_GO`.
