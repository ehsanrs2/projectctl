# Post-M5.2 Architecture Closure Review

**Status: Proposed review / human architecture decision pending**  
Reviewed baseline: `main@8e148aff9560ee9cc2e2b8d9bbb260504502f285` (merged PR #51, 2026-10-12)  
Current structured milestone authority: `docs/PROJECT_STATE.yaml` — **M5.2b**  
Decision candidate: `docs/decisions/ADR-038-general-execution-scope-governance.md` — **Proposed**

> This review is a decision proposal and evidence synthesis, not an authorization
> to mark ADR-038 Accepted, to change the active milestone, or to deploy a release.

## 1. Scope and evidence of closure

M5.2b was the required last closure milestone from the accepted Post-M5
Architecture Review. Its function was to remove the gap between
parallel-only-named scope and the generic execution authority while making
serial scope optionality an explicit durable project decision.

The implementation is merged:

| Milestone work | Evidence |
| --- | --- |
| M5.2a: shared execution-authority serialization | ADR-037 (Accepted), PR #43 |
| M5.2b Slice A: generic catalog/config v10 | PR #45 |
| M5.2b Slice B: runtime policy and execution-input v2 | PR #46 |
| M5.2b Slice C: explicit migration and canonical scope adoption v2 | PR #47 |
| M5.2b Slice D: migration receipt verification | PR #48 |
| Review YAML byte-integrity regression | PR #49 |
| Full-suite historical/orchestration fixture regressions | PR #50 |
| Evidence, pinned SDK gate and Actions quota disposition | PR #51 |

The operator reported on the merged PR #50 tree (which GitHub confirms is
tree-identical to the merge SHA) that the full pytest suite, M5.2b targeted
acceptance gate, and Git patch check passed. The operator separately
installed `openai-codex==0.160.0` in an `uv` virtual environment and ran
the non-skippable SDK/adapter gate: **7 tests passed**. The GitHub Actions
quota had been exhausted; the operator confirms this as the reason hosted
jobs were blocked. Those GitHub runs remain marked **failure** and are
**not** reclassified as passed. Repeat hosted CI once account quota returns.

Evidence details and the exact SHA provenance are recorded in
`docs/architecture/M5_2B_CLOSURE_AUDIT.md`.

## 2. Architectural findings

### F-01 — One human-managed execution-scope authority: closed by design and tests

- Canonical: `projectctl.scope.yaml` /
  `ExecutionScopeCatalog v1`.
- Legacy-only: `projectctl.parallel.yaml`, validated with its historical
  reader then converted *in memory*.
- Both catalog files present, unsafe paths, malformed input, or pending,
  forged, incomplete migration journals: **fail closed**.
- Scope task semantics and historical artifacts are kept separately versioned;
  the generic resolver is shared between execution and context workflows.

### F-02 — Explicit serial/parallel governance: closed by design and tests

- `ProjectConfig v10.scope_governance.mode` is `optional|required`.
- Existing config v1–v9 is upgraded only in memory to `optional`; no
  silent policy hardening or rewrite.
- `required` blocks admission without human-managed task input and write
  scope, independently of worker/ad hoc arguments.
- Parallel admission always requires explicit task scope, including in
  `optional` projects.

### F-03 — Durable authority and independent verification: closed by design and tests

- `ExecutionInputManifest v2` binds selected governance mode/catalog-source
  identity and task scope to the run; v1 remains independently readable
  with historical digest semantics.
- The common admitted-input boundary revalidates prepare/start/resume and
  recovery; verification independently checks current scope authority.
- Both catalog policy paths are human-owned and system-protected against
  worker edits. Suggested scope/discovery is never self-authorizing.

### F-04 — Reviewed adoption and crash-safe migration: closed within documented limits

- M5.2a serializes run admission and policy adoption under the shared
  `execution-authority` gate.
- Review/Request/Receipt v2 refer to the canonical policy and carry exact
  content-bound human approval. Historical v1 approvals remain audit-only.
- Operator migration uses preview, explicit apply and exact journaled recovery.
  It is **not** an atomic two-file filesystem transaction.
- Strict receipt-content validation (PR #48) and preservation of exact
  approved YAML bytes (PR #49) are required security/correctness fixes, not
  optional conveniences.

## 3. Residual limitations (accepted boundaries vs unproven claims)

1. **Hosted CI availability:** operator-confirmed exhausted GitHub Actions
   quota. The local checks are green; hosted CI is not. Re-run when funded.
2. **No remote live-worker acceptance implied:** pinned SDK public contract
   tests do not prove actual provider/OS/network behavior.
3. **Crash durability is platform-sensitive:** journal/rename/fsync cannot
   promise atomicity across power loss on every filesystem or OS.
4. **Human review is content approval:** a matching digest is not a
   cryptographic human identity or signed attestation.
5. **Direct human edits happen outside application locks:** freshness
   validation, protected path checks and review boundaries are mandatory.
6. **Operational evidence is local:** `.projectctl/` journals and approvals
   are not repository-portable signatures.
7. **Versioned release remains separate:** the project currently declares
   `0.41.0`. A tag/version bump requires explicit release review, not merely
   completion of an architecture milestone.

These are explicit scope limits, not grounds to bypass any of the run
admission, evidence, migration, or approval checks.

## 4. Proposed architecture decision

**Recommendation: Accept ADR-038 as the documented M5.2b execution-scope
architecture**, subject to operator review of this report and release
policy. Accepting it should not promise platform-independent durability,
cryptographic identity or green hosted CI.

On acceptance:

1. Change ADR-038 status to `Accepted` and replace outdated
   pre-implementation tense with an as-built summary and evidence refs.
2. Mark M5.2b **Completed** in the Blueprint/README, while preserving the
   hosted-CI quota exception and residual limitations.
3. Preserve `docs/PROJECT_STATE.yaml` as the **sole active-state authority**.
   Advance it only when the next goal/milestone is explicitly selected.
4. Review the release version separately (potential next minor pre-1.0
   release candidate: `0.42.0`, **not yet chosen**). Do not tag or publish
   automatically.

**No status is changed by this proposal alone.**

## 5. Next major product-direction decision

The accepted Post-M5 review intentionally deferred new product expansion
until M5.2a/b closure. Its candidate areas remain:

| Candidate | Expected upside | New architecture/authority risk | Suggested order |
| --- | --- | --- | --- |
| Read-only evaluation and trace export | Makes the existing evidence/run chain inspectable and measurable, without granting new authority | Low–medium: privacy, data lineage, schema versioning | **First candidate** |
| Governed skills registry and supply-chain controls | Prevents arbitrary skill/tool capability escalation | Medium–high: trust, pinning, signing, revocation | After observability, before autonomous expansion |
| Broader language-aware context discovery | Improves useful code navigation beyond existing Python AST | Medium: parser versions, false positives and provenance | Bounded additive work |
| Additional worker providers | Broadens supported environments | High: provider-specific sandbox/approval/capability semantics | After better trace comparability |
| Research → Hypothesis → Experiment → Evidence → Decision | Extends the control plane into research workflows | High: new domain objects and decision authority | Separate architecture phase |
| Human cockpit / Obsidian integration | Improves oversight and operator experience | Medium: UI is non-authoritative, consent and state synchronization | After read-only views are stable |
| Multi-agent orchestration | Potentially higher throughput | Very high: conflicts, quota, independent verification | Not next; retain safety prerequisite |

The order above is a **recommendation, not an accepted roadmap**.

### Recommended first product slice, if selected

**Candidate M6.0 — Read-only Trace & Evaluation Export**.

- Begin with an explicit versioned `ExecutionTraceBundle` that references
  existing run, input, claim, worker, verification and delivery evidence
  *without changing their authority*.
- Add a local CLI read/export operation with deterministic ordering and
  explicit redaction of secrets/sensitive payloads; no network egress by
  default and no automatic worker invocation.
- Define provenance, completeness and stale/missing evidence representation
  before scoring or metrics.
- Introduce explainable evaluation measures derived from independently
  verified artifacts, not a worker self-reported success field.
- Tests must include malformed/stale source data, privacy exclusions,
  historical schema versions, reproducibility and cross-project isolation.
- This **must** get its own bounded ADR and acceptance tests before code.

Why this candidate first: it makes the existing deterministic execution and
evidence architecture easier to audit before introducing additional worker,
skill or automation authorities. This is a sequencing judgment, not a
claim of an established product priority.

## 6. Review and transition gate

The final closure PR should be a **separate, explicitly approved** change
after the operator chooses the next product direction. That PR can accept
ADR-038, advance the single `PROJECT_STATE.yaml` authority to the selected
milestone, update the Blueprint/README and select the release/version policy
without confusing a review proposal with a completed decision.

Before the final PR is merged, obtain:
- acceptance of the ADR-038 invariants and recorded CI exception;
- an explicit next-milestone goal and ID;
- a decision on whether a release/version bump is in scope.

Until then, **M5.2b remains the formal active milestone** despite its
merged and locally regression-tested implementation.
