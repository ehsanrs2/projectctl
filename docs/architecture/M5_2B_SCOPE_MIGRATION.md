# M5.2b Slice C — Scope migration and canonical reviewed adoption

**Status:** Slice C merged in PR #47; Slice D receipt-integrity hardening and final test evidence still pending. This is not milestone closure.

## Operator workflow

1. Commit/stash all unrelated local repository changes. Ensure the legacy
   `projectctl.parallel.yaml` is committed, and no active or unresolved
   ProjectCTL runs or pending scope adoption requests exist.
2. Inspect the **read-only preview**:
   `projectctl scope migrate --project /path/to/repo`.
3. If the output and source/target SHA-256 hashes are acceptable, explicitly run:
   `projectctl scope migrate --project /path/to/repo --apply`.
4. Review `git diff`, stage the addition of `projectctl.scope.yaml` and deletion
   of `projectctl.parallel.yaml`, and commit the policy change. **ProjectCTL does
   not commit, rebase, merge, or push this change.**
5. Regenerate old scope reviews and use
   `projectctl context review-scope` / `context adopt-scope` to approve a
   **new canonical v2 review digest**. Existing approvals cannot be re-targeted.

## Crash and recovery boundaries

The migration is *not* a single atomic rename. The exact source digest and
canonical target YAML bytes are recorded in a durable request journal at
`.projectctl/scope-migrations/<migration-id>/request.json` **before** either
authority file changes. The journal is human-inspectable and lives outside Git
in the local operational store.

Only these exact policy-file states can be continued with an explicit command:

| Journal state | Legacy | Canonical | Recovery |
| --- | --- | --- | --- |
| Before canonical write | Exact recorded source | Absent | Recreate the exact recorded target |
| After canonical write | Exact recorded source | Exact recorded target | Retire legacy file |
| After legacy retirement | Absent | Exact recorded target | Validate and persist receipt |

Until the receipt is present, normal scope resolution fails closed even if
the canonical file is the only policy file. The dual-file interval also fails
closed. `projectctl scope migrate --recover` is the **only** supported automatic
continuation; edited/unexpected source or target bytes, multiple pending
migrations, symlinks, incomplete journals, and incompatible receipts stop for
manual audit. No rollback of an uncertain file state is attempted.

Migrations hold `execution-authority` then `scope-migration` locks,
consistent with the M5.2a lock order. Active and unresolved runs, pending
reviewed-adoption writes, and a dirty Git repository block a new migration.
Crash recovery may legitimately run with a dirty Git diff, but requires
a matching durable journal and exact bytes.

## Context compatibility

- New M5.1 review/request/receipt outputs are `v2`, with the canonical
  `projectctl.scope.yaml` path and generic `ExecutionTaskScope`.
- Historical `v1` artifacts remain schema-parseable for audit only; exact old
  review digest approval is not automatically valid for the new authority.
- Discovery's declared-scope coverage uses the same canonical/legacy resolver
  as execution. Discovery does not grant write permission.
- Legacy-only repositories still permit execution through the read-only legacy
  resolver under their project governance policy, **but they cannot write new
  reviewed scopes** until an explicit catalog migration; committing the
  migrated policy is required before automated run preparation.
- Existing historical ParallelPlan, Run and ExecutionInput artifacts remain
  versioned; no silent rewriting.

## Checks required before merge

```bash
python -m pytest -q tests/test_m52b_scope_migration.py tests/test_m51_context_adoption.py tests/test_m50_context_discovery.py
python -m pytest -q tests/test_m52b_scope_enforcement.py tests/test_m52b_scope_foundation.py tests/test_m41a_parallel_planning.py tests/test_m41b_parallel_runtime.py
python -m pytest -q
git diff --check main...HEAD
```

Inspect failure injection at each transition and verify that no worker starts
against an incomplete migration. GitHub Actions not starting is **not** passing
test evidence.

See proposed ADR-038 and `docs/architecture/M5_2B_IMPLEMENTATION_PLAN.md`.
M5.2b cannot be marked complete until Slice D test and architecture gates pass.
