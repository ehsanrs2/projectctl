# M6.0 P3c — Dual-principal experiment evidence and falsification plan

**Classification:** FUTURE DISPOSABLE TRIAL PLAN ONLY — **NO SCENARIO EXECUTED OR PASSED**.  
**Baseline:** merged P3b PR #108, `main@442e73d2a9dddfa4ca2ef77de98a58f73506f8b8`.  
**Selected candidate:** conditional P3-C2 / T1 single throwaway VM, separately administered static Custodian identity, independent ordinary writer and controlled persistent storage. The actual VM, FS, principals, privileges, observer, keys and runtime are NOT selected or provisioned.

This matrix refines, but neither replaces nor weakens, the 28 scenarios in [P3-F01–F28](M6_0_P3_TRUSTED_CUSTODY_DEPLOYMENT_MATRIX.md). Every status is **NOT_RUN**, every absent/ambiguous witness results in **NO_GO**, and no P0–P4, W1/R1, v3, Collector/CLI or Worker/Task authority is granted.

## Independent evidence contract for every future test

For **each** case record: immutable case ID, independently authorized disposable target ID, exact setup and threat assumptions, separate **actor under test** and **observer**, synthetic input digest, pre-test identity/mount/FD observations, injected fault and cut point, kernel-level denial or fresh-process/reboot readback, sanitized before/after identities, one protected evidence record, explicit PASS/FAIL/UNKNOWN, cleanup/retirement state and reviewer approval. A test harness asserting its own result with matching SHA is not independent evidence. Evidence storage and its rollback scope must be declared.

**Preconditions:** independently owned service/code and protected ancestor chain; no real ProjectCTL state; no shared secret/sudo with untrusted writer; nonvolatile trial storage assessed on actual mount/host backing; fully specified command-level owner permission in a separate approval. STOP without any of these prerequisites. All evidence below is future-tense.

| ID | Family | Future negative/fault episode | Mandatory independently observed witness | On missing/failed witness |
| --- | --- | --- | --- | --- |
| P3-F01 | CRED | Project UID attempts chmod of committed object | Admin observer sees OS denial; committed bytes and identity unchanged | NO_GO |
| P3-F02 | CRED | Project UID attempts rename/unlink of package and ancestors | Denial at all replaceable parent edges; post-test readback unchanged | NO_GO |
| P3-F03 | CRED | Actual uncooperative v2 writer joins/inherits private GID | Verify effective filesystem GID/groups; actual custody write denied | NO_GO |
| P3-F04 | CRED | Old writer carries writable pre-cutover FD or passed socket | Open FD inventory plus attempted write/publish denial or prior safe revocation/drain proven | NO_GO |
| P3-F05 | CRED | Old startup surfaces (CLI, user services, tasks, scripts) reexec | Complete bounded launch-path inventory and denied credential/code takeover | NO_GO |
| P3-F06 | CRED | User-controlled imports, executable, env or service unit substituted | Admin-owned code/dependency ancestry verified; attempted injection rejected | NO_GO |
| P3-F07 | AUTH | IPC peer claims issuer/key/PID with spoofed metadata | Independent producer admission rejects claimed identity; peer UID/PID alone not trusted | NO_GO |
| P3-F08 | CRED | User/group reuse, capabilities, idmaps and namespace alias attempts | Actual kernel fs credentials, ACL/LSM/caps/mount maps verified; cross-boundary writes denied | NO_GO |
| P3-F09 | BLOB | Symlink, hardlink, bind or alternate-path alias to object/ledger | Anchored no-follow lookup and protected identity deny alias modification | NO_GO |
| P3-F10 | BLOB | Competing publishers race same content/version identity | Exactly one no-clobber final address committed, second rejected, original unchanged | NO_GO |
| P3-F11 | BLOB | Blob mutated between hashing/staging and publication | Pinned, immutable staged bytes; final digest and content identity match original | NO_GO |
| P3-F12 | SEQ | Old checkpoint, manifest and SHA restored together | Protected high-water/refuse replay survives restart within declared writer threat scope | NO_GO |
| P3-F13 | SEQ | Full guest/disk snapshot rolled back by trusted host | Explicitly classified OUT_OF_SCOPE for T1; **never** count as a T1 antirollback PASS. If in scope, require external monotonic witness or STOP | NO_GO for stronger threat |
| P3-F14 | AUTH | Issuer revocation/rotation races publication | Independent policy epoch checked at authoritative commit; stale issuer rejected | NO_GO |
| P3-F15 | DUR | Blob staged and durable, ledger transaction fails | No accepted commit or ACK; orphan quarantined and recoverable safely | NO_GO |
| P3-F16 | DUR | Ledger appears committed while blob is not durable | Commit ordering prevents this or independent restart quarantines and refuses | NO_GO |
| P3-F17 | DUR | File fsync succeeds but directory entry is not synced | Directory fsync + exact-target reboot readback; failure never accepted | NO_GO |
| P3-F18 | DUR | No-replace unsupported/overlay/FS semantics differ | Measured exact FS behavior; unsupported path fails closed with no overwrite | NO_GO |
| P3-F19 | DUR | SIGKILL before first object fsync | Independent restart sees no accepted record/ACK; staged bytes isolated | NO_GO |
| P3-F20 | DUR | SIGKILL after durable staged blob before metadata commit | Fresh process finds only orphan staging; no acceptance or silent retry | NO_GO |
| P3-F21 | DUR | Crash after authoritative durable commit before ACK | Independent reboot readback finds exact committed receipt; caller remains ambiguous | NO_GO |
| P3-F22 | DUR | ACK lost on socket after commit | Authenticated reconciliation to protected same commit; never auto reissue | NO_GO |
| P3-F23 | DUR | ACK refers to wrong project/run/sequence/digest | Mismatch refused/quarantined against authoritative record, no promotion | NO_GO |
| P3-F24 | DUR | ENOSPC, EIO, EINTR, ACL drift or read-only remount | Typed uncertain/failure state; no self-certification or destructive repair | NO_GO |
| P3-F25 | DUR | Crash during final retirement/cleanup | Independently protected terminal record, bounded retention/recovery; no journal-only inference | NO_GO |
| P3-F26 | EXP | Private prompts, paths, credentials in synthetic raw fields | Privacy gate blocks or redacts egress; no public Collector/CLI | NO_GO |
| P3-F27 | AUTH | Perfectly signed receipt covers DB/JSON different epochs | Only independently proved P0/P1 source epoch can accept; T1 synthetic trial must refuse claims of real-data coherence | NO_GO |
| P3-F28 | EXP | User/Worker calls public CLI or active v2 WAL reader | No new operation available or registered; existing refusal C and least privilege retained | NO_GO |

## Witness coverage and explicit phase gates

**Phase 0 — topology and owner authorization:** separately approved disposable guest, exact non-tmpfs disk, admin identity, two static principals, operator capabilities, real legacy writer negative control, FS and mount ancestry, no real source data, exact approved commands and abort procedure. Without Phase 0 STOP. This document is **not** that approval.

**Phase 1 — CRED:** F01–F08. Privileged changes and actual adversarial denial would occur only under future approval. Failure of any CRED edge prevents all later custody claims.

**Phase 2 — BLOB:** F09–F11. No-clobber version identity and caller-independent object provenance. Failure prevents durable publication claims.

**Phase 3 — SEQ + AUTH:** F12–F14, F07, F27. Protect high-water and policy identity without confusing same-host root rollback with writer rollback; real source epoch remains outside synthetic trial scope.

**Phase 4 — DUR:** F15–F25 on actual candidate target, repeatable crash/reboot at documented cut points and fresh **independent** readback; failures remain quarantined, no ACK-based retry inference.

**Phase 5 — EXP:** F26–F28 privacy/no new operations. Even passing all synthetic T1 cases does **not** enable production export until independent P0/P1/P2/P4 proofs exist.

## Hard STOP conditions

- No independent administrator or project identity retains sudo/root/capabilities to impersonate Custodian.
- Any writable executable/import/ancestor, unexpected private GID, inherited FD, idmapped or bind-mount alias, or unbounded IPC file-copy endpoint.
- Any missing readback under reboot, fsync failure, mutable high-water, whole-VM rollback mistakenly labeled protected or no-clobber unsupported.
- Any ambiguous ACK interpreted as no commit and retried, any self-hashed attacker object considered provenance, or any mistaken same-epoch/source claim.
- Any real DB/WAL path, secret, production project or public CLI touched, or any test launched without explicit owner-approved VM and privileged command list.

**Result of P3c:** planning completeness can be reviewed, but **28/28 actual cases remain NOT_RUN**. No test passes and no privileged trial is authorized by this document. Only a distinct owner-signed, bounded deployment-lab authorization could change the execution scope, and that would not change P0–P4 operational NO-GO.
