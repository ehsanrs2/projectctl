# M5.2b — Slice D closure and architecture acceptance audit

**Status: LOCAL REGRESSION AND PINNED CODEX SDK CONTRACT GATES PASSED; CI AND FORMAL ARCHITECTURE ACCEPTANCE OPEN.**

This document is a recorded evidence review, not a second source of
milestone authority. `docs/PROJECT_STATE.yaml` continues to name M5.2b
until outstanding acceptance requirements and the next-goal decision are
explicitly resolved.

## Implementation and source revisions

- PR #45: Slice A — generic execution-scope catalog and ProjectConfig v10.
- PR #46: Slice B — ExecutionInputManifest v2 and lifecycle enforcement.
- PR #47: Slice C — explicit migration and canonical reviewed adoption.
- PR #48: Slice D — strict receipt validation, regression gates and docs.
- PR #49: preserve exact YAML bytes in ContextScopeReview v2.
- PR #50: restore compatibility of the 13 stale/full-suite test fixtures.
- PR #50 merged on **2026-10-12** at
  `main@f6aa8b5cdcf5a6ab552045b54e403ff24a16667a`.
- The locally tested PR #50 head is
  `07ab421906c39c5953519f3f89679d44c88fee90`.
  GitHub Git commit metadata reports **the same tree SHA**
  `e0a4120580c208e6854a64121fa4398d04407e25` for both
  the tested PR head and the merge commit. The merger introduced no
  tree-content difference from the locally tested revision.

## Human-supplied local test evidence

The operator supplied terminal output from the PR #50 feature checkout:

1. `python -m pytest -q`: **100% displayed; no failures or errors**.
2. `bash scripts/m52b-closure-check.sh`:
   - targeted scope, historic and execution regressions: **100% displayed**;
   - complete suite re-run: **100% displayed**;
   - `git diff --check` gate reached;
   - final output: **"M5.2b local closure checks passed."**
3. Earlier terminal output from the same local uv-based setup reported
   Python **3.12.15** and pytest **9.1.1**. The latest invocation did not
   separately print versions or the tested SHA. Revision identity is supported
   by the checked-out branch and GitHub tree equality, not a command-captured
   `git rev-parse HEAD` from the terminal.

This is valid **operator-reported local regression evidence** for the current
main tree. It is not independently reproduced within this connected session,
and is not a substitute for green GitHub CI or formal architecture acceptance.

## Acceptance matrix

| Gate | Evidence | Current status |
| --- | --- | --- |
| Generic catalog, no dual authority, optional/required modes | M5.2b scope tests included in targeted gate | **Local pass reported** |
| Serial/parallel scope and run/verification enforcement | Targeted M4/M5 suites and complete suite | **Local pass reported** |
| Migration crash windows, receipt-integrity, and historical adoption approval | Targeted migration/adoption suites | **Local pass reported** |
| Historical schemas, config in-memory upgrades and v2 review YAML byte integrity | Complete suite including fixed v8–v10 fixtures | **Local pass reported** |
| Public SDK contract with real pinned `openai-codex` | Operator installed the exact pinned SDK in uv and ran the non-skippable contract script | **7 local tests passed; reported** |
| GitHub Actions test and SDK jobs | Run on PR #50 merge SHA reported completed/failure | **Not green; cause unproven** |
| ADR-038 architecture acceptance, docs/version release policy, next milestone | Architecture owner must approve final design and explicitly select next step | **Pending human acceptance** |

### GitHub Actions observation

The latest `main` CI run for
`f6aa8b5cdcf5a6ab552045b54e403ff24a16667a` was
[run 38241675582](https://github.com/ehsanrs2/projectctl/actions/runs/38241675582),
`completed/failure`. Both jobs `test` and `codex-sdk-contract` are
marked `failure`. Job metadata did not expose usable step details.
This **does not prove** either a test regression or a runner/credits problem. The subsequent PR #51 Actions [run 38242378674](https://github.com/ehsanrs2/projectctl/actions/runs/38242378674) also reports `completed/failure`; the local SDK pass does not change that CI result.
Resolve by obtaining the actual logs, rerunning in a provisioned CI runner
or documenting the infrastructure blocker separately. Never label this green.

### Pinned Codex SDK verification with uv — completed locally

The Codex public API test uses
`pytest.importorskip("openai_codex")`. A passing complete suite may
therefore have **skipped** this test when the optional dependency is absent.
The operator has now run the following distinct acceptance check on PR #51's
feature checkout. Import and pinned-version preconditions cannot silently skip:

```bash
source .venv/bin/activate
uv pip install -e ".[dev,codex]"
bash scripts/m52b-codex-sdk-contract-check.sh
```

**Observed terminal output, reported by the operator on 2026-10-12:**

- `uv pip install -e ".[dev,codex]"`: installed `openai-codex==0.160.0` and `openai-codex-cli-bin==0.160.0`.
- `Pinned Codex SDK importable; version=0.160.0`.
- The contract and adapter suite displayed `....... [100%]` (7 tests).
- Terminal ended with `Pinned Codex SDK public contract and adapter checks passed.`
- The operator checked out branch `docs/m5.2b-closure-evidence-sdk-gates` before running. The branch head at PR #51 check time was `e2177a2b04dc944f5866a826470850c27090bde1`; the terminal did not print `git rev-parse HEAD`.

The SDK gate is therefore **operator-reported locally passed**, not independently run here. It is separate from remote Codex worker acceptance and does not exercise a live worker. A post-report documentation-only commit does not change the pinned SDK checker itself.

## Architecture invariants for ADR acceptance

- Exactly one human-managed canonical or validated legacy scope authority.
  Both present, malformed files, symlinks and pending/tampered journals fail closed.
- Scope `optional` preserves backward-compatible serial planning.
  `required` refuses unscoped work; parallel planning requires scope in both.
- ExecutionInputManifest v2 binds selected policy and source identity across
  prepare, worker start/resume, recovery and independent verification.
  Historical v1 artifacts retain their own parser/digest semantics.
- Human digest approval is content-bound (not cryptographic identity);
  v1 review/request/receipt evidence is audit-only for canonical mutations.
- Migration requires explicit human action, durable source/target evidence,
  exact recovery states, and subsequent human Git commit. It is not a
  multi-file atomic transaction.
- Shared execution-authority locking serializes adoption and new run
  admission; derived discovery/Graphify does not grant write authority.

## Residual limitations

- Cross-platform directory fsync/power-loss durability differs. Local test
  success does not establish filesystem-wide transactional guarantees.
- External direct file edits are outside application-held locks and require
  freshness checks. Local `.projectctl/` journals are not portable signing.
- A successful suite verifies coded contracts, not all operational
  environments, live Codex worker behavior or GitHub Actions availability.

## Milestone promotion rule

Do **not** change `docs/PROJECT_STATE.yaml`, tag a release, or claim
ADR-038 accepted solely because this report has a local pass.
The pinned SDK evidence is now recorded. Final acceptance still needs CI
failure disposition, ADR decision review and a human-selected next roadmap
direction. The implementation can be described accurately as
**merged and locally regression-tested**, while the milestone remains active.

See `docs/architecture/M5_2B_IMPLEMENTATION_PLAN.md`,
`docs/architecture/M5_2B_SCOPE_MIGRATION.md`,
`docs/architecture/POST_M5_ARCHITECTURE_REVIEW.md` and ADR-038.
