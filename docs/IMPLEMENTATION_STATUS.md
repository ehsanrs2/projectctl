# ProjectCTL — Implementation status and dependency ledger (2026-11-04)

> **Status snapshot, not a second roadmap or execution authority.** The [Blueprint](PROJECTCTL_BLUEPRINT.md) governs the overall product architecture and roadmap shape; [PROJECT_STATE.yaml](PROJECT_STATE.yaml) alone determines the active milestone (M6.0). Accepted ADRs govern bounded design decisions; evidence and approvals are separate. This index reconciles [main at 82f576632f35b68adced2e529768d72f7017fd3b](https://github.com/ehsanrs2/projectctl/commit/82f576632f35b68adced2e529768d72f7017fd3b) on 2026-11-04.

## 1. Verified baseline

| Stream | Evidence | Correct classification |
| --- | --- | --- |
| Existing M0–M5.2 control plane | Implemented task/scheduling/run execution and independent verification with ADR-037/038 authority boundaries. | Existing feature coverage, not unconditional live-run permission. |
| D2 research | Direct and CTL arms passed 26 acceptance tests; direct Worker ~32.81 seconds vs CTL Worker-event interval ~33.91 seconds, with different timing definitions. | Bounded comparison, **not** statistical superiority, general overhead or provider cost proof. |
| **Post-D2 Lifecycle Observability** | [PR #126](https://github.com/ehsanrs2/projectctl/pull/126) merged 2026-11-04 06:25:50 UTC, final PR head 745d10f45fe834dfe7d1b58df61222f4eb9cceed; main merge 82f576632f35b68adced2e529768d72f7017fd3b. [Postmerge Actions](https://github.com/ehsanrs2/projectctl/actions/runs/41785470901): 2763 passed / 7 skipped, SDK-contract success. | **MERGED, offline-qualified**. No live D2 rerun, separate stage permission, source-attested Trace or new Worker privileges. |
| P01 and P02 | [#121](https://github.com/ehsanrs2/projectctl/pull/121) synthetic mixed-epoch/forged oracle and [#123](https://github.com/ehsanrs2/projectctl/pull/123) self-attesting receipt studies merged. | **LAB_ONLY**. Neither independently authenticates a real source epoch. |
| P3i–P3n | Bounded synthetic SQLite/custody, orphan, crash and ordinary guest reboot witnesses; [Issue #119](https://github.com/ehsanrs2/projectctl/issues/119) closed. | **LAB_ONLY**; not a real P0/P1 or host power-loss/rollback proof. |
| [P03-D1 PR #125](https://github.com/ehsanrs2/projectctl/pull/125) / [Issue #124](https://github.com/ehsanrs2/projectctl/issues/124) | Duplicate source-witness decision document was reviewed and **closed without merge**. Existing B-Diagnostic design/security matrix and ADR-040 retain the architecture; D1–D5 owner decisions were preserved in Issue #124. | **PR CLOSED AS REDUNDANT; OWNER_DECISION_REQUIRED**. No actual controller, writer, issuer or custodian selected. |
| [Issue #127](https://github.com/ehsanrs2/projectctl/issues/127) / [PR #129](https://github.com/ehsanrs2/projectctl/pull/129) | Typed pre-dispatch telemetry collision diagnostic merged at `d39bfedde82b9f2feab5130d14668e727184c7c6`. Postmerge CI #41805186666 passed: 2781 passed, 7 skipped. | **MERGED / ISSUE CLOSED**. No implicit retry, dispatch or new authority. |
| [W1c PR #131](https://github.com/ehsanrs2/projectctl/pull/131) / [Issue #130](https://github.com/ehsanrs2/projectctl/issues/130) | Disposable test-only fenced as-of Seal and crash-window fixture merged at `b7057c2d256332c88ad7902b8ec89b7204c4e989`. [Postmerge CI](https://github.com/ehsanrs2/projectctl/actions/runs/41835342458): 2797 passed / 7 skipped. | **MERGED / LAB_ONLY / ISSUE CLOSED**. P0–P4 and real W1 remain NO_GO. |

## 2. Two distinct observation products

**Implemented Post-D2 (ADR-041):** the derived read-only `projectctl run audit` checks supported RunStore, manifests and Git evidence. State `observed` means the stated local check passed; it does **not** mean a coherent atomic snapshot or authorization. `proposed_stage` is advisory, `permitted_action=inspect`, `dispatch_authorized=false` and `implicit_retry_allowed=false`. Its reader refuses unsupported live-WAL headers (unknown/no stage suggestion). Opt-in `--measurements PATH` on already separately authorized `start|resume|verify|integrate` records overlapping monotonic durations and scoped SDK usage; it is not a durable exclusive dispatch-intent journal, provider-cost proof, live task-store status or retry authority. This feature was selectively ported from research preserving main's quota/resource_class and WorkerOutputPayload schema.

**Separate M6.0 Trace Export (ADR-039 and ADR-040):** pure Trace contracts, historical artifact validators, test readers, synthetic Seal/receipt/custody labs exist. Still missing: an actual fenced W1 source writer, source-attested coherent P0/P1 as-of epoch, verified nonmutating R1 active-WAL read, independent P2 issuer/P3 custody and separately approved P4 Collector/CLI/privacy policy. Do not infer them from Post-D2 success. The ADR-040 as-of observation is bound to successful non-review `VERIFYING -> READY_TO_INTEGRATE` only.

## 3. Current evidence and dependency gates

| Gate | Precondition and minimum future proof | Current limit |
| --- | --- | --- |
| **P0** source admission | Independently bounded source identity, launch/origin controls, all old-v2 starts and aliases excluded, continuous denial of new writable opens, reconciled already-open writable FDs, approved controller/TCB. | **NO_GO**. Systemd unit masks, PID lists, chmod and advisory locks alone do not suffice. |
| **W1 / P1** same-epoch as-of Seal | Compatible fenced writer, exact Verification/Evidence durable bytes and parent fsync, atomic **single** SQLite Run status + events + Seal transition, source-version and frozen event boundary, retained historical exact leaves. | **NO_GO**. ADR-040 Path A / W0 accepted **design** only; overwritten old bytes without retention => unavailable, not reconstructed. |
| **M0 v2→v3 controlled cutover** | Independently enforced P0 closed-world legacy start/FD exclusion, private WAL-inclusive backup and durable recovery, schema-compatibility proof, verified candidate executable origin and permanent denial of old-v2 credentials; separate owner approval. | **NO_GO operational migration**. M0a–M0x are bounded designs/negative trials, not a complete P0–P9 production release. |
| **R1** source reader | Qualify nonmutating access to coherent as-of source including SQLite WAL/SHM and linked exact leaf identities, with independent transient-write audit. | **R0b route C fail-closed**. Do not flip real journal mode or use `immutable=1`/`mode=ro` as a shortcut proof. |
| **P2** issuer authentication | Separately governed keys/issuer registry, authorization, canonical receipt, revocation and anti-replay bound to actual P0/P1 evidence. | **NO_GO**. Signatures authenticate assertions, not epoch truth. |
| **P3** custody | Independently protected accepted bytes, no-clobber, durable receipt + monotonic replay state, fresh-process/crash/reboot reconciliation. | **NO_GO deployment**. P3i–P3n remain synthetic. |
| **P4** consumer/export | Valid P0–P3 and R1 (or separately accepted bounded offline diagnostic route), reviewed ADR-039 privacy/output, deterministic redacted fields and approved product semantics. | **NO_GO** for public complete Trace, verification assessments, or live CLI. |
| **Dispatch intent** | Separate durable exclusive per-attempt intent and reconciled recovery/authorization. | Design backlog; not optional telemetry and not in issue #127. |

## 4. Revised implementation order (dependency overlay, NOT a second roadmap)

1. **D0 — documentation and Git hygiene:** completed in merged [PR #128](https://github.com/ehsanrs2/projectctl/pull/128), including short README, retained feature history, doc indexes and historical-status addenda; branch deletion is still a separate operator-only housekeeping task.
2. **D1 — nonlive diagnostics:** completed in merged [PR #129](https://github.com/ehsanrs2/projectctl/pull/129); [Issue #127](https://github.com/ehsanrs2/projectctl/issues/127) closed. No P0/P1 authority implied.
3. **D2 — P0/P1/P2 actual owner decision remains open:** documentation-only [PR #125](https://github.com/ehsanrs2/projectctl/pull/125) **closed without merge as redundant**; live [Issue #124](https://github.com/ehsanrs2/projectctl/issues/124) retains D1–D5 authority/retention/issuer decisions. S3/ADR-040 remains preferred research direction and S2 is conditional; no real controller or issuer selected.
4. **D3 — disposable W1c experiment:** completed in merged [PR #131](https://github.com/ehsanrs2/projectctl/pull/131); [Issue #130](https://github.com/ehsanrs2/projectctl/issues/130) closed. Covers fenced-token refusal, exact dummy leaves and fsync order, one synthetic SQLite transition/event/Seal commit, crash/ambiguous ACK, stale and mixed bytes. **No real W1 integration, P0 or P1 provenance proven.**
5. **D4 — separate environment-specific P0/P2/P3 trials if justified:** only after explicit owner trust-topology decision, operator approval of VM/root/global policy, old-v2 start and FD challenge, issuer governance, independent custody and crash recovery. Prior VM permissions are not transferable.
6. **D5 — controlled M0 cutover decision and independent R1 reader gate:** Real v2→v3 migration is **not implied by a W1 disposable fixture**. It requires a separately approved, independently enforced old-writer/FD embargo, WAL-inclusive private backup, verified v3 schema/client compatibility and release identity, ambiguous-COMMIT reconciliation and permanent old-v2 denial. Independently prove active WAL nonmutation and exact as-of coherence before a private collector; otherwise preserve R0b C and require separate ADR/privacy acceptance for any incomplete offline diagnostic.
7. **D6 — P4 export and evaluation:** separately approve redacted bounded local CLI, schemas, destination/path constraints and supported assessment claims; no live Worker/provider research by implication.
8. **D7 — dispatch-intent and recovery enhancement:** separate owner-governed workstream if needed. Do not fold into telemetry diagnostics or assume automated retry is safe.

These are *conditional* work packages, not blanket authorizations, completion dates, or a new issue tracker. Keep `docs/PROJECT_STATE.yaml` unchanged until the owner changes the single active milestone.

## 5. Documentation and branch policies

- **Canonical landing:** [root README](../README.md); **product/roadmap authority:** [Blueprint](PROJECTCTL_BLUEPRINT.md); **active milestone authority:** [PROJECT_STATE.yaml](PROJECT_STATE.yaml); **detailed historical guide:** [FEATURE_HISTORY.md](FEATURE_HISTORY.md); **navigation:** [docs index](README.md) and [M6 index](architecture/INDEX.md).
- ADR decisions are historical records of the exact accepted boundaries. ADR-041 and [POST_D2_FEATURE_PORT](architecture/POST_D2_FEATURE_PORT.md) still describe premerge state as originally authored; **PR #126 and this ledger supersede only their status text**, not their original evidence. Early October rebaselines contain old R0-next wording; the accepted later R0b C governs current refusal.
- [Git hygiene runbook](GIT_HYGIENE.md) tracks candidate refs and operator-only ancestry/lease preflight. Protect `main`, active research/unmerged feature refs, and branch tips that do not match confirmed review evidence. PR #125 is **closed without merge**, so its branch is a possible *separately approved* cleanup candidate after confirming no downstream dependency. The already merged PR #126 branch may also be cleaned after fresh SHA/reachability checks. No Git ref deletion occurs in this documentation-only update.
- Do not auto-merge, run a real/paid Worker, perform recovery, deploy policy or reuse old root/VM permissions. Run all future CI at exact PR HEAD. No `tmux` or interactive `set -e` for operator commands.

## 6. Interpretation ceiling

- **Merged:** in main with scoped CI; not universal live safety.
- **Offline-qualified / LAB_ONLY:** fixture/model evidence, not kernel/platform/source-origin proof.
- **Accepted design:** intended invariant, not an installed implementation.
- **Operational GO:** only after independently witnessed target-specific tests + explicit owner consent; none of P0–P4 qualifies.

**Current decision:** `POST_D2_LIFECYCLE_OBSERVABILITY_MERGED_AND_POSTMERGE_CI_GREEN`; `P01_P02_W1C_LAB_ONLY_MERGED`; `P03_D1_PR_CLOSED_REDUNDANT`; `P03_D1_OWNER_DECISION_PENDING_IN_ISSUE_124`; `P0_P1_P2_P3_P4_NO_GO`; `R0B_C_FAIL_CLOSED`.


---

## 7. Engineering progress and ranked work — 2026-11-08 (estimates, NOT certified metrics)

**Pinned evidence:** [main c486e50d94858fe5ead3571e4c60e8d8eea4ba9d](https://github.com/ehsanrs2/projectctl/commit/c486e50d94858fe5ead3571e4c60e8d8eea4ba9d); [postmerge CI #42361676934](https://github.com/ehsanrs2/projectctl/actions/runs/42361676934): 2797 passed, 7 skipped, test and SDK-contract jobs success. GitHub currently lists **no open PR** and [Issue #124](https://github.com/ehsanrs2/projectctl/issues/124) as its sole open issue. Sections 1–6 above remain the dated November 4 ledger. This appendix supersedes **no accepted ADR or project state**, and grants no authority.

**Estimation rubric:** approximate expert judgment of implemented coverage within *each already declared scoped feature*, not empirical project completion, work log, schedule, security certificate or exact forecast. Uncertainty is roughly ±10–20 percentage points, possibly more for security. Different rows have different denominators; **never average them**. A passing negative test can establish a weakness, not close its operational gate. Architectural acceptance and deployed source trust must be measured separately.

### A. Existing roadmap feature coverage

| Workstream | Approximate scoped coverage | Grounded limit |
| --- | --- | --- |
| M0–M1: bootstrap, RunStore, claims, single-run, independent verify/integrate/recover | **90–95%** | Implemented, CI-covered within documented scope; this is NOT the new M6 M0 v2→v3 cutover. |
| M2: quota/auto/checkpoint | **85–95%** | Bounded automation/quotas; cost modeling, external operator approval, new providers not silently provided. |
| M3: task authorities/delivery | **80–90%** | GitHub and Jira execution capabilities, Linear read/eligibility only and intentionally unsupported lifecycle writes. |
| M4: account-global admission, portfolio, safe concurrency, unified turns | **90–95%** | M4.2a/b completed; account-global worker turns remain serialized intentionally. |
| M5–M5.2: derived context, human-reviewed scope, enforcement | **90–95%** | Explicit human scope remains authoritative; derived suggestions do not grant permission. |
| Post-D2 / ADR-041: offline audit/measurements | **95–100% of its deliberately bounded feature** | #126/#129 merged and postmerge tested; no current live-WAL claim, exclusive dispatch-intent journal or retry authority. |
| M6: schema/private reader/pure Seal *foundation* only | **65–80% of foundation** | Public schema, strict historical validators, rollback-only private reader and synthetic Seal/fault tests; no public Collector. |
| M6: full trust-qualified as-of Trace Export *end to end* | **25–35% design/lab-weighted progress** | **Zero of P0–P4 operational gates admitted**; this percentage is neither a deployment readiness score nor a likelihood of success. |

### B. M6 proof chain, deliberately separating lab maturity from operational GO

| Dependency | Estimated design/lab maturity | Operational gate / principal gap |
| --- | --- | --- |
| P0 trusted source admission | ~20–30% | **NO_GO**. M0l–M0x demonstrate FD, independent start, same UID+private GID, code-origin, LSM and recovery gaps; no independently held continuous barrier. |
| W1/P1 genuine as-of Seal | ~30–40% | **NO_GO**. [#131](https://github.com/ehsanrs2/projectctl/pull/131) is a participating-writer disposable fixture. No actual fenced W1 source publisher/retention/epoch authority. |
| M0 controlled v2→v3 cutover | ~25–35% | **NO_GO**. Rehearsals do not prove all old writers/FDs excluded, migration compatibility or privileged recovery. |
| R1 supported nonmutating source reader | ~15–25% | **R0b C_FAIL_CLOSED** for active WAL; bounded private rollback readers and detached probes do not prove source+JSON epoch coherence. |
| P2 authenticated issuer | ~15–25% | **NO_GO**. Receipt, syntax and replay lab only; no independently governed real keys/issuer/authorization. |
| P3 protected custody | ~35–45% | **NO_GO deployment**. P3i–P3n synthetic no-clobber/reboot only; no protected real-source package or anti-rollback root. |
| P4 Collector/CLI/verified assessments | ~15–25% | **NO_GO**. Trace v1 schema/privacy contract exists, but end-to-end detached consumer, safe output and independent evaluation claims absent. |

### C. Strategic scope choice before expensive implementation

**Two deliverables must not be confused:**

- **M6a, restricted incomplete offline diagnostics (candidate only):** A separately accepted derived, local, strictly privacy-redacted trace from a **proven supported non-mutating offline or quiescent input**. It must refuse unsupported live WAL, emit explicit unknown/incomplete/indeterminate classifications and `assessments=[]`. Reuse ADR-039, Post-D2 and historical readers. It **cannot** claim P0/P1/P2/P3 external attestation, latest state, safe Retry or verified provider completion. No public CLI is currently authorized. Order-of-magnitude effort **6–15 engineer-days** after input/privacy acceptance; high risk if no safe source input is available.
- **M6b, full trusted as-of provenance (current ambitious architecture):** ADR-040 Path A is preferred as *design*. Real P0 admission, W1/M0 change, R1 nonmutation, P2 issuer, P3 custody and P4 product release are unproved. Total **40–100+ engineer-days** is only a very uncertain one-contributor engineering-effort range, excluding external approvals and unknown topology difficulties. The chosen environment may make it infeasible. This is NOT a promised duration.

**Architectural caution:** The accepted ADR-039 goal is a **non-authoritative local derived export**; imposing signed independently protected provenance on *every* incomplete diagnostic could inflate scope needlessly. But an incomplete diagnostic may never masquerade as a trusted current snapshot. Splitting a deliverable or acceptance target requires explicit human review; this appendix does not revise ADR-039/040 or authorize the shorter path.

### D. Ranked priorities and stop conditions

| Priority | Smallest useful next unit | Exit and dependency | Very approximate engineering effort |
| --- | --- | --- | --- |
| **P0 — FIRST** | Decide on M6a incomplete diagnostic, M6b trusted as-of, or **two separately named tiers**. Use the *existing* [Issue #124](https://github.com/ehsanrs2/projectctl/issues/124) and accepted ADRs; no new duplicate architecture document. | Explicit allowed source input and truthful output labels, plus a fail-closed stop path for each tier. This decision precedes any privileged pilot or public CLI. | **1–3 engineer-days** review and scoped source inventory |
| **P1 — EARLY** | Time-box only the **new** reader/input feasibility gap using existing R0b/B1/B2 evidence; do not repeat known WAL-unsafe approaches. | Qualify a supported detached/quiescent non-mutating input **or reject**. Negative result is legitimate. | **3–8 engineer-days**; high uncertainty |
| **P1 — IF M6b** | Choose/test bounded P0 controller/TCB in a disposable Debian KVM guest, with explicit separate approval before root/systemd/AppArmor. Model A is valid only if untrusted actors cannot obtain *both* writer credentials or escaped writable FDs; a unit-local AppArmor label is not global protection. | Independent denial of old starts/new opens, preopened/SCM_RIGHTS FD/alias challenges, credential/code provenance and durable recovery. Any bypass => NO_GO. | **3–6 days pilot design; 8–20+ days** guest-only evidence if authorized |
| **P2 — AFTER P0** | Implement and test real W1 single status+event+Seal transaction and separately gated M0 v2→v3 migration (or reviewed cooperative alternative). | Protected exact bytes, durable published Seal, old writer exclusion and backup/ambiguous-commit recovery. | **12–30+ days** |
| **P2 — AFTER SAFE SOURCE** | R1 coherent as-of read with independently audited no-mutation of source DB/WAL/SHM/metadata. | Supported nonmutating input or preserved R0b option C; no fake `current`. | **7–15+ days**, may be infeasible |
| **P3** | Independently governed P2 authentication + P3 custody and then P4 redacted export. | Valid provenance, no-clobber/replay protection, safe deterministic local output and supported evidence claims. | **15–35+ days** |
| **P4 / DEFER** | Durable exclusive dispatch-intent, more providers, D2 statistical comparison, optional old branch hygiene. | Separate ROI/safety decision; not a prerequisite for initial bounded Trace. | No estimate without accepted scope |

**Recommended order:** (1) resolve one concrete **product/trust tier** decision in #124; (2) qualify one safe input, preserving fail-closed; (3) implement a narrow diagnostic vertical slice *if independently accepted*, or the separately authorized real P0 enforcement pilot if full trusted path is selected; (4) proceed to W1/M0→R1→P2/P3→P4. Avoid another self-hashed receipt or one-more-journal negative-model PR unless it uniquely closes a new admission obstacle.

**Unchanged stop line:** `P0_P1_P2_P3_P4_NO_GO`; `R0B_C_FAIL_CLOSED`; no real worker/provider call, source DB migration, root policy install, actual guest reconfiguration, key enrollment, public Trace or implied approval from a percent estimate. `docs/PROJECT_STATE.yaml` remains the single active-goal authority.

---

## 8. 2026-11-11 M6a G4a focused operator witness (lab only)

**Owner-reported local execution:** On ordinary-user Debian at `$HOME/projectctl-m0k-lab`, the operator ran the exact-head, `&&`-guarded command previously reviewed for [PR #145](https://github.com/ehsanrs2/projectctl/pull/145). The command required a clean checkout, fetched `origin/experiment/m6a-g4a-stdin-stdout-optin-preview`, pinned `363287c4f30935af70d38820c4e772177d4d0227`, and invoked `pytest -q -rs` with exactly these three files:

- `tests/test_m60m6a_g2_private_byte_diagnostic.py`
- `tests/test_m60m6a_g3_private_envelope.py`
- `tests/test_m60m6a_g4_stdin_preview.py`

The provided terminal excerpt showed `HEAD is now at 363287c`, pytest progress through `[100%]` without visible failing markers, and the final guarded sentinel **`LOCAL_M6A_G4_PASS`**. This is **owner-reported focused local evidence**, not an independently captured local log or an exhaustive hardware/filesystem attestation. The prior [exact-head CI #43005752828](https://github.com/ehsanrs2/projectctl/actions/runs/43005752828) independently completed **2,907 passed / 7 skipped** and SDK-contract success for that commit. A later evidence-only commit requires its own exact-head CI before merge.

**Credit:** The owner explicitly reports that the focused test was performed with help from Reza Souri; the commit recording this evidence carries the requested `Co-authored-by` Git trailer. This statement does not assert authorship of all earlier commits or retroactively change their metadata.

**No promotion:** This remains `M6A_G4_PREVIEW_LAB_ONLY`. The script consumes caller-provided synthetic test bytes and produces a redacted, explicitly opted-in and locally correlatable stdout preview; it does **not** prove trustworthy source acquisition, absence of live writes, one DB+JSON epoch, authenticated provenance or custody, readiness for installed/public `projectctl trace export`, or any supported assessment. `P0_P1_P2_P3_P4_NO_GO` and `R0B_C_FAIL_CLOSED` remain unchanged. [Issue #144](https://github.com/ehsanrs2/projectctl/issues/144) stays open until independent review, merge, and postmerge CI.
