# M6.0 architecture index — provenance, source safety, custody and export

**Navigation, not a new ADR or execution gate.** See the [dated implementation status](../IMPLEMENTATION_STATUS.md), [Blueprint](../PROJECTCTL_BLUEPRINT.md) and [PROJECT_STATE.yaml](../PROJECT_STATE.yaml). Every historical file retains its own reviewed status and version; a document named “proof”, “lab”, “pass”, or “design” does not itself mean operational admission.

## Governing decisions and current product split

- [ADR-039](../decisions/ADR-039-read-only-execution-trace-export.md) — local redacted non-authoritative Trace design; public R1 Collector/CLI not automatically implemented.
- [ADR-040](../decisions/ADR-040-trace-snapshot-publication-consistency.md) — accepted **design** for a narrow successful non-review Verification as-of Seal; real writer/epoch source not implemented.
- [ADR-041](../decisions/ADR-041-offline-lifecycle-audit-and-measurements.md), [Post-D2 observability](POST_D2_LIFECYCLE_OBSERVABILITY.md), [selective port record](POST_D2_FEATURE_PORT.md) — distinct **merged**, rollback-journal-only observational audit and optional telemetry, PR #126. The historical premerge status in the latter two documents is provenance, not current status.
- [M6 Oct 19 rebaseline](M6_0_REBASELINE_2026_10_19.md) and [historical implementation plan](M6_0_IMPLEMENTATION_PLAN.md) — dated snapshots. Their old “next R0 choice” wording was superseded by [R0b fail-closed decision](M6_0_R0B_CURRENT_WAL_FAIL_CLOSED_DECISION.md).

## Source epoch and writer proof (P0/P1 and W1)

- [Source admission and trusted producer design](M6_0_BDIAG_SNAPSHOT_PRODUCER_TRUSTED_CUSTODY_DESIGN.md), [adversarial matrix](M6_0_BDIAG_PRODUCER_CUSTODY_SECURITY_MATRIX.md): what remains **unverified**.
- [W0 trusted writer protocol](M6_0_W0_WRITER_FENCING_AND_SEAL_PROTOCOL.md), [W1a cross-process fencing](M6_0_W1A_CROSS_PROCESS_FENCING_PROOF.md), [W1b RunStore preflight](M6_0_W1B_REAL_RUNSTORE_FENCING_PREFLIGHT.md): bounded design/proof assets; not a production writer.
- [M0o closed-world deployment candidate](M6_0_M0O_DEBIAN_KVM_CLOSED_WORLD_DEPLOYMENT_PROFILE.md), [M0q executable origin](M6_0_M0Q_EXECUTION_ORIGIN_AND_START_AUTHORITY.md), [M0r credential feasibility](M6_0_M0R_SERVICE_ONLY_WRITE_CREDENTIAL_FEASIBILITY.md), [M0x journal crash windows](M6_0_M0X_ANCHORED_JOURNAL_CRASH_WINDOWS.md): why root/LSM/FD/execution-origin admission remains separate and unproven.
- [P01 mixed-epoch and false current](M6_0_P01_SYNTHETIC_MIXED_EPOCH_ADMISSION_GATE.md) and [P02 self-asserting receipt](M6_0_P02_SYNTHETIC_RECEIPT_PROVENANCE_GAP.md): merged **LAB_ONLY** negative models, not source attestation.
- [P03-D1 owner decisions D1–D5](https://github.com/ehsanrs2/projectctl/issues/124) — **OPEN / NOT OPERATIONALLY APPROVED**. Proposed [PR #125](https://github.com/ehsanrs2/projectctl/pull/125) was **closed without merge as redundant**; substantive authority and threat requirements remain in the existing B-Diagnostic design, matrix, ADR-040 and this open issue.
- [W1c disposable Seal/crash tests](https://github.com/ehsanrs2/projectctl/pull/131) — **MERGED / LAB_ONLY**; [Issue #130](https://github.com/ehsanrs2/projectctl/issues/130) closed, not proof of a trusted real Writer or captured source epoch.

## Reader, schema and artifact research

- [R0 native live-WAL feasibility](M6_0_R0_LIVE_WAL_READER_FEASIBILITY.md), [R0b decision](M6_0_R0B_CURRENT_WAL_FAIL_CLOSED_DECISION.md), [B2a detached WAL](M6_0_B2A_WAL_FEASIBILITY.md) and [B2b cross-store consistency review](M6_0_B2B_SNAPSHOT_CONSISTENCY_REVIEW.md).
- [B1 reader audit](M6_0_SLICE_B1_READER_AUDIT.md), [B1b historical artifact validation](M6_0_SLICE_B1B_ARTIFACT_VALIDATION.md), [Trace contract](M6_0_TRACE_CONTRACT_V1.md) and [Slice B privacy/security spec](M6_0_SLICE_B_SNAPSHOT_SECURITY_SPEC.md).
- [Seal v1 design gate](M6_0_B3_SEAL_V1_DESIGN_GATE.md), [pure Seal](M6_0_B3A1_PURE_SEAL_CONTRACT_AUDIT.md), [transaction lab](M6_0_B3A2_TRANSACTION_LAB.md), [schema migration rehearsal](M6_0_B3A3_SCHEMA_MIGRATION_REHEARSAL.md) and [backup recovery rehearsal](M6_0_B3A4_BACKUP_RECOVERY_REHEARSAL.md). None means production migration or live Export admission.

## P2/P3 receipt and custody labs (synthetic only)

- [Receipt contract](M6_0_BDIAG_P2_SYNTHETIC_RECEIPT_CONTRACT.md), [issuer/replay model](M6_0_BDIAG_P2B_ISSUER_REPLAY_MODEL.md) and [crash-recovery state model](M6_0_BDIAG_P2C_CRASH_RECOVERY_STATE_MODEL.md).
- [P3 deployment feasibility](M6_0_P3_TRUSTED_CUSTODY_DEPLOYMENT_FEASIBILITY.md), [matrix](M6_0_P3_TRUSTED_CUSTODY_DEPLOYMENT_MATRIX.md), [P3c dual principal topology](M6_0_P3C_DISPOSABLE_DUAL_PRINCIPAL_TOPOLOGY.md), [P3i SQLite custody](M6_0_P3I_SYNTHETIC_SQLITE_CUSTODY_TRIAL.md), [P3j Unix intake](M6_0_P3J_SYNTHETIC_UNIX_INTAKE_LAB.md), [P3k ACK reconciliation](M6_0_P3K_SYNTHETIC_ACK_RECOVERY_LAB.md), [P3l SIGKILL recovery](M6_0_P3L_SYNTHETIC_SIGKILL_SOCKET_RECOVERY_LAB.md), [P3m blob no-clobber](M6_0_P3M_SYNTHETIC_BLOB_BINDING_NOCLOBBER_LAB.md), and [P3n reboot evidence](https://github.com/ehsanrs2/projectctl/issues/119). **P3 deployment is NO-GO.**

## Hygiene and research preservation

Preserve all older M0a–M0x, P3a–P3m, Post-M3/M4/M5 reviews, ADRs and D2 research provenance. These are **historical evidence**, not duplicate current-stage instructions. Index them here where meaningful; do not make a wholesale move that breaks links, cross-references, CI or source identities. A separate branch/PR may remove dead pointers only after verified references and reachability.

**Operational stop:** P0/P1/P2/P3/P4 and live R1 Trace Reader/Collector/CLI remain NO-GO, with R0b C fail-closed.
