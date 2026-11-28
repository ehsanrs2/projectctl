# ProjectCTL — Implementation status and dependency ledger (2026-11-04)

> **Current M6a handoff:** Section 11 (2026-11-28) assesses delivery readiness after merged G10–G12 and defines the finite next input-qualification decision. Sections 1–10 preserve their dated evidence, including the owner-approved G9A design-only protocol.
>
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

---

## 9. 2026-11-22 — M6a G5–G8 merged; G9 supported-input admission decision

**Verified baseline:** `main@b19112737457974d9368ceb763bfe40d3b096b26`, merge of [G8 PR #154](https://github.com/ehsanrs2/projectctl/pull/154) on 2026-11-22. The previous G5 [#147](https://github.com/ehsanrs2/projectctl/pull/147) and correction [#148](https://github.com/ehsanrs2/projectctl/pull/148), G6 [#150](https://github.com/ehsanrs2/projectctl/pull/150), and G7 [#152](https://github.com/ehsanrs2/projectctl/pull/152) are all merged. G5–G8 scope issues #146, #149, #151, and #153 were closed as completed; **Issue [#124](https://github.com/ehsanrs2/projectctl/issues/124) stays OPEN** because its actual producer/controller/issuer/custody trust decisions remain unmade.

**Exact G8 PR-head CI** [#45004166751](https://github.com/ehsanrs2/projectctl/actions/runs/45004166751): 2,951 passed, 7 skipped; `test` and `codex-sdk-contract` both succeeded on `a926191059e37d43805a30d7a11aee993fc146a1`. This is *not* a new independently witnessed operator run, a postmerge CI claim, or a real source-mutability assessment.

### 9.1 What has and has not been established

| Input/observation path | Evidence now available | Admission status |
| --- | --- | --- |
| Explicit caller-supplied bytes → G2/G3/G4 private diagnostic | Deterministic bounded byte processing; G4 has exact `--ack-local-correlatable` for standalone stdout and constant untrusted labels | **Private research input only**. Supplied bytes are not independently authenticated or source-qualified. No public `trace export` interface/destination accepted |
| G5 named, owner-controlled synthetic rollback DB and context JSON | `O_NOATIME` test-owned leaf reads, bounded/typed G4 input wire, sidecar refusal; G8 adds dirfd `O_NOFOLLOW` ancestor traversal | **LAB_ONLY**; even a matching basename, UID, mode, inode and metadata are not synthetic provenance or an admission authority |
| Cross-store epoch in G6/G7 A/B fixtures | Controlled mixed epoch tests and pre-pinned test-oracle digest contrast; same-actor self-resigning can match mixed data | **UNATTESTED**. Test-oracle labels do not authenticate real origin, immutable retention, writer commit or a current epoch |
| Proposed independently qualified *offline/quiescent* rollback copy of actual ProjectCTL v2 evidence | B1/B2, R0b and G1–G8 define failure cases; no approved real data source, producer, acquisition/custody topology or non-mutation witness | **OWNER_DECISION_REQUIRED; NOT ADMITTED**. No code path may read it on this evidence |
| Active v2 SQLite WAL source, or a complete trusted as-of export | R0b rejects unsupported active-WAL reads; ADR-040/W1c remain design/test-only | **NO_GO**. No `immutable=1`, native WAL connection, migration or implicit snapshot claim |

**Separate labels:** M6a can eventually be a strictly incomplete, local, non-authoritative diagnostic if its source and privacy gates are independently accepted. It need not claim M6b's L2–L4 verified epoch. Nevertheless, calling arbitrary source bytes “safe/quiescent” without proof is not allowed. Never infer source admission or source nonmutation from fixture checks, an operator-supplied inventory, permission bits, metadata polling, or a self-computed digest.

### 9.2 The next *finite* G9 admission gate (decision-ready, not implemented authority)

1. **Owner scope choice — resolved for DESIGN ONLY (2026-11-22):** The owner explicitly selected **A**: research and review a future operator-produced, already-detached and independently quiesced rollback-v2 DB plus exact allowlisted JSON as a *diagnostic-only* candidate. This approves **protocol authoring and review only**, not an actual-source trial, source access, snapshot/copy creation, producer deployment, new CLI or real writer. **B was not selected**. M6a-first priority was already accepted; do not reopen the M6a/M6b tier choice. See Section 10 for the design and its evidence gates.
2. **Acquisition/nonmutation evidence before any actual-source input:** name the source owner and acquisition producer; pin an approved controlled offline transition/quiescence procedure and its independent observer; define exact file set, origin path and copy destination, rollback header, journal sidecars, byte/capacity bounds, filesystem/OS/atime policy, known aliases and preopened writers. Verify nonmutation using evidence stronger than pre/post self-reported metadata; otherwise **reject input**, without fallback to reading the live database.
3. **Cross-store and retention semantics:** explicitly label an offline copy with `source_origin=UNATTESTED`, `cross_store_epoch=UNATTESTED`, `source_current=UNKNOWN` unless separately proven (no such upgrade exists today); no automatic “latest” claim. If exact historical JSON versions are missing or replaced, classify them as unavailable, never silently substitute current bytes. The G6/G7 mixed-pair counterexamples are mandatory negative controls.
4. **Privacy/destination decision:** independently accept the locally correlatable fields and exact output surface. Existing G4 stdout is opt-in *lab preview* only. Do not create an installed CLI, write output files, network upload or general input-path option without a separate reviewed destination/privacy contract.
5. **Narrow implementation gate only after choices and evidence:** run a scoped nonroot test matrix on explicitly approved disposable inputs; include WAL refusal, symlink/ancestor/mount/alias and concurrent mutation challenges, a source-metadata/atime audit, malformed/historical JSON, and strict no-provenance/no-assessment labels. A single unexplained source write, unapproved alias, unsupported WAL or uncontrolled mutation => **FAIL_CLOSED**. Follow with a separately reviewed Draft PR; no automatic production promotion.

**Current disposition after owner's design-only A selection:** `G9A_PROTOCOL_DESIGN_APPROVED_SOURCE_NOT_ADMITTED`. No actual-source acquisition code or privilege has been authorized by G5–G8, this ledger or the G9 plan. Existing operational decisions remain **M6b P0–P4 = NO_GO** and **R0b = C_FAIL_CLOSED**; the original [Issue #124](https://github.com/ehsanrs2/projectctl/issues/124) remains the owner control point rather than a duplicate ADR/roadmap.

---

## 10. 2026-11-22 — G9 option A: proposed OFFLINE-COPY protocol (design and review only)

**Owner instruction recorded:** Option **A** is approved **exclusively for design and review**. No command in this section is authorization to touch real ProjectCTL storage, generate or inspect actual project snapshots, stop or signal a real writer, alter journaling, change permissions, install a service/policy, access a VM, launch a provider, introduce a public CLI, or export user content. **Not a runbook for execution.** The 2026-11-22 exact design baseline is `main@b19112737457974d9368ceb763bfe40d3b096b26`, before this documentation-only Draft PR.

### 10.1 Code-grounded feasibility and trust boundary

- **Source default:** `projectctl/storage/sqlite.py::connect_db` creates the parent directory and explicitly selects `PRAGMA journal_mode=WAL`. An ordinary active `.projectctl/state.sqlite` is **not** an eligible rollback input. Reading or copying just its DB file can omit uncheckpointed WAL transactions. A source-side SQLite backup, checkpoint or `journal_mode=DELETE` would require a separate side-effect/nonmutation and writer-control approval; **none is authorized**. Never use `immutable=1` on a changing source.
- **Existing reader:** `projectctl/trace/snapshot.py::read_run_db_snapshot` recognizes rollback header bytes `01 01`, refuses unsupported live WAL before the SQLite connection, and uses source sidecar/metadata checks. These are useful local negative controls **not** proof of source nonmutation, quiescence, or a DB-plus-JSON commit epoch. `scripts/m6a_g5_detached_lab_handoff.py` admits its fixed **synthetic test-only** root and two leaves, even after G8 ancestor hardening; it must **not** be repurposed as an actual-source importer.
- **Source writer ordering:** `docs/architecture/M6_0_B2B_SNAPSHOT_CONSISTENCY_REVIEW.md` records separately committed JSON/DB transitions and missing cross-store Seal; therefore a physically coherent filesystem capture is not automatically a single committed business epoch. Existing B-Diagnostic copies and G6/G7 SHA test anchors are **not** authenticated custody evidence.
- **Diagnostic classification must remain fixed:** `source_origin=UNATTESTED`; `cross_store_epoch=UNATTESTED`; `source_current=UNKNOWN`; `source_capture_nonmutation=UNPROVEN`; `authenticated_custody=UNPROVEN`; `assessment_authority=NONE`; `assessments=[]`; completeness `incomplete` or `inconsistent`. No retry, dispatch, verification-success, provider-delivery or public export permission.

### 10.2 Proposed roles; assignment intentionally pending

| Role | Necessary independent duty | Present determination |
| --- | --- | --- |
| Source owner / scope approver | Choose *one* disposable or separately consented source instance and a defined, no-secret test objective; approve any future actual-source trial | **UNASSIGNED**; design-only permission is not this approval |
| Quiescence controller | Independently prevent both new writes and already-open/aliased writable FDs, including legacy v2 processes and reconnect/start paths, for the entire cut | **UNASSIGNED / UNPROVEN**. PID lists, `chmod`, same-UID cooperative locks or service stop alone fail |
| Offline-copy producer | Operate only under a separately approved, independently evidenced quiescence boundary; produce a **private detached candidate**, not an ad hoc single-file WAL copy | **UNASSIGNED**. No script, command or root policy is authorized |
| Independent observer / evidence holder | Verify prestate, continuous nonmutation while capturing, complete file membership, and poststate; hold evidence outside producer's ability to rewrite | **UNASSIGNED**. Source and copy hashes generated by the producer alone do not create this role |
| Private diagnostic reviewer | Review exact offline candidate compatibility, privacy/destination policy and typed refusal outcomes without opening the real source | **REVIEW ONLY**. G2–G5 are not an accepted production intake interface |

No assumption that a second account on the same machine or a self-signed receipt automatically constitutes independent custody. Bind mounts, directory ancestry/aliases, source filesystem, atime behavior and same-credential writer access must be included in the trust model.

### 10.3 Proposed stages and mandatory fail-closed holds

| Stage | Design-only qualification evidence | Stop / refusal boundary |
| --- | --- | --- |
| **H0: explicit source-scope approval** | Document source owner, project/run scope, version, lawful handling/privacy basis, designated roles, isolation topology and precisely which destination is allowed; no real path/secret in public Issue/CI | No explicit later trial approval, wrong source, privilege ambiguity or missing privacy decision → **STOP** |
| **H1: independent quiescence proof** | Controller/observer specify how all old and new writer entry points, credentials, preopened/SCM_RIGHTS FDs, symlink/mount aliases, WAL/SHM/journal and recovery/restarts are continuously excluded; enumerate failure/boot scenarios and evidence artifacts | Unsupported controller/TCB, writer still able to mutate, or merely inferred inactivity → **STOP**. No real stop or service control under this design permission |
| **H2: exact detached candidate definition** | Propose allowlist of rollback-v2 SQLite and schema-versioned source leaves (initial diagnostic subset: DB plus Context; further evidence kinds separate), bounded raw sizes, run/task/project identity and missing-leaf policy; record whether raw WAL/SHM/hot journal are absent or unsupported | Active WAL header, residual WAL/SHM/hot journal, unknown leaf/alias, or inconsistent/missing bytes → **REFUSE**. Converting live source WAL or copying DB alone is **not** a fallback |
| **H3: non-mutating source acquisition witness** | Before any future trial, independent OS/VFS/filesystem-level method must observe content, directory entries and metadata including atime during the **entire** acquisition, plus sidecar creation/deletion/temporary changes and mount aliases. Pre/post SHA, stat and producer logs are supporting observations, not a proof | Any unexplained access-time mutation, metadata write, transient sidecar, checkpoint, journal conversion or uncontrolled gap → **REFUSE**; unknown visibility also → **NOT QUALIFIED** |
| **H4: detached retention and integrity** | Source-to-copy identity witness plus raw byte fingerprints retained by an independently controlled holder; exact file membership and version labeling; no-clobber and cleanup/retention limits agreed separately | Inability to attest correct candidate membership or retained exact bytes → **REFUSE**. A rehashed forged inventory is not a source witness |
| **H5: isolated offline interpretation** | Only a **future separately reviewed** private consumer of already detached, allowed rollback bytes may run; prove it cannot reach source paths/network and remains bounded/redacted/non-authoritative; malformed/historical or mixed-epoch test fixtures stay negative controls | No newly approved consumer or destination, unsupported WAL, cross-project identity mismatch, unbounded bytes, raw payload disclosure or false `current`/assessments → **REFUSE** |
| **H6: audit and rollback** | Typed outcome record (pass / refuse / unavailable / unsupported), independent evidence references, documented deletion/retention of sensitive detached bytes, no source mutations and incident response on unexpected writes | Any ambiguous exit, privacy leakage, uncontrolled temporary file or unverifiable cleanup → **STOP / QUARANTINE** |

A **design review may pass H0–H6 as specified controls**, but it cannot label **any actual source as admitted** without separate execution authorization and empirical evidence. No stage changes `R0b C_FAIL_CLOSED` or the unchanged M6b P0–P4 gates.

### 10.4 Evidence fields for a *future* review packet (not a new runtime schema)

| Evidence field | What reviewer needs | Prohibited inference |
| --- | --- | --- |
| `review_scope`, `source_kind`, `source_version`, `run_scope` | Explicit source/run boundary and known v2 / historical artifacts; sensitive identifiers kept private | A field value is not a verified origin |
| `owner_approval_ref`, `controller_ref`, `observer_ref` | Separately approved and independently checked responsibilities | No self-signed issuer or unreviewed account equivalence |
| `quiescence_window`, `writer_fd_exclusion_evidence` | Evidence of exclusion across writer startup/restart/FD aliases for whole window | A process snapshot does not prove closed-world quiescence |
| `filesystem_vfs_policy`, `nonmutation_evidence` | OS/fs, mount/alias topology, atime and transient write/sidecar monitoring method | Pre/post inode/hash checks alone cannot prove zero transient writes |
| `candidate_allowlist`, `raw_byte_sha256`, `missing_leaves` | Bounded exact DB/JSON membership retained privately for comparison | A matching hash cannot prove same-epoch or unforgeable source |
| `privacy_surface`, `retention_expiry`, `cleanup_evidence` | Local output/destination, correlatable fields, retention and confirmed deletion policy | The existing opt-in G4 lab stdout is not a production privacy approval |
| `refusal_codes`, `open_gaps`, `review_disposition` | Explicit typed stop reasons, unknown assumptions, exact reviewer approval status | CI success cannot turn an unapproved actual source into a safe one |

**Evidence security:** Do **not** commit actual project paths, payloads, hashes that enable correlation, credentials, host/user identity or copies to public GitHub. Retained copies remain private and limited by a separately accepted handling policy. No logger/CLI interface is added by defining these review fields.

### 10.5 Mandatory adversarial acceptance matrix (design tests; NOT executed)

1. **Active WAL** header `02 02`, residual `-wal/-shm`, missing SHM and hot `-journal`: **REFUSE**, do not invoke SQLite VFS on source or attempt repair/checkpoint.
2. **Writer concurrency** across a claimed stop, restart, inherited writable FD, alternate interpreter/code origin, aliased path and same-UID/private-GID actor: if denial is not independently demonstrated for the entire cut, **NOT QUALIFIED**.
3. **Intermediate symlink, bind mount, hardlink, inode swap, TOCTOU/ABA** and source-to-detached identity mismatch: **REFUSE / UNKNOWN**; G8's no-symlink observed walk does not cover mounts.
4. **Pre/post-equal tampering** or transient WAL/SHM creation between observations, including atime-only source metadata changes: **REFUSE if witnessed; NOT QUALIFIED if unobservable**.
5. **Partial publication:** DB(A)+JSON(B), DB(B)+JSON(A), producer-rehashed inventory, stale retained leaf or missing historical artifact: do not claim an epoch; preserve `UNATTESTED`, report missing/inconsistent where independently detected.
6. **Historical/malformed schema, wrong run/project identity, oversize artifact or unknown input leaf:** **REFUSE** or typed invalid/unsupported, never coerce to current schema.
7. **Privacy violation, nonlocal destination, raw event/prompt/secret, unapproved output flag:** **REFUSE**; exact opt-in G4 output stays lab-only and locally correlatable.
8. **Crash, partial private candidate, producer/observer disagreement, uncertain teardown:** **STOP / QUARANTINE**, neither silent retry nor promotion to a complete Trace.

A passing **future** nonroot disposable test suite is necessary but not sufficient for a real offline source admission. No real file or source system is accessed during this proposal. The broader M6b trusted P0/P1/W1/R1/P2/P3/P4 path remains separately governed by ADR-040 and Issue #124.

### 10.6 Design-review disposition and next authorized work

**Approved now:** document and review the A-path protocol, negative controls and explicit evidence checklist; existing private synthetic code and docs may be read for context. **Not approved now:** live source reads or copies, journal conversion on source, root/VM policy changes, new active source-reader implementation, source/reader credential enrollment, public export/CLI or user-data transfer.

**Review exit:** `G9A_OFFLINE_COPY_PROTOCOL_REVIEW_READY_SOURCE_NOT_ADMITTED` if the owner can assess H0–H6 and the adversarial matrix with unresolved roles marked honestly; **not** `SOURCE_ADMITTED`. **Next separate authorization** (only if later explicitly granted): choose a disposable/sanitized trial source and independently controlled capture/observer topology, privately pin filesystem/OS requirements and privacy handling, then design a bounded test-only proof before any actual-source bytes are touched.

**Standing status:** `M6a=INCOMPLETE_DIAGNOSTIC_RESEARCH_ONLY`, `M6b P0–P4=NO_GO`, `R0b=C_FAIL_CLOSED`. The consent to **design** option A is not consent to **execute** it.

---

## 11. 2026-11-28 — G13 M6a delivery readiness after G10–G12

**Evidence baseline:** `main@37878226506dd128d62042f7236ac26bb261f645`, merged G12 [PR #161](https://github.com/ehsanrs2/projectctl/pull/161). The active M6.0 goal in [PROJECT_STATE.yaml](PROJECT_STATE.yaml) remains unchanged. This is a delivery-readiness review, not a second roadmap, new ADR, new source authority or release approval.

### 11.1 Reconcile the intervening owner scope and evidence

G9A [#155](https://github.com/ehsanrs2/projectctl/pull/155) merged 2026-11-25 at `b0164120de5639b49e458e0fb523b965f4051b13`. The owner subsequently authorized a **bounded synthetic-only trial**; G10–G12 executed in hosted CI on test-generated fixtures, not a user project, target guest, actual-source acquisition or root/global policy. That limited permission does not lift H0–H6 for real inputs.

| Stage | Verified merged evidence | What it establishes / what it does not |
| --- | --- | --- |
| G10-D1 [#157](https://github.com/ehsanrs2/projectctl/pull/157) | `dc1d6c2197c0b4619ecc688c5ff5808afac4d85d`; [PR-head CI](https://github.com/ehsanrs2/projectctl/actions/runs/45564631142) and [postmerge CI](https://github.com/ehsanrs2/projectctl/actions/runs/45586869320): 2956 passed / 7 skipped | Known committed WAL-only fixture event survives normalization on a fresh writable clone; exact G4 output agrees with a separately constructed logical fixture oracle. Missing/truncated/altered WAL rejected against a test-held pin. DB-only stale clone can still pass integrity. No independent acquisition/custody or full transaction-history proof |
| G11 [#159](https://github.com/ehsanrs2/projectctl/pull/159) | `5a5324515c23c3bacc72889f55e660642c8a289b`; [PR-head CI](https://github.com/ehsanrs2/projectctl/actions/runs/45587192727) and [postmerge CI](https://github.com/ehsanrs2/projectctl/actions/runs/45602719853): 2959 passed / 7 skipped | On covered Linux x86_64 nonroot fixtures, process-local Landlock ABI >= 3 restricts handled new file accesses while clone normalization succeeds. Inherited FD and utime negative controls explicitly expose limitations |
| G12 [#161](https://github.com/ehsanrs2/projectctl/pull/161) | PR head `d2a9c02ab5e28fabbc62b78b2c53518952410793`; [PR-head CI](https://github.com/ehsanrs2/projectctl/actions/runs/46111898405): 2961 passed / 7 skipped, both jobs succeeded | G11 + libseccomp: four native timestamp setter syscalls denied, including in-clone operations, while exact G4 equality survives. No general syscall allowlist, network isolation, inherited-FD revocation, implicit metadata guarantee or external writer exclusion |

Counts are suite-level hosted CI observations, not separate focused test logs, exhaustive platform coverage or an independent target-host witness. G12 postmerge CI is not asserted here. G10–G12 experiment issues #156/#158/#160 are completed; #124 remains open.

### 11.2 Product boundary and requirements-to-evidence traceability

M6a's first useful deliverable remains **local, explicitly incomplete, assessment-free diagnosis of independently qualified detached input**. It is not M6b's authenticated, coherent Verification as-of export. Its source-safety requirements are real; L2–L4 epoch/issuer/verified-delivery claims need not be proved merely to report unknowns. Keep every false authority flag and conservative reason code.

| Requirement for M6a | Existing implementation / evidence | Readiness / next consequence |
| --- | --- | --- |
| Byte-only diagnostic and v2 structural/historical validation | G0/G2; private `scripts/m6a_g2_private_byte_diagnostic.py`, B1 historical validation; memory-only SQLite, bounded bytes and VM instructions | **LAB PROVEN** for tested fixtures. No hard OS memory/CPU proof or public support commitment |
| Deterministic locally correlatable redaction and refusal | G3/G4 private envelope and explicit stdout ack; ADR-039 local privacy baseline | **LAB PROVEN**; final destination and allowed fields for actual data still need acceptance. No raw payload, network or file destination |
| Bounded non-following detached file acquisition | G1/G5/G8, fixed fixture directory/leaves, O_NOATIME, no sidecars, ancestor dirfd traversal | **LAB PROVEN** for sampled conditions. Not proof against mounts, transient changes, ABA or real origin; no generic importer |
| Preserve WAL-inclusive fixture commit on an isolated copy | G10-D1, reuse B2a/B3a4; G2 still refuses WAL | **LAB PROVEN** for known single event; D1 capture completeness remains unproved. Normalizing a clone does not certify the raw capture |
| Restrict normalization child | G11/G12, process-local handled-rights restriction and explicit timestamp denylist | **PARTIAL LAB EVIDENCE**; no complete sandbox, independent controller, network denial, hard resource envelope or metadata nonmutation. Do not equate with H1/H3 |
| Independent source selection, quiescence and no mutation | H0–H3; prior M0/R0/B2 negative evidence | **BLOCKED**; no approved actual-source topology, externally held barrier or capture proof. Primary delivery blocker |
| Private retained candidate, independent observation and failure handling | H4/H6; G7/G10 fixture pins, earlier custody/recovery labs | **BLOCKED** for actual-source acquisition; test-held digest is not independent custody, crash/restart/teardown remains unqualified |
| Honest epoch and freshness semantics | G6/G7, B2b, G2/G3/G4 | **LAB PROVEN refusal to promote**; retain UNATTESTED/UNKNOWN. No requirement to fabricate L2/L3 evidence for M6a |
| Usable local product interface | G4 standalone experimental preview | **NOT RELEASED**. No registered CLI, supported source contract, release privacy acceptance or independent end-to-end admission |

Do not sum or average these rows into a release-readiness percentage: the unresolved source and release gates are mandatory. The earlier rough estimates in §7 remain historical.

### 11.3 Finite next decision: qualify one source boundary, not another sandbox layer

Compare three routes against H0–H6 and the owner's M6a-first priority:

| Route | Design decision | Why |
| --- | --- | --- |
| **D0 / first qualification target** | A newly generated, deliberately rollback-v2 disposable source with fixed Context JSON, on a dedicated test-only storage image outside any real project. Independent controller/observer outside the fixture writer's process/credential boundary. | Minimizes moving parts and directly tests the source-acquisition boundary missing from G1–G12. Does not solve WAL-default production capture |
| **D1 / conditional later extension** | A separately approved, independently frozen WAL-inclusive raw candidate; preserve raw bytes apart from mutable clone and normalize only the clone | G10 already supplies logical downstream feasibility. Need first to demonstrate source freeze, complete membership and independently observed nonmutation; no live source read fallback |
| **Stop at private byte-only research** | Continue G2–G4 on synthetic data without claiming a safe actual source | Honest fallback if no trustworthy isolation/controller or observer can be established. Not a shipped M6a product |

**Recommended G14 target (proposal, not authorized execution):** choose D0 first for a single deliberately disposable, independently controlled offline-source pilot. Prefer an externally controlled, powered-off disposable guest/disk image with no shared writable host mounts and a separately observed read-only source boundary over relying on an in-guest process scan, chmod or a same-UID lock. This is a proposed topology, not a verified capability of the owner's environment. Host/hypervisor/storage controller and observer trust assumptions, image backing-chain identity, exclusion of other host writes, read-only mapping/filesystem journal/recovery behavior, atime policy, raw-data handling and cleanup must be independently reviewed. A powered-off guest by itself does not prove host-side write exclusion or nonmutation. No privileged action, VM or actual data operation is part of G13.

**Acceptance sequence:** (1) explicit owner approval of the concrete disposable environment, controller/observer roles, authorized operations and privacy/retention boundary; (2) independently review the exact fixture/image identity, writable alias and already-open FD exclusion, cold/offline state and observation method before capture; (3) one bounded capture with an independently held expected fixture reference and positive/negative evidence for H0–H4/H6; (4) only if qualified, feed separately retained rollback bytes to existing G2–G4 in the approved local destination, check deterministic output and unchanged authority labels; (5) report evidence and refuse any unexplained source change, unobserved barrier, uncertain recovery or privacy violation. Do not allow arbitrary source paths, mount a real disk, grant new credentials, or silently retry. Separate approval required for any root/hypervisor/storage action. If the chosen environment cannot support independent evidence, record **NO_GO** rather than repeating G10–G12.

### 11.4 Exit and governance

**G13 disposition:** `G13_M6A_LAB_CHAIN_REVIEWED_SOURCE_QUALIFICATION_BLOCKED`. G10–G12 do not change R0b C or the accepted ADR-039/040 designs. Stop incremental denylist expansion as the primary research path. The next meaningful decision is the scoped, independently observed D0 pilot under #124; once it qualifies, consider the narrowly bounded M6a local interface and release review. D1 remains a separate extension and M6b remains separately gated.

`M6A_ACTUAL_SOURCE_NOT_ADMITTED`; `M6b P0–P4=NO_GO`; `R0b=C_FAIL_CLOSED`. No source access, user-data transfer, VM/root operation, worker/provider dispatch, runtime schema, migration or public CLI authorized by this review. #124 is deliberately left open.
