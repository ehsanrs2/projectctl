# Post-M5.2 Architecture Closure Review

**Status: Architecture review accepted for M5.2b closure and M6.0 direction selection — 2026-10-12**  
Reviewed baseline: `main@8e148aff9560ee9cc2e2b8d9bbb260504502f285` (merged PR #51, 2026-10-12)  
Milestone transition: `docs/PROJECT_STATE.yaml` selects **M6.0** in the closure PR; the merged pre-transition state was M5.2b  
Decision: `docs/decisions/ADR-038-general-execution-scope-governance.md` — **Accepted in the milestone closure PR**

> This review was originally proposed in PR #52 and accepted by the owner together with the M6.0 direction. The milestone closure PR makes the ADR and Project State changes effective on merge. This does not authorize a release, new worker authority or relaxed scope policy.

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

## 4. Architecture closure decision

**Decision: Accept ADR-038 as the documented M5.2b execution-scope architecture** with the recorded operator-confirmed GitHub Actions quota exception and local suite / pinned SDK evidence. This acceptance does not promise platform-independent durability, cryptographic identity, live worker acceptance or green hosted CI.

The closure PR records this accepted direction by updating ADR-038 to
`Accepted`, marking M5.2b `Completed` in Blueprint/README and advancing the
single `docs/PROJECT_STATE.yaml` authority to the owner-selected M6.0. The
recorded GitHub Actions quota exception remains non-green CI. The release
version remains `0.41.0`; any future bump, tag or publication requires a
separate release decision. The specific M6.0 evidence and privacy contracts
are still **proposed** under ADR-039 and must be approved before implementation.

**The closure PR makes these recorded architecture decisions effective on merge.**

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

The operator has selected **M6.0 Read-only Trace & Evaluation Export** from these candidates. Other candidates remain deferred; their ordering remains non-binding.

### Recommended first product slice, if selected

**Selected M6.0 — Read-only Trace & Evaluation Export**.

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
skill or automation authorities. This sequencing is now the owner-selected product priority; it remains subject to its own design/acceptance gates.

## 6. Review and transition gate

The milestone closure PR accepts ADR-038 and advances the sole active state to M6.0 without tagging a release. The owner-confirmed GitHub Actions quota exception remains documented rather than treated as a passing hosted run. ADR-039 and the M6.0 implementation plan define the next **proposed** privacy, provenance and read-only acceptance gates; no new worker authority is granted merely by selecting M6.0.
