# D2 CTL first Prepare preclaim admission blocked — 2026-10-21

**Observed operator decision:** `D2_CTL_PREPARE_PRECLAIM_BLOCKED__NO_RETRY`. This is a **scheduler/admission stop before** calling `projectctl run prepare` and without a ProjectCTL worker start, Beads claim, run ID, or inference turn. It is not evidence that the frozen CTL coding task failed.

## Evidence provided by operator

- Pulled research from `38e6305` to `625b101`; all **15/15 synthetic offline tests passed**, followed by the successful `D2_CTL_PREPARE_PREVIEW_PASS__NO_CLAIM_NO_INFERENCE` (frozen policy HEAD `3c69dd42497acadadc5d64e7b4abe5d412b309f5`, Task `d2ctl-g4q`, integration target `main`).
- One authorized call of the *outer* `d2_ctl_prepare_once --prepare --ack-claim` was attempted. The runner returned:
  ```json
  {
    "decision": "D2_CTL_PREPARE_PRECLAIM_BLOCKED__NO_RETRY",
    "evidence_path": "/home/ai/.local/state/projectctl-dogfood-d2/observations/ctl-prepare-attempt-1",
    "paid_worker_started": false,
    "prepare_exit_code": null,
    "prepare_wall_monotonic_seconds": null,
    "reason": "Scheduler did not select sole D2 task",
    "run_id": null
  }
  ```
- Overall shell exit `D2_CTL_PREPARE_EXIT=2`. Preserve the created evidence directory; do not delete/reset or rerun this first attempt.

## Where this failure happens

Source inspection of `d2_ctl_prepare_once.py` shows it obtains **read-only** outputs from `projectctl quota --project CTL --json` and `projectctl next --project CTL --json`, writes those originals to `quota-before-prepare.json` and `scheduler-before-prepare.json`, then calls `validate_admission(q, n, now=UTC)`. The observed message comes from its pre-dispatch test that requires both:
- `next_decision.selected_task_id == "d2ctl-g4q"`, and
- `next_decision.quota_mode == "normal"`.

The same message is used for **either** discrepancy; actual saved scheduler JSON has not yet been shared, so the cause is **unresolved** (quota-mode degradation, no selected task, or another scheduler state). Since the output has no `prepare_dispatch_utc` or `prepare_exit_code`, the inner `projectctl run prepare` was **not dispatched**. No claim/worktree creation or paid model activity is indicated by the observed evidence.

Static scheduler source review: `projectctl/scheduler/service.py` builds candidate eligibility and chooses a task only when at least one is eligible. `projectctl/scheduler/eligibility.py` can report `quota_unknown`, `quota_insufficient`, `not_ready`, `blocked`, or `human_decision` among reasons. It would be unsound to infer which reason occurred without inspecting the stored `next` result.

## Diagnostic next step — read preserved snapshots only

On the owner's workstation, parse the existing `$HOME/.local/state/projectctl-dogfood-d2/observations/ctl-prepare-attempt-1/{prepare-summary.json,quota-before-prepare.json,scheduler-before-prepare.json}`. Show minimal safe fields: quota mode/stale/effective, provider/limit ID/sample timestamp, scheduler quota_mode/selected_task_id/candidates task_id/eligibility reasons/model and schedule digest, plus presence of `prepare_dispatch_utc` and `prepare.stdout.json`. Do not publish raw quota snapshots, logs, credentials, worker events or raw source. Avoid another `projectctl quota`, `projectctl next`, `--prepare --ack-claim` or `run start` until the saved mismatch is adjudicated.

An eventual new Prepare attempt must have a **fresh separately identified observation directory and explicit owner decision**, since the first outer attempt produced an immutable no-retry record. Never repurpose `ctl-prepare-attempt-1` or silently bypass a quota/selection check. If quota is simply insufficient, allow recovery without changing frozen criteria. If the scheduler is misconfigured or frozen policy needs a hotfix, record it as a design/gate defect and decide how to maintain paired comparability before modification.

**State:** `D2_DIRECT_ACCEPTED / CTL_PREPARE_ATTEMPT_1_PRECLAIM_BLOCKED / NO_CLAIM / NO_CTL_MODEL_TURN / SNAPSHOT_DIAGNOSTIC_PENDING`.
