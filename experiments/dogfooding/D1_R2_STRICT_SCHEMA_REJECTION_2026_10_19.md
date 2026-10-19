# D1-R2 — Codex strict structured-output schema rejection (2026-10-19)

**Observed result:** `PREPARE_PASS` followed by `START_FAILED` with provider HTTP 400 / `invalid_json_schema`. **No accepted or completed task-model turn**, and no verified output. Retain the actual run state and evidence.

## Operator evidence

- Isolated `ctl` fixture and direct-arm semantic baseline remain as previously frozen; no direct-arm run reported.
- Existing D1 quota/capability corrections passed all **15 offline tests**. The two previous runs were preserved and matched their known failures; previous blocked unassigned Beads issue was explicitly reopened under the recorded owner adjudication.
- Fresh official Codex quota and Scheduler admission passed; Beads issue `d1ctl-lh4` was the sole ready task.
- Third attempt `ctl-attempt-3` began `2026-10-19T11:05:48Z`. `projectctl run prepare --strategy direct` succeeded, new run ID **`run-b5785a14e0ab4961a970c43b0dc2b303`**. `run start` invoked `2026-10-19T11:05:58Z`.
- Provider returned HTTP **400**: `Invalid schema for response_format 'codex_output_schema': 'schema.required' is required to include every key in properties. Missing 'blockers'.` Status `invalid_request_error`, parameter `text.format.schema`, code `invalid_json_schema`. The harness exited 5; no retry, verification, integration, direct comparison or automatic rerun.
- Expected from the checked-in code (must confirm on operator host): `_run_worker_operation` catches WorkerError and transitions `RUNNING → FAILED`, reason `worker_error`; reconciliation releases the Beads claim and returns the Task to `open`. **Do not treat this expectation as an observed fact until read.**

## Root cause

`projectctl/workers/codex/adapter.py::_turn_kwargs` passed the unmodified `WorkerOutputPayload.model_json_schema()` to Codex. This Pydantic model has default-valued `blockers`, `requested_permissions`, `suggested_verification` lists. Its ordinary JSON Schema lists the optional/defaulted keys under `properties` but not under `required`. Strict Structured Outputs requires every object key to be required and `additionalProperties=false` on every object, including nested permission requests. The service rejected the request **before valid generation**.

## Scoped research branch fix

- `projectctl/workers/codex/adapter.py` now uses a dedicated strict wire-schema conversion `_strict_worker_output_schema()`. It derives from the canonical Pydantic payload model, requires **all** root and nested object properties, enforces `additionalProperties=false`, strips wire-incompatible defaults, and leaves model-side nonempty-string validation to Pydantic after parsing. The stored Pydantic contracts and WorkerResult status logic remain unchanged.
- Added `experiments/dogfooding/test_d1_codex_strict_output_schema.py` with nine offline regression tests: root/nested strictness; no default/minLength in wire; both start/resume request construction; Pydantic valid and invalid result behaviors; unknown keys rejected. Existing Codex adapter fake tests should also remain valid.
- These changes are **research-branch-only**. Host-side unit tests are pending; this is not yet evidence that the real Codex API accepts the patched schema.

## Next safe experiment step

1. Pull the research branch; ensure actual imported ProjectCTL and Codex adapter are the research files.
2. Execute new offline strict-schema tests and previous 15 regression tests. Check `projectctl runs`, `run show` and `bd show` for run `run-b5785a14e0ab4961a970c43b0dc2b303`. Require documented `failed/worker_error`, no active lease, and an unassigned **open** Task, before a new run. If any differ, do not force-reopen or mutate by guessing.
3. Reread official quota; require same scope, model, direct strategy, permissions and isolated fixture baselines. Use a **new** attempt directory `ctl-attempt-4` and start exactly one new run with no automatic retry/verification/integration.
4. Preserve all three earlier failed/needs_decision runs as legitimate ProjectCTL overhead and defects. Any successful patched run is a fourth attempt (**D1-R3**), not proof of original stock M6.0 correctness.

No artificial quota admission, schema loosening that permits extra fields, or new network permissions are authorized.
