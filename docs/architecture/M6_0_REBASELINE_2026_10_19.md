# M6.0 — Current implementation rebaseline and gate scorecard (2026-10-19)

**Status: PROPOSED IMPLEMENTATION REVIEW, not a new ADR or permission grant.**
**Pinned repository evidence:** merged main SHA 325fc7ef54ae29823e84f35a14397c040c9649e5, PR #96. This review is read-only. It neither overrides accepted ADR-039 or ADR-040 Path A nor changes the active M6.0 goal in docs/PROJECT_STATE.yaml. No root trial, OS policy, source DB, project writer, public CLI or release is authorized by this PR.

**Active goal:** deterministic, strictly read-only Trace & Evaluation Export from existing ProjectCTL run/verification evidence without expanding execution authority. The trace is non-authoritative. Accepted ADR-040 Path A adds a narrowly scoped *trusted writer-produced as-of Seal* at the successful non-review Verification boundary, but its operational implementation is still gated.

## 1. Definitions: evidence never automatically becomes permission

- **IMPLEMENTED_LIMITED:** production-tree logic exists for a deliberately narrow supported mode; this does not imply the end-to-end feature.
- **LAB_ONLY:** isolated tests, disposable DB, experimental code, inert template, or offline decision model; no user-facing or production authority.
- **NEGATIVE_WITNESS:** actual counterexample refuting a proposed assumption; not an accepted operational control.
- **DESIGN_ACCEPTED_ONLY:** owner-accepted architecture ADR, no corresponding deployed feature or evidence of target conditions.
- **UNVERIFIED:** missing acceptable independently checked witness for an operational gate.
- **NO_GO:** no release, policy load, v3 migration, trusted Seal producer, complete Trace or Worker authority increase.

Evidence ranking: accepted ADR/project-state constraints; checked-in real runtime at pinned SHA; exact-head CI; operator-reported bounded Debian observations; inert models. A hypothetical all-true claims structure, parser dry run, or passing unit suite is not real kernel/process attestation.

Latest merge-main [GitHub Actions #39217591787](https://github.com/ehsanrs2/projectctl/actions/runs/39217591787) succeeded in both test and pinned SDK contract jobs on the **exact** pinned SHA: **1860 passed, 6 skipped**. This does not establish real systemd/AppArmor enforcement, continuous writer exclusion, reboot recovery, source WAL/SHM nonmutation or reliable cross-store snapshots.

## 2. Unified end-to-end scorecard

| Section | What is actually present | Classification | Mandatory missing evidence |
| --- | --- | --- | --- |
| A / Trace public schema | projectctl/schemas/trace.py, trace formatting, privacy allowlist and versioned public contract | IMPLEMENTED_LIMITED | No accepted as-of proof locator or public Export CLI |
| B1 / source reader | projectctl/trace/snapshot.py handles bounded fixed no-follow artifacts and quiescent rollback-journal SQLite; validate.py emits incomplete bundles, empty assessments | IMPLEMENTED_LIMITED | Active WAL Reader and DB+files epoch proof |
| B2 / R0 live WAL | B2a detached candidate explicitly has snapshot_proven=False; R0 explores SQLite mode=ro behavior | LAB_ONLY | Independently proven nonmutation under active WAL/SHM/checkpoint and coherent sealed epoch, or formal fail-closed choice |
| B3a1–B3a4 | Private Seal model, in-memory transaction, temporary candidate v3 migration and WAL-inclusive backup labs | LAB_ONLY | Real trusted Verification Seal and approved migration/backup recovery |
| W0 / W1a / W1b | Cross-process epoch/token/fencing test, reviewed mutex protocol, real v2 RunStore consumer analysis | LAB_ONLY | All actual writer paths cooperate; real fenced lease and one-transaction status/event/Seal |
| M0a–M0c | Candidate unified v3 schema, uncooperative legacy-v2 writer counterexamples, strict offline cutover design | LAB_ONLY / NEGATIVE_WITNESS | Enforced external offline writer embargo, all-FD/start/alias closure, independently recoverable migration |
| M0d–M0n | Supervision, Landlock, process group, cgroup, mount/VM, WAL and FD negative feasibility work | LAB_ONLY / NEGATIVE_WITNESS | Actual whole-system closed-world writer and startup guarantee |
| M0o–M0s | Debian dual-UID and private writer GID design; **old code with candidate UID + private GID successfully writes in synthetic fixture** | NEGATIVE_WITNESS | Independent code-origin/credential grant and all independent actor restriction |
| M0t–M0u | Inert systemd/AppArmor templates; ordinary-user AppArmor parser smoke and hypothetical lifecycle faults | LAB_ONLY | Actual loaded enforcing policy and service-process label; no global recovery authority yet |
| M0v–M0x | Real ordinary-user SIGKILL in bounded disposable fixtures, fsynced journals and independently launched replay; owner-observed Debian results | LAB_ONLY | Outer-anchor retirement, independent controller after reboot, guest-global policy reconciliation |
| R1 / Collector / CLI / supported assessment | No trusted current exporter or public trace command | **NO_GO** | R0 decision + W1 sealed source where required + R1 safe read + ADR-039 privacy/output acceptance |

At the pinned main: projectctl/storage/sqlite.py still declares PROJECT_STATE_DB_VERSION=2 (and global v2); projectctl/storage/runs.py has no real lease_generation or lease_token; projectctl/application/verification.py writes JSON with file fsync and os.replace but no parent directory fsync, and stores event/transition separately; projectctl/trace/snapshot.py rejects WAL-header databases before opening a SQLite connection; projectctl/trace/validate.py remains always incomplete with assessments=[]; projectctl/cli/entry.py has no Trace registration. These are current source observations, not production bugs caused by dormant lab code.

## 3. Reassessment of F-01 to F-09 from the October 14 audit

Reference: [original M6.0 audit](M6_0_ARCHITECTURE_IMPLEMENTATION_AUDIT_2026_10_14.md), historically pinned to PRs #54–#65. Keep that original audit unchanged; the table below is the current scorecard.

| Finding | Original severity | Current status | Independent exit gate |
| --- | --- | --- | --- |
| **F-01** same-run writer fencing and durable JSON/Seal publication | HIGH | OPEN. W1a tests generation/token privately; real Verification still lacks required cross-process transaction protocol | W: enumerate *all* writers and aliases, persisted fencing, no-follow durable JSON plus atomic real Run/event/Seal transaction |
| **F-02** Seal/event same-run SQL integrity | HIGH | OPEN. M0a candidate SQL improves lab, no registered production Seal | W/M: typed v3 schema, same-run event FK/equivalent, deletion and history policy, real transaction/fault acceptance |
| **F-03** operational v2-to-v3 migration and recovery | HIGH | OPEN. Negative legacy-writer witnesses; only private recovery labs | M: actually enforced offline writer exclusion, unique trusted code identity, WAL backup, ambiguous commit and reboot recovery, owner authorization |
| **F-04** live-WAL source nonmutation | HIGH | OPEN. R0 is feasibility, not a supported Reader | **R FIRST:** choose and independently prove native-safe read or coherent snapshot, otherwise explicit fail closed |
| **F-05** explicit as-of/Seal locator in public trace | MEDIUM/HIGH | OPEN. Public v1 has no typed explicit Seal proof epoch | R/schema: reviewed compatible schema extension or deliberately restricted v1, no false complete |
| **F-06** L3/L4 lineage and evaluation | MEDIUM | OPEN by conservative design; assessments=[] | Later: independently prove parent/candidate/provider receipts, not structural SHA alone |
| **F-07** meaningful lifecycle event categories | MEDIUM | OPEN; run.transition and verification.passed not in finite trace event mapping | B: bounded privacy-reviewed category/format tests; unknown remains unclassified |
| **F-08** stale plan/scope ledger | MEDIUM | THIS PR addresses current plan index, not historical claims | Owner review, ledger anchored to exact main, no accepted ADR rewritten |
| **F-09** critical fault/platform test coverage | MEDIUM | PARTIAL; M0v–M0x test owned process SIGKILL but not VM reboot, power-loss, live installed kernel policy or real migration | D: isolated opt-in platform and fault matrix after concrete components exist |

Marking F-04 or F-03 PASS based on the success of a test that expects NO_GO is prohibited.

## 4. Dependency map and priority order

    Original M6.0 goal (ADR-039): local non-authoritative Trace
       |
       +-- A/B1 limited public schema, historical parser, quiescent snapshots
       |
       +-- R0 FEASIBILITY DECISION [NEXT TECHNICAL TASK]
       |     A. Source-native live-WAL read with actual nonmutation proof
       |     B. Truly coherent writer-cooperative or atomic snapshot copy
       |     C. Unsupported => fail-closed; no complete active-WAL trace
       |
       +-- Optional diagnostics for quiescent rollback-journal evidence
       |     Separate privacy, safety and owner approval; incomplete only
       |
       +-- Accepted ADR-040 Path A trusted as-of route
             W0 all-writer fencing and durable published JSON
             M0 externally controlled offline cutover and v3 migration
             W1 actual trusted verification status/event/Seal producer
             R1 sealed-as-of reader validated against external files
             Collector/CLI; only later L3/L4 independent assessments

**Ordering nuance:** Decide whether a safe Reader is *feasible* at R0 before expanding operational M0 investment; this does not imply an implementable fully trusted R1 without a real W1 Seal. R0 feasibility may end at option **C** and that negative conclusion is a useful product decision, not permission to weaken nonmutation.

### R0 next PR acceptance

- Test only fresh disposable sources, not the operator's live ProjectCTL databases, with active/idle WAL, present/absent SHM, checkpoint/rename, concurrent writers, exact DB/WAL/SHM and metadata/atime observation, no-follow/symlink and Windows/macOS portability restrictions explicitly documented.
- Distinguish DB-only transaction consistency from **database + separately published JSON** epoch consistency. Two unchanged samples or PRAGMA query_only and integrity_check are not definitive nonmutation or cross-store-epoch evidence.
- Produce one reviewed, falsifiable **A, B or C decision** with supported platform/filesystem scope and remaining nonproofs. If neither A nor B can actually be proven, record C and stop work that assumes live-WAL trusted export.
- No production SQLite hooks, trace CLI, parser/root service installation, imported credential grants, migration or policy change in this feasibility PR.

A separate intentionally limited diagnostic export could be assessed for a known **quiescent rollback-journal** fixture, but would require full ADR-039 safety/privacy/no-write evidence and explicit scoped acceptance; it cannot claim latest/live or independent verified outcomes, and is **not** authorized by this document.

## 5. Security choice and stop-work rules

**Trusted-root Model A** means the privileged VM owner exclusively provisions private writer group membership and immutable, reviewed service code. Every untrusted both-credential launch route, inherited writable FD, mutable import/environment and independent old-code path must be shown unreachable. This assumption is **not established** by M0t's unit template.

**Mandatory Model B** requires denying old code even if it gains candidate UID and private write GID. A named AppArmor profile attached only to one service does **not** confine unrelated unconfined same-credential processes. M0s proves credentials alone do not encode executable version identity. Do not install a broad system Python AppArmor profile in the shared VM.

**Pause further M0y/M0z journal-layer experiments.** M0x closes only its inner journal-unlink window. A last outer-anchor unlink still creates a residual after an interruption. Further work must first specify a separately owned, independently recoverable transaction/restore mechanism (potentially a disposable VM snapshot with verified rollback), and require new explicit operator permission for any privileged tests. The prior M0s root allowance is **not transferable**.

Stop if any of the following remain unbounded for the proposed operational topology: an old writer start route, group delegation, inherited writable FD or alias, executable/import mutation, nonunique unit/profile, missing recovery owner, unsupported live-WAL read/no-mutation claim, or absent same-epoch artifact proof. Do not relabel a test-only witness as a deployment gate.

## 6. One-PR-at-a-time decisions

| Next slice | Allowed | Exit evidence | Does NOT grant |
| --- | --- | --- | --- |
| **Rebaseline, this PR** | Docs, true current-state scorecard and linked plan only | Owner review and exact-head CI | Root, policy, migration, writer, CLI |
| **R0 feasibility, first technical PR** | Ordinary-user disposable evidence and A/B/C decision | Independent nonmutation + epoch proof or explicit C refusal | Live Reader R1, Collector |
| **Optional diagnostic concept** | Separate non-WAL, quiescent, incomplete-only design | Explicit ADR-039-based privacy and no-mutation acceptance | Trusted Seal, v3 or verified assessments |
| **W0/W1 integration design** | Inventory real writer participants and status/event/Seal transaction | No missing path in supported topology, failure-injection plans | Unsafe v2 writer release or automatic migration |
| **M0 later** | Isolated guest operational exclusion/backup decision | Independently witnessed all-writer embargo and crash/VM rollback, distinct permission | General desktop/production safety |
| **R1/Collector later** | Read exactly witnessed sealed epoch without source writes | Real W1 epoch + proven R0 mechanism + source lineage + owner approval | New Worker/provider authority |

Each later PR must have *one falsifiable hypothesis, exact witness, explicit NO_GO path, failure-case matrix and scope*. The historical R/W/M test inventory is preserved, not deleted.

## 7. Operational status must stay NO-GO

    project_v2_to_v3_operational_migration   NO_GO
    root_or_guest_global_policy_install     NO_GO
    W1_production_verification_Seal_writer   NO_GO
    R1_live_WAL_trace_reader                NO_GO
    Trace_Collector_and_public_CLI          NO_GO
    new_Worker_or_Task_authority            NO_GO

Never edit docs/PROJECT_STATE.yaml to completed, bump the DB version, auto-migrate on read, expose a complete Trace or treat passing CI as kernel proof by virtue of this rebaseline. All M0 operational P/R/T/W gates remain unverified. This scorecard is an implementation index alongside the accepted ADRs, not a replacement for them.
