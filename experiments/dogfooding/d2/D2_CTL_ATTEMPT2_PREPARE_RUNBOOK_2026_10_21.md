# D2 Attempt-2 — Separate one-Prepare implementation, NOT authorized

**Operator result:** The previous manual offline qualification passed all 23 tests,
historical replay and CTL readiness, reporting
D2_ATTEMPT2_OFFLINE_QUALIFIED__PREPARE_NOT_AUTHORIZED.
That evidence is preserved in observations/ctl-attempt2-offline-qualification.

**New code:** d2_ctl_attempt2_prepare_once.py, its 10 synthetic safety tests
test_d2_ctl_attempt2_prepare_once.py, and this runbook.
It is a separately gated Attempt-2 entrypoint. Do not rerun the Attempt-1
entrypoint or modify historical/Direct evidence.

## New runner contract

- Preview requires a full explicit reviewed research SHA, pinned D0 Python and
  D2 env, successful unmodified offline qualification, and fresh read-only
  frozen-state readiness. Git/Beads read commands may touch operational caches.
- A later Prepare additionally requires two explicit acknowledgement arguments.
  Their existence in source does NOT imply owner authorization.
- Attempt-2 evidence uses only a new 0700 single-use directory at
  observations/ctl-prepare-attempt-2. Existing identity always stops.
- Read one fresh official quota and one independent Scheduler decision. The
  Scheduler must itself be normal and select only d2ctl-g4q; an unknown quota
  digest is rejected. Never reuse healthy first quota to override Scheduler.
- Verify fixed strategy/capabilities and recheck readiness and quota freshness.
  Make at most ONE inner projectctl run prepare dispatch; no retries.
- Mark intent durably before dispatch; after dispatch, timeouts and incomplete
  postflight demand manual reconciliation, not a second Prepare.
- Validate worktree, claim, task, RunStore, Direct immutability. No run start,
  Codex model call, verification, integration, publishing or runtime change.
- Failures record stage/type only, avoiding provider exception contents.

## Offline-only next action (allowed; no Prepare)

After synchronizing research/advisory-skills-eval, execute synthetic tests:

    cd /home/ai/project/My/projectctl-advisory-lab
    /home/ai/.local/share/projectctl-dogfood-d0/venv/bin/python -B -m unittest -v \
      experiments.dogfooding.d2.test_d2_ctl_attempt2_prepare_once

Then to inspect the updated frozen readiness safely:

    export PROJECTCTL_HOME="$HOME/.local/state/projectctl-dogfood-d2/ctl-home"
    export BD_ACTOR=d2-dogfood-owner BD_DISABLE_METRICS=1
    export DOLT_DISABLE_EVENT_FLUSH=1 DO_NOT_TRACK=1 PYTHONDONTWRITEBYTECODE=1
    export D2_REVIEWED_SHA='<exact-current-reviewed-40-character-commit>'
    /home/ai/.local/share/projectctl-dogfood-d0/venv/bin/python -B -m \
      experiments.dogfooding.d2.d2_ctl_attempt2_prepare_once \
      --preview --expected-head "$D2_REVIEWED_SHA"

Expected decision:
D2_ATTEMPT2_PREPARE_PREVIEW_PASS__NO_CLAIM_NO_INFERENCE.

Do not invoke --prepare; no owner authorization to create a run or claim was
given. If the 10 synthetic tests or Preview fail, preserve outputs and stop.

Next stage after separate owner approval: at most one manual Prepare, no Worker.
