# M5.2b — Implementation and Acceptance Plan

Status: **Slices A–D and regression fixes merged; local validation passed; SDK/CI and formal architecture sign-off pending.**
Baseline: `main@8dd6a53d8f71bac353c48803587ee9fa690d7e4c`
Required review: proposed `docs/decisions/ADR-038-general-execution-scope-governance.md`
Authority: `docs/PROJECT_STATE.yaml` is the *only* active-milestone authority; this document is a bounded design/acceptance plan, not a second roadmap.

## Verified touchpoints in current code

| Concern | Existing source | Change |
| --- | --- | --- |
| Legacy catalog model | `projectctl/schemas/parallel.py` | Preserve historical v1 parser; move generic model to `projectctl/schemas/execution_scope.py` |
| Single-read catalog loader | `projectctl/parallel/catalog.py` | Introduce a central canonical/legacy resolver under `projectctl/execution_scope/`; make parallel module consume it |
| Config evolution | `projectctl/schemas/config.py`, `projectctl/project/loader.py`, `projectctl/project/bootstrap.py` | Add v10/optional|required and in-memory v1–v9 upgrade; no silent config rewrite |
| Execution-input authority | `projectctl/application/execution_inputs.py`, `projectctl/schemas/execution_input.py` | Resolve exact authority, enforce policy, bind policy evidence/digest, retain v1 history |
| Run admission and worker | `projectctl/application/execution.py`, `projectctl/project/locking.py` | Gate required scope at prepare/start/resume; retain M5.2a lock order |
| Parallel planning / reapplication | `projectctl/parallel/{service,runtime}.py` | Use generic scope without weakening parallel proof |
| Independent checks | `projectctl/application/verification.py`, `projectctl/verification/diff.py` | Fail closed on required scope missing; protect both policy paths |
| Context discovery and review | `projectctl/context/{discovery,adoption}.py`, `projectctl/schemas/context_adoption.py`, `projectctl/cli/m50.py` | Target canonical scope; maintain historical review/receipt readers and exact digest approvals |
| CLI/migration | `projectctl/cli/`, `projectctl/project/ownership.py` | Add dry-run and explicit catalog conversion, durable mutation/recovery, human-managed ownership |
| Public schema | `projectctl/schema_export.py`, `projectctl/schemas/__init__.py` | Export new versions and preserve all old schema names |
| Documentation | `docs/PROJECTCTL_BLUEPRINT.md`, `README.md`, `docs/PROJECT_STATE.yaml` | Reflect completed behavior **only after** tests/acceptance |

## Bounded implementation order

### Slice A — Models, resolver, and v10 compatibility

1. Add generic scope models with strict schema kind/version, nonempty input/write, uniqueness and path validation.
2. Implement single-read snapshot resolver: canonical-only, legacy-only, missing, both, malformed, symlink. No hidden dual-file precedence.
3. Make project config v10 contain durable `scope_governance.mode` with new/legacy default `optional`, preserve historical ProjectConfig public exports.
4. Record stable canonical + legacy conversion semantics, including task-scope digest compatibility.
5. Tests: strict validation, old config v1–v9, no mutation during load, both-file conflict, invalid canonical, legacy conversion, symlink and path safety.

### Slice B — Execution and verification policy closure

1. Extend the execution-input runtime contract using explicit versioned parsing/hashing (no silent v1 reinterpretation).
2. Fail closed on `required` when no catalog/task scope, even on serial/manual/ad hoc pathways; reject any unreviewed explicit scope used as a policy bypass.
3. Keep required policy evidence pinned across prepare, worker start, checkpoint/resume, preclaim/afterclaim revalidation, verification and recovery.
4. Preserve serial `optional` behavior; all parallel modes require task scope.
5. Protect both scope files against worker writes, including indirect/symlink escape checks.
6. Tests: required fail before claim, optional serial remains supported, parallel optional still requires explicit scope, stale policy/digest, forbidden writes, worker-start/resume/recovery, historical v1 behavior.

### Slice C — Context workflow, migration, and crash safety

1. New M5 review/adoption targets only canonical scope; legacy-only requires explicit migration.
2. Preserve old schema readers and exact-path binding; old approvals cannot be replayed against the new file.
3. Provide `projectctl scope migrate` dry-run/apply with shared authority gate, no active runs, crash-journal state, deterministic before/after recovery and fail-closed ambiguous state.
4. Test interleavings with concurrent run preparation and reviewed adoption, and crash windows before/after canonical write and legacy retirement.
5. Tests: exact approval unchanged, review stale after migration, symlink/both-file refusal, recovery, read-only dry-run, no worker or uncommitted execution after mutation.

### Slice D — Closure and architecture review

1. Update public JSON schema registry (without generating a versioned schema mirror in Git), README and Blueprint; author final accepted ADR only after architectural approval.
2. Run schema export tests; relevant M4.1/M4.2/M5 tests; `pytest`; and `git diff --check` in a real local checkout.
3. Inspect changes to `ProjectConfig`, Run/ExecutionInput, review/approval, and protected-file rules; record residual risks and test evidence.
4. After passing local evidence, update `docs/PROJECT_STATE.yaml` to the actual next accepted milestone; never claim M5.2b complete before that gate.

## Acceptance matrix

| Scenario | Expected behavior |
| --- | --- |
| Legacy-only catalog + optional | Validated and usable via compatibility loader; no automatic migration |
| Canonical-only catalog | Accepted as sole human authority |
| Both files (even identical) | Fail closed; operator resolves |
| Neither file + optional + serial | Allowed under generic path/diff protections |
| Neither file + required + serial | Rejected before durable claim/worker admission |
| Missing task scope + optional + parallel | Rejected |
| Missing task scope + required + parallel | Rejected |
| Invalid / symlinked scope file | Rejected, never treated as absent |
| Required + valid task scope | Write boundary present in execution inputs and worker context; verified independently |
| Worker changes either scope authority file | Fails system-protected-path check |
| Task scope or governance mode changes after plan | No unchecked start/verification/recovery; stale execution evidence rejected |
| Review against legacy catalog | Require explicit migration and fresh canonical review |
| Prior v1 review/receipt | Parse and audit only; no reapproval path switching |
| Migration with active/paused/recovery-needing run | Fail closed |
| Crash during two-file migration | Deterministic recovery only for exact known states |
| CI runner never starts | Report unavailable, not pass |

## Implementation caveats found during inspection

- `projectctl/application/verification.py::_write_scope_violations` currently returns no violations when the manifest has no writes. Required-mode handling must be explicit.
- `projectctl/application/execution_inputs.py::_optional_scope` currently checks `projectctl.parallel.yaml` directly; this must be replaced with the shared resolver.
- `projectctl/context/adoption.py::_catalog_state` already has single-byte-read parsing from M5.2a. Preserve that guarantee.
- `projectctl/project/loader.py` upgrades v1–v8 in memory into v9; v10 must preserve existing behavior and schema exports.
- `projectctl/schemas/context_adoption.py` v1 artifacts encode the legacy path and `ParallelTaskScope`; these need historical readers, not replacement-in-place.
- `projectctl/verification/diff.py::SYSTEM_PROTECTED_PATHS` currently does **not** include either scope-policy filename; add both.
- `projectctl/project/ownership.py` likewise does not yet identify either policy path as human-managed.
- `execution-authority` admission/adoption serialization exists in M5.2a and must remain shared for migration and future ProjectCTL-controlled governance mutations.
- GitHub Actions credits were reported unavailable in the recent PR; no successful CI run is inferred.

## Release gates

- **Gate A:** Architecture accepts ADR-038 and the precise new/historical public-schema compatibility.
- **Gate B:** Verified model/resolver/config compatibility.
- **Gate C:** Verified execution policy and recovery fail-closed behavior.
- **Gate D:** Verified migration/adoption and deterministic crash handling.
- **Gate E:** Local test evidence, documentation consistency, and Post-M5.2 closure review.

This plan does not authorize production deployment or milestone promotion outside the accepted gates. M5.2b's merged implementation still requires the evidence recorded in `docs/architecture/M5_2B_CLOSURE_AUDIT.md`.
