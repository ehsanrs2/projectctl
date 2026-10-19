# D1-R3 — First successful ProjectCTL worker turn (2026-10-19)

**Status: WORKER_IMPLEMENTED / VERIFYING.** This is a successful worker execution in the **research-patched** ProjectCTL branch, not yet a verified implementation or integrated patch. Three earlier failed/blocked runs remain part of the dogfooding evidence.

## Operator-observed result

- Pulled `research/advisory-skills-eval` through research commit `4b5f06f`. All **24** local offline quota/resource, capability-identity, and Codex strict-structured-output regression tests passed.
- `D1_STRICT_SCHEMA_AND_RESEARCH_RUNTIME_PASS`, `THREE_PREVIOUS_D1_RUNS_PRESERVED; TASK_READY_AND_UNCLAIMED`, and `D1_FRESH_QUOTA_AND_SCHEDULER_PASS` all passed.
- At `2026-10-19T11:32:32Z`, `projectctl run prepare --strategy direct` succeeded with **`run-e467c1fa8f0f448b8497c9530c49b326`**, using the frozen `d1ctl-lh4` task and `gpt-6-luna`, reasoning `medium`.
- At `11:32:46Z`, `projectctl run start` began and finished `11:33:10Z`. The observed shell command wall time was **24 seconds**, covering start command overhead as well as the turn; it is not a per-token latency measurement.
- Reported `worker_status=implemented`, `run_status=verifying`, `checkpointed=false`, script `D1_R3_EXIT=0`. The harness intentionally ran **no** independent verification or integration.
- Evidence saved in isolated operator location `$HOME/.local/state/projectctl-dogfood-d1/observations/ctl-attempt-4/`. No measured model token usage was supplied; record usage as **unknown** pending available artifacts rather than inventing counts.
- Earlier attempt history: original source failed preclaim on raw UNKNOWN quota class; D1-R1 failed live capability version banner; D1-R2 reached Codex but received HTTP 400 strict-schema rejection. These are meaningful orchestration defects and overhead, not worker attempts that should be hidden.

## Verified vs pending

The worker's `implemented` status means only that a structured result was accepted and ProjectCTL transitioned to `verifying`. It does **not** establish that normalization behavior, protected-path constraints, or test expectations passed.

Next, check that the **only** worker-modified workspace path is `user_id.py`, the source/fixture baseline and project policy remain intact, and run `projectctl run verify RUN_ID --project CTL --json` exactly once. Source inspection confirms that a **passing** verify writes test logs and evidence, creates a candidate commit in its isolated run worktree, and transitions the run to `ready_to_integrate`. This is a deliberate Git-history mutation in the isolated **worker** worktree, not a merge or update to the `ctl` integration target. It must be logged. A failing verify transitions to `failed` or `blocked_policy` and must not be bypassed.

Do not run `projectctl run integrate`, `run auto`, or the direct Codex arm during this gate. Independently adjudicate the candidate code, exact diffs, test logs, protected file hashes, and recorded worker scope after verification. One paired run supports feasibility, not statistical claims about productivity or model quality.
