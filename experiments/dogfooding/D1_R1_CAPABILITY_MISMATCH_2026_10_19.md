# D1-R1 second attempt — live capability mismatch at worker start

**2026-10-19 (UTC). State:** `PREPARE_PASS`; `START_BLOCKED_CAPABILITY_CHANGED`; **no worker task turn dispatched** (the source fails before context assembly and `adapter.start`). Original stock-runtime preclaim failure remains preserved separately.

## Operator evidence

- Ran an explicitly paid-authorized, single-attempt Bash harness `d1_r1_manual_run.sh --execute --ack-paid` in a child shell, with separate evidence directory `$HOME/.local/state/projectctl-dogfood-d1/observations/ctl-attempt-2`.
- Research patched runtime was active; the previous failed run `run-88361fe2431e4e299a0f4b9c506c50fa` remained preserved as `failed/quota_exhausted`.
- `bd ready` had exactly one `d1ctl-lh4` with no assignee, and fresh official quota plus Scheduler admission passed.
- `projectctl run prepare --strategy direct` started `2026-10-19T10:44:30Z`, succeeded, claimed task and created isolated worktree.
- New run: `run-10e606ca532c403487131ea092db232c`. `PREPARE_PASS` logged; `projectctl run start` called `2026-10-19T10:44:37Z`, failed with exactly `Worker capability surface changed between prepare and start.`. Harness exited 5; no automatic retry, verification or integration.
- The live capability probe **may start the Codex SDK runtime** but this error is raised before the code calls `adapter.start(...)`; no evidence of an actual task turn.

## Source inspection

- `projectctl/application/execution.py` prepares a `version_capabilities()` snapshot and saves `.projectctl/runs/RUN_ID/worker-capabilities.json`.
- At `start`, the code calls `adapter.probe()`, calculates `effective_capability_digest(live_capabilities)`, and if different writes `.projectctl/runs/RUN_ID/worker-capabilities-live.json`, transitions the run to `needs_decision/capability_changed`, and raises the observed error.
- `CodexWorkerAdapter.probe()` starts with the version-only base but replaces `sdk_version` with its imported module's `__version__` or `unknown`, and may replace `runtime_version` with the SDK metadata's reported runtime version. The digest deliberately ignores probe kind, observation time and notes but **retains** versions and capability support values.
- Therefore an SDK or runtime identity disagreement is a plausible cause, **not confirmed** without inspecting the saved prepare/live JSON snapshots. Do not weaken capability checks, silently rebind the existing run, or auto-resume.

## Read-only next evidence

With the isolated `PROJECTCTL_HOME` and no worker calls: run `projectctl run show RUN_ID --project CTL --json`, `bd -C CTL show d1ctl-lh4 --json`, and compare the **semantic** (timestamp/notes-stripped) fields of `worker-capabilities.json` and `worker-capabilities-live.json`. Capture fields and exact values that differ (especially `runtime.sdk_version` and `runtime.runtime_version`); do not assume one.

Check whether `reconcile_terminal_task` changed Beads to `blocked` or released its claim, and whether the run really reached `needs_decision/capability_changed`. The tool's error text alone does not establish durable provider ownership after the failure. Treat repair/release as a distinct, evidence-backed operation after diagnosis.

**Next engineering action:** Once actual diffs are known, make a narrow research-branch correction and synthetic regression tests proving that metadata-only/provenance-label variance is handled *without* ignoring real capability or compatible runtime changes. Any further run is a new, explicitly labeled D1 research attempt. Preserve attempt-2 artifacts.

**Production boundaries:** no M6.0/main changes, no remote changes, no direct-arm work, no manual quota fabrication.
