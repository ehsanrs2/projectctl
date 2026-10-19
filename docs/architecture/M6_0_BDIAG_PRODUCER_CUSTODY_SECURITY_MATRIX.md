# M6.0 B-Diagnostic — Producer/Custody threat and acceptance matrix

**Status: REVIEW PLAN / FUTURE TEST SPECIFICATION — NOT A TEST REPORT.**
**Reviewed baseline:** main 608da94f250f1354ffa3c8f47a6282160e6b4577, PR #100 merged and operator-reported nonroot Debian 30 focused tests. Existing suite checks only internally coherent synthetic detached fixture bytes. All future conditions below remain **UNVERIFIED**. See [the controlling P0–P4 design](M6_0_BDIAG_SNAPSHOT_PRODUCER_TRUSTED_CUSTODY_DESIGN.md).

## Evidence levels must be separate

| Level | What counts | At current baseline | What it must never imply |
| --- | --- | --- | --- |
| E0: syntactic and hash consistency | Strict finite path list, bounded bytes, exact digest checks | **LAB_ONLY** on synthetic detached fixture | Original project identity, coherent time, independent custody |
| E1: authenticated producer/capture assertion | Independently authorized signer/custodian and unforgeable binding to receipt | **UNVERIFIED** | Producer told the truth about source quiescence or epoch |
| E2: source epoch and file-set coherence | Trusted writer as-of Seal or vetted atomic/cooperative cut with exact Run/DB/event/JSON identity | **UNVERIFIED** | Remote task success, independent verification, exported complete Trace |
| E3: custody, durability and anti-replacement | Separate trust principal prevents changes; durable no-clobber versioned publication and restart reconciliation | **UNVERIFIED** | Source epoch truth without E2 |
| E4: read-only diagnostic eligibility | E1–E3 independently checked, supported source read, privacy/output policy and scoped owner acceptance | **UNVERIFIED / NO_GO** | Trusted R1 or public CLI without separate approval |

A same-UID actor can regenerate SHA-256 and inventory text, satisfying E0. A cryptographically signed mixed-epoch package can satisfy E1 and E3 while failing E2. A correct epoch with an overwritten or revoked custody object can satisfy E2 but fail E3. Treat each level as independently necessary, not substitutable.

## Threat/falsification plan — cases are REQUIRED FUTURE PROOFS, not executed findings

| ID | Threat or injected condition | Proof required for future approval | Current outcome |
| --- | --- | --- | --- |
| C01 | Old v2 binary starts after an advisory quiescence check | Independent offline denial of **all** start paths before/during/after capture | **UNVERIFIED / refuse** |
| C02 | Already-open writable DB, WAL or JSON FD from old writer | Demonstrated barrier/drain, not PID-name enumeration or a newly added lock | **UNVERIFIED / refuse** |
| C03 | Source DB copied at epoch N, JSON replaced at epoch N+1 | Exact epoch witness rejects mixed versions; no self-hash promotion | **UNVERIFIED / refuse** |
| C04 | Active WAL + checkpoint/SHM regeneration overlaps capture | Source-read nonmutation and coherent snapshot without torn WAL/DB pair | **UNVERIFIED / fail closed C** |
| C05 | SQLite backup succeeds but JSON belongs to another instant | Explicit artifact/Run/event Seal identity binding or independently atomic handoff | **UNVERIFIED / refuse** |
| C06 | Atomic filesystem snapshot taken during partial Verification | Application-level as-of boundary verified, never infer READY_TO_INTEGRATE from filesystem instant | **UNVERIFIED / refuse** |
| C07 | Same-UID actor edits leaf and recalculates local inventory | Independent producer/custodian trust, no source-origin promotion from hashes | **PR #100 NEGATIVE WITNESS; future gate open** |
| C08 | Signing key or credential is writable by untrusted same-UID client | Separate trust principal/keystore, grants audited, no exported private key | **UNVERIFIED / refuse** |
| C09 | Self-signed receipt, unknown key ID or misleading algorithm choice | Fixed version/domain, independently anchored issuer allowlist, no algorithm downgrade | **UNVERIFIED / refuse** |
| C10 | Revoked/expired producer key, replayed old package or duplicate sequence | Defined revocation/rotation, anti-replay and verified issuance time/epoch policy | **UNVERIFIED / refuse** |
| C11 | Run ID, task ID, project ID, event ID or manifest version swapped | Typed canonical receipt and cross-run/run-event identity checks against authoritative epoch | **UNVERIFIED / refuse** |
| C12 | Sign receipt before fsync of content or directory publication | Publication barriers and final package receipt correspond to durable bytes only | **UNVERIFIED / refuse** |
| C13 | Crash after payload publication but before receipt pointer, or vice versa | Independent recovery discriminates accepted/partial/ambiguous; never blind success | **UNVERIFIED / quarantine** |
| C14 | Crash after final journal unlink before outer directory retirement | Trusted reconciliation owner and terminal durable state not solved by nested journals | **M0x NEGATIVE LIMIT; future gate open** |
| C15 | Same-UID replaces package by rename, parent-directory swap or symlink/hardlink | Trust boundary independent of attacker, path/FD and mount identity checks | **UNVERIFIED / refuse** |
| C16 | Filesystem provides no trustworthy no-clobber/rename/fsync contract or is remote/shared | Explicit supported FS/topology list, fail closed for unsupported mounts | **UNVERIFIED / refuse** |
| C17 | Historical Seal references fixed leaf overwritten by newer writer | Immutable referenced bytes retained and validated, else mark unavailable | **UNVERIFIED / unavailable** |
| C18 | Reader hits malformed/oversized manifest, JSON duplicate keys, secret fields | Strict finite schema, bounded parsing, typed redacted failures, no raw event/provid­er data in public Trace | **PARTIAL fixture tests only** |
| C19 | Source DB/WAL/SHM atime, mmap or transient VFS write modified by reader | Independent VFS/OS audit with declared metadata tolerance on target platforms | **UNVERIFIED / fail closed** |
| C20 | Package holds provider credentials or absolute local paths in raw leaves | Raw-data retention/privacy minimization, access control and safe output allowlist | **UNVERIFIED / no public export** |
| C21 | An untrusted operator-supplied source path aliases production/project state | Absolute path not trusted as identity; independent project scope and canonical FD/custody admission | **UNVERIFIED / refuse** |
| C22 | Verified local package is mistaken for independent remote Task success | Export remains non-authoritative, assessments empty absent later accepted L3/L4 lineage | **NO_GO for supported assessment** |
| C23 | Guest reboot/parent death while producer or custodian is running | Separate restart owner, staged receipt and durable state readback, no unapproved OS-wide install | **UNVERIFIED / refuse** |
| C24 | Compromise of trusted producer or guest root, or unauthorized signing request | Explicit TCB and issuance governance; define residual compromise response, do not claim signature prevents an authorized actor from lying | **UNVERIFIED / out of scope until TCB approved** |

**Required negative controls:** for each future candidate, inject at least one case where E0 hash checks pass while E1/E2/E3 fails. The product must not label that input trusted, complete or independently verified. A successful check of a local Manifest is not a cryptographic provenance proof; matching VFS fingerprints are not proof of no transient side effects.

## Gate-specific evidence packages required before implementation

### P0 source admission evidence

A review artifact must specify deployment OS/version, filesystem/mount topology, project parent inodes, all DB/WAL/SHM and fixed external-leaf aliases, all admitted writer PIDs/UIDs/GIDs/entrypoints and writable FDs, and a **separately enforced** startup/FD barrier. It must include a negative demonstration of a v2 old-process attempt and a documented post-release lifecycle. No static process scan or status bit is adequate.

### P1 source epoch witness

Provide a bounded event/Run state and exact leaves/writer ordering for the **one ADR-040 eligible non-review Verification transition**. Prove generation/token fencing, durable no-follow file publication, transition/event/Seal in one SQLite transaction, ambiguity/crash recovery, and exact retained bytes. If P1 uses an atomic filesystem snapshot instead, additionally prove it captures a valid application boundary, not merely a consistent on-disk instant. Native WAL read path is still R0b fail-closed pending separate proof.

### P2 producer identity and receipt

Review an explicit finite receipt schema, canonical encoding, signature domain and algorithms, authority allowlist, key storage with independent ownership, rotation/revocation and authorized issuance. Test corrupt/reordered/extra/duplicated fields, key substitution, cross-project replay, stale epochs and falsified capture claims. A signature by an independent authority must bind specific content and epoch but must not be construed as *evidence* that the epoch existed; that comes from P1.

### P3 custody finalization and recovery

Review who may create a package, who may approve publication, who can chmod/rename/unlink after handoff, and how content-addressed identity and no-clobber versions work under the chosen FS. Test real interprocess races and all fsync/rename/receipt failure boundaries, power cut where approved and a fresh post-restart independent owner. Never delete unknown content by wildcard. The custodian must protect package bytes and their named identity from a same-UID adversary.

### P4 consumer and export eligibility

Test only against a **previously accepted** immutable package and independently anchored receipt; consumer must never visit live source paths or open active source WAL. Verify origin, as-of epoch, receipt validity, version, bounded source list, privacy and safe source-independent deterministic output. Unknown content or unsupported target platform => refuse. Diagnostic stage remains incomplete/inconsistent and assessments=[]; any public CLI/output or historical verified claim has its own separate owner gate.

## Stage decision and exact no-authorization statement

**This documentation-only PR establishes NONE of P0–P4.** It gives reviewers an auditable test plan and preserves design-only ADR-040 Path A as the preferred eventual epoch producer (S3); the feasibility of an atomic storage snapshot remains a separately reviewed alternative (S2).

No operational ProjectCTL project state, database schema, live source, privileged service, AppArmor, systemd, root, signing key, networking, maintenance stop, Reader/Collector/CLI or Task/Worker permission may be changed on the strength of this document. M0/v3, W1, R1, Collector and public CLI remain **NO_GO**.

The smallest next defensible *technical* PR, if separately requested, is one **synthetic pure contract** exercising a proposed receipt format with explicit source-origin/epoch/custody unknown states, adversarial duplicate/cross-project/stale inputs and all flags false. It must not create a signing service or real snapshot producer merely because a design review is merged.
