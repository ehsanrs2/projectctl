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
| [P03-D1 PR #125](https://github.com/ehsanrs2/projectctl/pull/125) / [Issue #124](https://github.com/ehsanrs2/projectctl/issues/124) | Independent P0/P1/P2 witness authority topology decision draft, originally based on pre-#126 main. | **DRAFT; OWNER_DECISION_REQUIRED**. Recheck base and reconcile ADR-041 before merge. |
| [Issue #127](https://github.com/ehsanrs2/projectctl/issues/127) | Duplicate optional telemetry-file path produces FileExistsError outside the CLI's ProjectCtlError handler. | **OPEN P3 UX defect**, fix in separate nonlive regression PR. |

## 2. Two distinct observation products

**Implemented Post-D2 (ADR-041):** the derived read-only `projectctl run audit` checks supported RunStore, manifests and Git evidence. State `observed` means the stated local check passed; it does **not** mean a coherent atomic snapshot or authorization. `proposed_stage` is advisory, `permitted_action=inspect`, `dispatch_authorized=false` and `implicit_retry_allowed=false`. Its reader refuses unsupported live-WAL headers (unknown/no stage suggestion). Opt-in `--measurements PATH` on already separately authorized `start|resume|verify|integrate` records overlapping monotonic durations and scoped SDK usage; it is not a durable exclusive dispatch-intent journal, provider-cost proof, live task-store status or retry authority. This feature was selectively ported from research preserving main's quota/resource_class and WorkerOutputPayload schema.

**Separate M6.0 Trace Export (ADR-039 and ADR-040):** pure Trace contracts, historical artifact validators, test readers, synthetic Seal/receipt/custody labs exist. Still missing: an actual fenced W1 source writer, source-attested coherent P0/P1 as-of epoch, verified nonmutating R1 active-WAL read, independent P2 issuer/P3 custody and separately approved P4 Collector/CLI/privacy policy. Do not infer them from Post-D2 success. The ADR-040 as-of observation is bound to successful non-review `VERIFYING -> READY_TO_INTEGRATE` only.

## 3. Current evidence and dependency gates

| Gate | Precondition and minimum future proof | Current limit |
| --- | --- | --- |
| **P0** source admission | Independently bounded source identity, launch/origin controls, all old-v2 starts and aliases excluded, continuous denial of new writable opens, reconciled already-open writable FDs, approved controller/TCB. | **NO_GO**. Systemd unit masks, PID lists, chmod and advisory locks alone do not suffice. |
| **W1 / P1** same-epoch as-of Seal | Compatible fenced writer, exact Verification/Evidence durable bytes and parent fsync, atomic **single** SQLite Run status + events + Seal transition, source-version and frozen event boundary, retained historical exact leaves. | **NO_GO**. ADR-040 Path A / W0 accepted **design** only; overwritten old bytes without retention => unavailable, not reconstructed. |
| **R1** source reader | Qualify nonmutating access to coherent as-of source including SQLite WAL/SHM and linked exact leaf identities, with independent transient-write audit. | **R0b route C fail-closed**. Do not flip real journal mode or use `immutable=1`/`mode=ro` as a shortcut proof. |
| **P2** issuer authentication | Separately governed keys/issuer registry, authorization, canonical receipt, revocation and anti-replay bound to actual P0/P1 evidence. | **NO_GO**. Signatures authenticate assertions, not epoch truth. |
| **P3** custody | Independently protected accepted bytes, no-clobber, durable receipt + monotonic replay state, fresh-process/crash/reboot reconciliation. | **NO_GO deployment**. P3i–P3n remain synthetic. |
| **P4** consumer/export | Valid P0–P3 and R1 (or separately accepted bounded offline diagnostic route), reviewed ADR-039 privacy/output, deterministic redacted fields and approved product semantics. | **NO_GO** for public complete Trace, verification assessments, or live CLI. |
| **Dispatch intent** | Separate durable exclusive per-attempt intent and reconciled recovery/authorization. | Design backlog; not optional telemetry and not in issue #127. |

## 4. Revised implementation order (dependency overlay, NOT a second roadmap)

1. **D0 — documentation and Git hygiene (this documentation PR):** shorten landing README, preserve full historical feature reference, give navigable docs index/architecture index, reconcile #126 and gate status, clarify historical PR-pending texts in ADR-041 and early M6 plans without falsifying their provenance. CI checks and path review.
2. **D1 — nonlive diagnostics PR for #127:** catch only duplicate telemetry artifact errors before invoking stage; sanitized fixed CLI message, predictable nonzero exit, preserve existing bytes and every stage authority gate; focused and full CI. This is not on the P0/P1 trust critical path.
3. **D2 — P03-D1 decision before privileged work:** review open #125 against new main, choose or decline a scoped independent P0 controller/TCB, exact P1 source producer/retention, and P2 issuer split. Existing S3 cooperative as-of writer preferred as **research direction**; S2 atomic snapshot conditional; S1 sequential copy/S4 DB-only checksum insufficient. No actual issuer or topology chosen by this memo.
4. **D3 — one separately scoped disposable W1/P1 transaction experiment:** reuse W1a/W1b assets, demonstrate fenced token rejection, durable exact leaf publication, one DB transition/event/Seal commit, split-commit failure, overwritten historical leaf refusal, ambiguous COMMIT and as-of vs current semantics. Ordinary user only until a new approval authorizes any privileged pilot.
5. **D4 — separate environment-specific P0/P2/P3 trials if justified:** only after explicit owner trust-topology decision, operator approval of VM/root/global policy, old-v2 start and FD challenge, issuer governance, independent custody and crash recovery. Prior VM permissions are not transferable.
6. **D5 — independent R1 reader gate, then private collector:** prove active WAL nonmutation and exact as-of coherence; otherwise keep R0b C and consider incomplete diagnostic-only offline input only through a new ADR/privacy acceptance.
7. **D6 — P4 export and evaluation:** separately approve redacted bounded local CLI, schemas, destination/path constraints and supported assessment claims; no live Worker/provider research by implication.
8. **D7 — dispatch-intent and recovery enhancement:** separate owner-governed workstream if needed. Do not fold into telemetry diagnostics or assume automated retry is safe.

These are *conditional* work packages, not blanket authorizations, completion dates, or a new issue tracker. Keep `docs/PROJECT_STATE.yaml` unchanged until the owner changes the single active milestone.

## 5. Documentation and branch policies

- **Canonical landing:** [root README](../README.md); **product/roadmap authority:** [Blueprint](PROJECTCTL_BLUEPRINT.md); **active milestone authority:** [PROJECT_STATE.yaml](PROJECT_STATE.yaml); **detailed historical guide:** [FEATURE_HISTORY.md](FEATURE_HISTORY.md); **navigation:** [docs index](README.md) and [M6 index](architecture/INDEX.md).
- ADR decisions are historical records of the exact accepted boundaries. ADR-041 and [POST_D2_FEATURE_PORT](architecture/POST_D2_FEATURE_PORT.md) still describe premerge state as originally authored; **PR #126 and this ledger supersede only their status text**, not their original evidence. Early October rebaselines contain old R0-next wording; the accepted later R0b C governs current refusal.
- Branch cleanups require proof: protect `main`, active PR #125 branch and unique unmerged research/feature refs. `feature/post-d2-lifecycle-observability` is a candidate for deletion only after checking the PR merge SHA and matching remote branch SHA/reachability; delete remote by explicit operator action, then `git fetch --prune`. No branch deletion inside this documentation PR.
- Do not auto-merge, run a real/paid Worker, perform recovery, deploy policy or reuse old root/VM permissions. Run all future CI at exact PR HEAD. No `tmux` or interactive `set -e` for operator commands.

## 6. Interpretation ceiling

- **Merged:** in main with scoped CI; not universal live safety.
- **Offline-qualified / LAB_ONLY:** fixture/model evidence, not kernel/platform/source-origin proof.
- **Accepted design:** intended invariant, not an installed implementation.
- **Operational GO:** only after independently witnessed target-specific tests + explicit owner consent; none of P0–P4 qualifies.

**Current decision:** `POST_D2_LIFECYCLE_OBSERVABILITY_MERGED_AND_POSTMERGE_CI_GREEN`; `P01_P02_LAB_ONLY_MERGED`; `P03_D1_OWNER_DECISION_PENDING`; `P0_P1_P2_P3_P4_NO_GO`; `R0B_C_FAIL_CLOSED`.
