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
