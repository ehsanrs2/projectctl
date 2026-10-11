# ADR-038: General Execution Scope Authority and Explicit Governance

Status: Proposed — M5.2b design; **not yet accepted or implemented**
Base reviewed: `main@8dd6a53d8f71bac353c48803587ee9fa690d7e4c`
Supersedes: none. Extends ADR-031, ADR-033, ADR-035, ADR-036, and ADR-037.

## Context

Post-M5 review accepted the human-review and execution-input authority boundaries, subject to M5.2a and M5.2b closure. M5.2a is merged. Currently `projectctl.parallel.yaml` / `ParallelScopeCatalog v1` is also consumed by ordinary serial execution (`projectctl/application/execution_inputs.py`), M5 discovery and adoption (`projectctl/context/{discovery,adoption}.py`), and independent verification (`projectctl/application/verification.py`). The serial path silently allows a missing task scope; the parallel path rejects it. The distinction must become explicit project policy without breaking existing projects.

This ADR proposes a design for implementation review. This file does not itself authorize a scope mutation, version migration, or worker execution.

## Proposed decisions

### 1. Exactly one human-managed scope authority

- Canonical source: `projectctl.scope.yaml`, schema kind `projectctl.execution_scope_catalog`, schema version 1, public models `ExecutionScopeCatalog`, `ExecutionTaskScope`, and `ExecutionPathScope`. The path kind is `exact | tree`. Each task has nonempty inputs/writes, optional resources, uniqueness constraints, and a task key equal to `task_id`.
- Read-only legacy compatibility: `projectctl.parallel.yaml`, schema kind `projectctl.parallel_scope_catalog`, version 1, continues to deserialize through its existing historical model.
- Resolver states: canonical only -> canonical; legacy only -> validated legacy converted to generic *in memory*; neither -> absent; both -> **fail closed, even if semantically identical**. Paths that are symlinks, malformed, or invalid must fail closed rather than being treated as absent.
- No automatic write, fallback from invalid canonical to legacy, or implicit merging. One shared loader/resolver supplies serial, parallel, discovery, and review paths.
- The `parallel` execution planner consumes the generic scope. The historical ParallelPlan and ParallelScopeCatalog artifacts remain readable and are not renamed retroactively.
- Preserve the task-level semantic scope digest across conversion when model serialization is equivalent; otherwise explicitly invalidate/rebuild pending planning evidence. Raw catalog byte digests and semantic task-scope digests are different contracts.

### 2. Explicit project scope-governance mode

- `ProjectConfig v10` introduces `scope_governance.mode: optional | required`; new projects persist `optional` unless the operator explicitly chooses `required`.
- Existing persisted ProjectConfig v1–v9 is validated by its original version and upgraded *in memory* to v10 with `optional`. Normal reads never rewrite legacy config. The explicit policy-change path persists v10.
- `optional`: missing catalog/task declaration is permitted for **serial** runs, with the existing generic protected-path/diff-policy checks; malformed or ambiguous catalogs are never ignored.
- `required`: no selected task may receive new run admission without an authoritative validated task scope with meaningful input and write boundaries. Explicit/derived/ad hoc scope arguments may not supply otherwise missing authority.
- Parallel planning requires an explicit valid task scope in **both** modes.
- Policy mode changes performed by ProjectCTL use the existing `execution-authority` gate and a no-active-runs check; direct human edits are outside the lock but subject to freshness and integrity validation. The CLI must never offer a per-run bypass of `required`.

### 3. Bind policy to execution authority and enforce at every boundary

- Retain `ExecutionInputManifest` as the runtime execution-input authority. Propose **v2** to bind `scope_governance.mode` and its semantic policy identity to planned task scope; keep a v1 reader and v1 audit/digest semantics. Do not overwrite historical manifests.
- A change of governance policy or selected authoritative task scope between planning and worker admission invalidates stale work instead of silently weakening enforcement.
- Check effective policy at run preparation, before/after claiming as appropriate, at worker start/resume, and when independently verifying. The verification layer must fail closed for a required-mode run with a missing/unprovable scope, not merely report an empty `execution-write-scope` violation list.
- Provide an explicit write boundary in ContextManifest/WorkerRequest for every required-mode worker turn. Existing `ExecutionInputManifest.write_scopes` and code-input digests remain the runtime reference; neither Graphify nor a worker suggestion grants authority.
- During legacy manifest replay or crash recovery, never infer absent v2 governance evidence as `required` compliance. Existing v1 artifacts remain auditable; continuation needs a proven-compatible policy or must stop for operator decision. Preserve historical schema-specific semantic-digest computation.

### 4. Explicit, crash-safe legacy catalog migration

Proposed operator command: `projectctl scope migrate --project PATH`.

Preconditions: exactly one valid **legacy** catalog, no canonical catalog, clean primary repository, no active runs, no unresolved competing scope migration/adoption, safe non-symlink paths. Hold `execution-authority -> scope-migration` locks throughout the operation. Dry-run shows exact resulting YAML, schema conversion, source/target digests, and tracked Git diff intent.

Persist an exact source-bound migration request *before* mutating file authority. Write and fsync canonical bytes atomically, then retire the legacy path. Between the two file operations, the dual-file state always fails closed to readers; process exit/recovery compares exact before/after bytes and durable intent. Recover only proven before/after transition states; unknown, edited, or conflicting states require manual audit. Persist a receipt after validating canonical bytes, then require the operator to inspect and commit the resulting Git deletion/addition. No execution against a dirty primary repository. The design must explicitly test crashes at each file transition.

A legacy-only project can continue ordinary execution according to its governance mode until its operator chooses migration. A new M5.2b scope review/adoption targets the canonical file; a legacy-only project must migrate first. Historical v1 review/adoption artifacts remain parseable for audit but may not silently adopt into the newly named policy; stale reviews require regeneration. Any in-flight request recovery is exact-path/digest-bound and must not reinterpret old approval as new policy approval.

### 5. Context review, ownership, and verification

- New review/request/receipt artifacts use generic scope models and canonical path with explicit versioned parsers; historical M5.1 v1 artifacts remain readable. Exact review digest approval remains content-bound operator approval, not cryptographic user identification.
- Preserve additive-only approval and existing `execution-authority -> context-scope-adoption` serialization from ADR-037. Do not create a second adoption authority or grant automatic write scope from discovery.
- Mark **both** scope filenames human-managed. Add them to system-protected worker diff paths and check any additional instruction/context exposure. Confirm the current protection path rather than assuming file ownership alone protects the worker.
- Preserve fast-forward, reapplication re-verification, account-global quota admission, and parallel safety proofs. No change to Task Authority or worker Git privileges.

## Rejected approaches

1. Renaming `projectctl.parallel.yaml` in place without a reader migration: breaks existing projects and review evidence.
2. Silently accepting/combining both catalogs: creates two competing authority sources.
3. Treating an absent catalog as `required` compliance based on a worker-supplied scope: crosses human authorization.
4. Adding generic scope semantics only to ParallelPlan: recreates the M4.2 split in runtime authority.
5. Quietly upgrading existing projects to `required`: changes execution behavior without human choice.

## Review-sensitive details

- Validate the precise `ExecutionInputManifest v2` compatibility surface and semantic digest before implementation; every caller that persists, loads, hashes, or revalidates execution inputs must agree.
- Ensure policy changes cannot race durable run admission and have explicit handling for active, checkpointed, and recovery-needed runs.
- Check schema/model compatibility for `ContextScopeReview` and its approval/request/receipt replay before picking the new version numbers.
- Keep config version upgrades in-memory on reads. A separate SQLite migration is not implied by a YAML ProjectConfig version change.
- Confirm platform-safe durable migration and failure-path cleanup; a multi-file migration is not claimed to be one atomic filesystem operation.

## Completion conditions

M5.2b is complete only when canonical/legacy/dual/missing combinations, governance modes, serial/parallel admission, start/resume, verification, M5 adoption, stale policy digests, crash recovery, schema export, and historical artifact readers have deterministic tests. Update `docs/PROJECTCTL_BLUEPRINT.md`, user README, public schema export, Project State, and the version in the implementation PR. Run the relevant test suite locally; unavailable GitHub Actions runners are **not** evidence of passing CI.

This proposed ADR is the architecture decision candidate; `docs/PROJECT_STATE.yaml` remains the only authority for the active milestone.
