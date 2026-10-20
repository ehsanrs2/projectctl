# M6.0 P3 — Custody deployment falsification and evidence matrix

**Status: SECURITY TEST PLAN ONLY; NONE of the real OS/custody scenarios below have been run by this PR.**
**Baseline:** main 012e993fbf2c1ef797e974508953566e535c3b48, merged P2c PR #105 (2026-10-20).
**Decision:** [P3 deployment feasibility](M6_0_P3_TRUSTED_CUSTODY_DEPLOYMENT_FEASIBILITY.md) proposes candidate P3-C2 (independently administered static-principal custodian), with **P3_NO_GO_DEPLOYMENT_UNVERIFIED**. Source-origin P0/P1, issuer P2, custody P3 and consumer P4 remain separate.

## 1. Evidence is layered, never interchangeable

| Claim | Required witness in a future *authorized disposable* deployment | Current evidence |
| --- | --- | --- |
| CRED — independent custody owner | Actual credential/UID/GID/capability/startup provenance and adversarial project/writer account denial, incl. inherited FDs, groups and all writable ancestors | **UNVERIFIED**; M0 private-group legacy-writer negative witness remains |
| BLOB — nonreplaceable package identity | Staged exact allowlist, no link/path aliases, no-clobber durable version, protected content identity independent of caller | **UNVERIFIED**; PR #100 self-hashed fixed test input is NOT custody |
| SEQ — rollback-resistant receipt history | One independently owned linearizable monotonic high-water and issuer/project scope; survive process/system restart, fail/rollback and concurrent submission | **UNVERIFIED**; PRs #103–#105 test only in-memory claim equality |
| DUR — exact crash publication | Tested target FS file/dir fsync, record/pointer ordering, SIGKILL/power interruption, ack loss and independent fresh-process recovery | **UNVERIFIED**; P2c only classifies caller-provided values |
| AUTH — approved producer | Independently authenticated and authorized issuer/protocol, trusted source project and bounded captured epoch | **UNVERIFIED**; no signed Seal producer |
| EXP — local nonmutating/export eligibility | Proven P0–P3 + conservative ADR-039 privacy, no source WAL mutation and owner-approved output destination | **NO_GO**; R0b C remains |

Positive SHA/format checks never substitute for a real credential, source epoch, or durable authenticated history. Even passing CRED/BLOB/SEQ does not prove P0/P1 source coherence.

## 2. Future fault and adversarial scenario matrix (NOT performed)

| ID | Adversary / fault | Mandatory independent observation | If absent |
| --- | --- | --- | --- |
| P3-F01 | Same ProjectCTL UID chmods supposedly frozen package | Kernel denies changing protected committed object and parent; readback identical | NO_GO |
| P3-F02 | Same UID renames/unlinks published path or its parent | Independent protected ancestor identity and no-clobber denial | NO_GO |
| P3-F03 | Old v2 writer inherits proposed private GID | Test old uncooperative binary against actual custody objects; denied | NO_GO |
| P3-F04 | Old writer holds writable FD from before cutover | Attempt write through open FD and FD-passed socket; independently denied/drained | NO_GO |
| P3-F05 | Old writer spawns from unexamined CLI/systemd/user task path | Enumerate and attempt every launch/exec/code origin route; no private credential gain | NO_GO |
| P3-F06 | Project UID loads fake custodian Python module or replaces executable | Verified admin-owned dependencies and launch identity; deny import/code injection | NO_GO |
| P3-F07 | IPC socket peer spoofs claimed issuer/key PID or rootless process metadata | Cryptographic/independently authenticated producer identity and bounded protocol; reject | NO_GO |
| P3-F08 | Credential reuse, supplementary groups or namespace idmapping | Verify effective **filesystem** identity/caps/mount mapping and actual denial | NO_GO |
| P3-F09 | Same UID follows symlink or hardlink alias to content/ledger | No-follow anchored open, hardlink/path/mount alias defense across every ancestor | NO_GO |
| P3-F10 | Competing publishers use identical content address | Exactly one no-clobber committed version; second fails; no overwrite | NO_GO |
| P3-F11 | Source blob changes between hash and publication | Pinned bytes and exact identity; reject TOCTOU, hostile filesystem races | NO_GO |
| P3-F12 | Full old checkpoint + old SHA/manifest reintroduced | Independent revision/high-water rejects prior sequence **across restart** | NO_GO |
| P3-F13 | Local high-water store is cloned/rolled back with entire VM disk | Explicit scope: root/disk rollback remains TCB; stronger external monotonic witness if required | NO_GO if threat scope includes rollback |
| P3-F14 | Signature/issuer allowlist revoked or rotated mid-accept | Independently authenticated policy and at-commit authorization epoch | NO_GO |
| P3-F15 | Blob durable but commit ledger update fails | No ACK or accepted proof; staged bytes orphaned/quarantined | NO_GO |
| P3-F16 | Ledger updated but blob not durably published | Impossible by ordering or detected/quarantined at fresh readback | NO_GO |
| P3-F17 | fsync file succeeds but directory entry not durable | Directory fsync and reboot observation on declared filesystem | NO_GO |
| P3-F18 | renameat2 no-replace unavailable; network/overlay mount semantics differ | Exact target support recorded, fallback refuses, never silent overwrite | NO_GO |
| P3-F19 | SIGKILL before first object fsync | No accepted package or ACK, restart-safe staging cleanup | NO_GO |
| P3-F20 | SIGKILL after blob fsync/before authoritative record | Uncommitted staging detected, no false accepted state | NO_GO |
| P3-F21 | Crash after authoritative commit/before ACK | Independent readback identifies commit; caller sees ambiguity, no automatic duplicate publish | NO_GO |
| P3-F22 | ACK constructed/sent but lost during network or socket failure | No inference of failure; reconcile via authenticated committed identity | NO_GO |
| P3-F23 | ACK returned for a different project/run/package/sequence | Bound exact commit/revision receipt; reject or quarantine mismatch | NO_GO |
| P3-F24 | Disk full, EIO, EINTR, ACL drift or read-only mount change | Explicit typed failure and uncertain durable state; no self-repair/certification | NO_GO |
| P3-F25 | Final cleanup/retirement crashes after deleting last journal | Independent terminal record and recovery owner; no nested-journal proof substitution | NO_GO |
| P3-F26 | Expose raw prompts/worktree path/secrets from custodial bytes | Raw object privacy/retention and redacted egress independently enforced | NO_GO |
| P3-F27 | Content bytes correctly signed but DB/JSON from different epochs | P1 source Seal and historical byte retention reject mixed input, not signature alone | NO_GO |
| P3-F28 | User/worker calls an unreviewed public CLI or live WAL path | No new operation registered, source-read refusal, exact execution authority unchanged | NO_GO |

For each future candidate, test at least one **syntactically valid** hostile object which passes its SHA checks but violates issuer, source epoch or anti-rollback; the system must not label it complete, verified, accepted or safely replayable.

## 3. Trial prerequisites and stop rules

A later **explicitly authorized** disposable-environment trial must capture exact real kernel, distro, service manager, FS, mount, idmaps, ACLs, supplementary groups, capability bounding sets, code provenance, all source/custody ancestor directories and FD inheritance. Review them without root first where possible; obtaining the facts is not equivalent to configuring a control.

**Before any privileged operation**, the owner must approve the concrete disposable targets, identities, commands, rollback mechanism, no operator project DB changes, privacy/storage retention, after-reboot readback plan and independent witness. Current PR requests **no** such authorization.

Only a trusted publisher may declare a single durable receipt+checkpoint+object commit. A second process observing an old checkpoint cannot safely “help” or reconstruct an accepted commit using only its own SHA/checkpoint, nor may any reader decide to retry after an ambiguous ACK. Any unexplained GID overlap, unmanaged user service/FD, user-writable code, non-durable stage or unverifiable as-of capture is an immediate NO_GO.

## 4. Recommended disposition and operator checks

**Decision remains NO_GO for deployment.** Candidate P3-C2 is for future human approval only. If the system cannot provision a principal independent of ProjectCTL writers under the chosen trust scope, prefer **fail closed** over a same-UID surrogate or more synthetic journal layers.

After merge this PR adds **no executable tests** and requires no Debian guest policy change. An ordinary-user reviewer may verify patch hygiene only:

    git fetch origin
    git diff --check 012e993fbf2c1ef797e974508953566e535c3b48..origin/main
    git diff --stat 012e993fbf2c1ef797e974508953566e535c3b48..origin/main

**Operational authority:** M0/v3 migration, W1 source Seal, R1 source WAL Reader, Collector/public CLI, signing service, trusted Custodian, root/systemd/AppArmor and Worker/Task expansion all stay NO_GO.
