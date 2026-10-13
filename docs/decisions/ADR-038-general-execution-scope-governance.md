# ADR-038: General Execution Scope Authority and Explicit Governance

Status: **Accepted — 2026-10-12**, as the completed M5.2b execution-scope architecture. This acceptance becomes the repository decision upon merging the closure PR.
Original design base: `main@8dd6a53d8f71bac353c48803587ee9fa690d7e4c`
Implementation evidence: merged PRs #45–#51, with closure review based on `main@10212d810a2bd631a9f7343a26216f08a94c7a73`;
see `docs/architecture/M5_2B_CLOSURE_AUDIT.md`.
Supersedes: none. Extends ADR-031, ADR-033, ADR-035, ADR-036, and ADR-037.

## Context

At the time of the Post-M5 review, `projectctl.parallel.yaml` /
`ParallelScopeCatalog v1` had become the effective authority for serial
execution, M5 discovery/adoption and independent verification in addition to
parallel planning. Unscoped serial admission was implicit whereas parallel
admission already required a declared scope. M5.2b resolved this by introducing
a generic authority and a durable `optional|required` project policy without
silently tightening historical projects.

The design was proposed before Slices A–D and the follow-up integrity and
regression fixes. The operator explicitly selected M6.0 as the next direction
after the Post-M5.2 review, and the closure PR records acceptance of the
implementation-backed M5.2b invariants. Acceptance **does not** imply
green hosted CI, a tagged release, cryptographic human approval, or universal
cross-filesystem power-loss guarantees. All future policy mutations and
worker admissions remain governed by the implemented checks.

## Accepted design decisions (implemented)

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

- Retain `ExecutionInputManifest` as the runtime execution-input authority. Version **v2** binds `scope_governance.mode` and its semantic policy identity to planned task scope; keep a v1 reader and v1 audit/digest semantics. Do not overwrite historical manifests.
- A change of governance policy or selected authoritative task scope between planning and worker admission invalidates stale work instead of silently weakening enforcement.
- Check effective policy at run preparation, before/after claiming as appropriate, at worker start/resume, and when independently verifying. The verification layer must fail closed for a required-mode run with a missing/unprovable scope, not merely report an empty `execution-write-scope` violation list.
- Provide an explicit write boundary in ContextManifest/WorkerRequest for every required-mode worker turn. Existing `ExecutionInputManifest.write_scopes` and code-input digests remain the runtime reference; neither Graphify nor a worker suggestion grants authority.
- During legacy manifest replay or crash recovery, never infer absent v2 governance evidence as `required` compliance. Existing v1 artifacts remain auditable; continuation needs a proven-compatible policy or must stop for operator decision. Preserve historical schema-specific semantic-digest computation.

### 4. Explicit, crash-safe legacy catalog migration

Implemented operator command: `projectctl scope migrate --project PATH` (read-only preview by default; explicit `--apply` and `--recover`).

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

## Acceptance evidence and residual constraints

The acceptance decision is grounded in the merged implementation and the
Post-M5.2 Architecture Review:

- PR #45: generic schema/resolver and ProjectConfig v10.
- PR #46: ExecutionInputManifest v2, required-mode admission and independent
  scope revalidation.
- PR #47: canonical reviewed adoption and journaled explicit migration.
- PR #48: migration receipt integrity and closure-script requirements.
- PR #49: exact approved YAML byte-preservation in v2 review.
- PR #50: successful operator-reported local full suite and targeted regression
  tests, with Git tree identity verified against merged main.
- PR #51: operator-reported non-skippable pinned `openai-codex==0.160.0` SDK
  contract/adapter gate (7 tests passed), and the GitHub Actions quota
  exhaustion recorded as an infrastructure exception.

The owner confirms the GitHub Actions quota is exhausted. Failed hosted
runs have **not** been relabeled as passing CI and must be rerun when the
quota is restored. Local acceptance tests do not demonstrate an end-to-end
live provider run, platform-independent multi-file transaction, portable
cryptographic audit receipts or authenticated operator identity.

Human-managed catalog changes, migration and review-digest approvals remain
content-bound and fail closed on ambiguous or stale states. Old schema
versions and run evidence retain their historical parsing/digest semantics.

See `docs/architecture/M5_2B_CLOSURE_AUDIT.md` and
`docs/architecture/POST_M5_2_ARCHITECTURE_REVIEW.md`.

## Decision outcome

**M5.2b execution-scope architecture accepted.** This closes the generic
scope-governance part of the Post-M5 required architecture work. The subsequent
`M6.0` read-only trace/evaluation goal is a separate milestone and **does not
grant** new authority over any M5 run, review, quota or worker decision.

`docs/PROJECT_STATE.yaml` remains the sole active-milestone authority.
The package version and release tag remain independently governed by the
release process: no automatic publication or version bump is entailed.

