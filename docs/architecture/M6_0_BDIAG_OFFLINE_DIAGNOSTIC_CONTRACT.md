# M6.0 B-Diagnostic — bounded offline rollback-journal diagnostic contract

**Status: TEST-ONLY FEASIBILITY + REVIEW CONTRACT; NOT A PUBLIC EXPORT OR PRODUCT ADMISSION.**
**Baseline:** merged R0b #98, main c384bbcfb17da16919c24783fa877453db4b2034.
**Governing:** accepted ADR-039 (derived non-authoritative read-only Trace and local privacy), accepted ADR-040 Path A (future trusted Verification as-of Seal), and R0b current decision C (active WAL fail-closed).

## Decision and purpose

The M6.0 goal is deterministic read-only Trace & Evaluation Export. R0b correctly refuses any claim that a normal **active-WAL** project has an independently certified source-nonmutating DB+JSON snapshot. This B-Diagnostic stage evaluates only whether the **existing private B1 readers and pure B1b builder** can generate a reproducible, incomplete, untrusted diagnostic bundle from a **quiescent, disposable, rollback-journal** project fixture.

**This is not the operational Reader, Collector or CLI.** It deliberately adds one test module plus this architecture file, with zero runtime projectctl package edits, no public register path, no source WAL read, no v3 migration, no trusted writer Seal, no AppArmor/systemd, no privileged commands or user-project access. Do not run its ideas against any live project without a separate safety review.

The only accepted observation on completion of a test is: a bounded test-owned rollback-journal project permitted deterministic, structurally conservative Trace composition without detectable file content or selected metadata changes. It is NOT proof that all source reads on any POSIX mount are side-effect-free, that quiescence is independently proven, or that the trace is complete or verified.

## Experimental composition (tests only)

On a newly initialized **real ProjectCTL v2** state.sqlite under pytest tmp_path, the test explicitly changes only that fixture to rollback-journal DELETE mode after initialization. This is not a supported way to convert a real user project. It inserts one bounded planned RunManifest, a RunStore event with secret-bearing private payload and a fixed versioned ContextManifest. No competing writer exists in the successful case.

The test only calls already-existing private functions, in this order:

1. **read_run_db_snapshot:** POSIX descriptor-anchored readonly attempt rejecting active WAL headers before SQLite connects. It hashes bounded Run record, historical manifest and ordered event category metadata, never raw event payloads.
2. **read_run_artifact:** fixed-leaf no-follow bounded context/verification/evidence reads. Missing artifacts are explicitly missing, symlinks and unsafe parents are refused.
3. **inspect_artifact_snapshot:** exact version/identity and raw SHA match checks, never implied semantic lineage.
4. **conservative_trace_from_snapshots:** deterministic public model always incomplete or inconsistent with zero assessments.
5. **canonical_trace_json_bytes:** identical bytes on repeated calls with no export-time timestamp, raw event payload, private worktree path or unclassified event type string.

The synthetic project ID is **known in test code**, not independently derived from a user project's configuration. Therefore it does not establish real cross-project identity admission. Missing project config authentication and externally enforced writer quiescence are independent blockers.

## Test witness matrix

| Scenario | Allowed observation | Gate |
| --- | --- | --- |
| Cold rollback-journal DB with no active writer | Repeated byte-identical incomplete Trace; no new WAL/SHM; file bytes and selected inode/size/mtime/ctime stable in the disposable fixture | LAB_ONLY, not universal safe export |
| Disposable DAC read-only mode 0400 DB and 0500 directory | Same bounded observation for ordinary-user test fixture | Not mandatory MAC proof; hostile owner/root not excluded |
| Missing expected artifact | Explicit missing_source, no invented supported assessment | Missing does not imply passing Verification |
| Duplicate-key/invalid artifact containing secret text | Inconsistent with typed invalid_content, no raw private content in derived bytes | Raw digest is correlation, not truth proof |
| Symlinked artifact or run directory | Fail closed before any derived public output | Foreign target not followed |
| Active WAL with open test writer | Existing B1 Reader rejects; no fallback to R0 test VFS | R0b route C preserved |
| JSON replaced after DB snapshot | Even a parsed present leaf does not certify one coherent epoch; bundle remains incomplete and assessment-free | Independent quiescence unproved |
| Secret-bearing event payload and private absolute path | Absent from canonical Trace bytes | Additional future privacy tests still needed |

Test fingerprints compare file content and selected inode/size/mode/mtime/ctime before/after; intentionally **do not** claim reads cannot update atime or briefly change filesystem/VFS state between samples. The tests themselves read files and may affect access time. A mount with incompatible no-follow/ownership or forbidden metadata side effects remains unsupported absent separate proof.

## Explicit consistency and security limits before ANY Collector

- **Offline is not a flag.** Caller-supplied claims of quiescence or static rollback header cannot exclude an already open writer, hot rollback journal, different process, delayed JSON replacement, hardlinks, ancestor rename, aliases or mount namespaces. Future admission must establish an independent boundary or restrict input to a separately constructed immutable/verifiably sealed snapshot.
- **Reader path pinning is partial.** B1 uses no-follow descriptors for selected leaves, but native SQLite opens by path; a caller-writable parent can race identity checks. A real exporter needs end-to-end ancestor and inode proof and side-effect-free VFS evidence.
- **No v3, no Seal, no epoch.** A structurally valid output does not prove as-of time or historical consistency and must never be labelled complete, independently verified, supported assessment or delivery confirmation.
- **No raw leakage.** Only allowlisted public fields and digest metadata; never prompts, raw provider payload, inputs, credentials, host absolute paths, or run_events payload_json.
- **Typed safe errors.** Corruption, unexpected versions, oversized files, unsafe paths, unknown project/run and symlink/hardlink races must fail conservatively with non-sensitive errors.
- **Production differs.** ProjectCTL normally uses WAL. Converting a running user project to DELETE mode to make this diagnostic work is **forbidden**.
- **No public command.** Adding a Trace export CLI would require a separate accepted decision, tested source/project identity, permitted metadata policy, output destination safety, privacy, and strictly limited claims; this PR does not do that.

## Next formal product gate (not passed by this PR)

A future diagnostic feature proposal must choose between **an independently constructed immutable detached fixture** and **externally witnessed all-writer quiescence**. The latter is difficult and may require authority beyond a portable read-only CLI. The resulting candidate must demonstrate:

1. Trusted source/project/run identities and bounded schema-version handling, ancestor and symlink/hardlink/rename resistance.
2. Independent nonmutation proof for filesystem/SQLite/sidecars and explicit atime policy; no unverifiable promise of writer absence.
3. No false cross-store epoch even after concurrent DB/JSON or rollback-journal changes.
4. Byte-identical redacted output with completeness incomplete/inconsistent, assessments empty, never inferred verified status.
5. Locally controlled stdout/destination only after explicit opt-in, with no authority overwrite or Worker/provider invocation.
6. Exact-head CI and platform test plus specific owner approval before a public CLI.

**Disposition:** B-Diagnostic is LAB_ONLY / suitable for further narrow review; operational Collector/CLI, active-WAL R1, v3 Migration, trusted W1 Seal, root/policy changes and new Worker/Task authority all remain **NO_GO**. Audit F-01 to F-06, F-08 and F-09 are not closed by this work.
