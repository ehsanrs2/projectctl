# M5.2b — Slice D closure and architecture acceptance audit

**Audit status: OPEN — M5.2b is NOT yet validated or released.**  
Baseline reviewed: `main@e6092d6469688c141f3dd58c07725e490dfe606c` (merged PR #47).  
Authoritative active milestone: `docs/PROJECT_STATE.yaml`.  
Architecture candidate: `docs/decisions/ADR-038-general-execution-scope-governance.md` (**Proposed** until explicit acceptance).

This is an evidence/gate tracker, not a second source of project-state authority.

## Delivered implementation, subject to acceptance tests

| Slice | Code landed on main | Outstanding evidence |
| --- | --- | --- |
| A | PR #45: generic scope model/resolver, `ProjectConfig v10`, historical schema readers | Local schema/fixture regression |
| B | PR #46: `ExecutionInputManifest v2`, required-mode run/worker/verification enforcement, protected policy paths | Independent verification, admission/recovery regression |
| C | PR #47: explicit journaled migration, canonical Context Discovery/Review/Adoption v2, v1 audit compatibility | Filesystem crash and concurrency tests |
| D | This hardening branch: strict receipt validation, regression tests, documentation and local gate script | **Must be run and reviewed before merge and milestone closure** |

## Concrete Slice D defect and disposition

**D-01 — Completed migration receipt presence treated as evidence of completion.**

The merged Slice C resolver checked for the mere *existence* of
`receipt.json`, whereas `migration._pending_journals` already has a stronger
validator that verifies the exact request fields, target digest, journal identity,
and receipt identity/digests. A forged/corrupted completed receipt could therefore
make the normal runtime reader treat a canonical-only state as usable even when
migration evidence was not valid.

**Fix in this branch:** the normal resolver calls
`assert_no_pending_scope_migration` (with its exact journal validation) instead
of checking filenames alone. Migration's internal postcondition check explicitly
retains `allow_pending_migration=True` solely while holding the transition
locks. New regression cases create tampered completed receipts and forged
receipts after a simulated crash. Neither is permitted as runtime authority.

**Important:** tests for this fix have been authored but not executed here.

## External CI evidence observed

For PR #47 head `81beb3b8725548b4e460fb8ff90e5435cb3c4b5d`:

- GitHub Actions run: `38217243686`, status `completed`, conclusion `failure`.
- Jobs: `test` (`114704742122`) and `codex-sdk-contract`
  (`114704741896`), both reported `failure`.
- Step summaries were empty; the log download returned a BlobNotFound/404
  response. The failed jobs **must not be reported as test failures or
  infrastructure-only failures without further evidence**.
- No successful CI or local `pytest` evidence is available from this session.

The repository was inspected through a connected private GitHub account; this
session did **not** execute `pytest` in a working checkout and did not perform a
production migration.

## Acceptance matrix

| Gate | Required evidence | Current result |
| --- | --- | --- |
| A: Architecture | Review ADR-038 decisions, version invariants and operator approval boundary | **Pending** — ADR Proposed |
| B: Schema/backward compatibility | Old ProjectConfig v1–v9 and ExecutionInput v1 digest/reader; new v10/v2; legacy parallel scopes | **Untested locally** |
| C: Runtime enforcement | Required/optional serial, parallel, preclaim/admitted, worker start/resume, verification, read-only/worker write paths | **Untested locally** |
| D: Migration/adoption | Exact three crash windows, dual/pending states, forged receipts, symlink rejection, lock ordering, legacy v1 audit-only and review replay refusal | **Untested locally** |
| E: Release readiness | Full `pytest`, relevant SDK contract tests in a correctly provisioned environment, `git diff --check`, docs/README/Blueprint review | **Blocked by missing execution evidence** |

### Required reproducible local command

From the feature branch in a genuine checkout, with Python >=3.12 and
`python -m pip install -e '.[dev]'` already completed:

```bash
bash scripts/m52b-closure-check.sh
```

Capture and attach: `git rev-parse HEAD`, `python --version`, the full
terminal output and process exit code. Follow up separately with the SDK
contract workflow in a provisioned environment (the optional Codex SDK
dependency is pinned in `pyproject.toml`). Re-run or inspect the GitHub
Actions jobs once runners/logging are available. **Do not equate empty job
steps or absent logs with passed tests.**

### Manual review / destructive-state checklist

1. Confirm new projects default to `optional` without silently upgrading old
   persisted configs, and `required` rejects missing input/write evidence.
2. Confirm planning, start, resume, recovery and verification reject policy
   drift, catalog-source changes and unauthorized scope mutation.
3. Confirm only one canonical/legacy authority can exist; incomplete,
   malformed or tampered journals block all ordinary execution.
4. Inject crashes before canonical write, during dual-file state and before
   receipt; recover only exact recorded source/target states.
5. Confirm v1 review/request/receipt and ExecutionInput artifacts remain
   readable for audit but never authorize new canonical policy mutation.
6. Confirm the full suite, schema export and git hygiene checks pass without
   disabling any historical tests.

## Residual limitations to acknowledge

- The two-file migration is **not** a single atomic filesystem transaction.
  Journaled crash recovery, not atomic rename of both files, provides
  consistency. Directory `fsync` behavior may differ across platforms.
- Exact review-digest confirmation is operator content approval, **not**
  cryptographic human identity. Direct human edits lie outside ProjectCTL's
  execution-authority lock, but their freshness must be checked.
- M5 local adoption/migration evidence is stored in `.projectctl/` and is not
  automatically repository-portable attestation.
- Historical ParallelPlan and ExecutionInput evidence cannot be silently
  reinterpreted under a newer governance policy.
- Running the full tests alone is not enough: actual observed success and
  architecture sign-off are mandatory.

## Decision after acceptance

Only **after** all gates are backed by real evidence: accept the final form of
ADR-038, update the canonical `docs/PROJECT_STATE.yaml` to the selected next
milestone, update release notes and version according to release policy, and
prepare the post-M5.2 architecture closure. Until then, leave M5.2b active and
this hardening PR in Draft status.

Reference: `docs/architecture/M5_2B_IMPLEMENTATION_PLAN.md`,
`docs/architecture/M5_2B_SCOPE_MIGRATION.md`,
`docs/architecture/POST_M5_ARCHITECTURE_REVIEW.md`.
