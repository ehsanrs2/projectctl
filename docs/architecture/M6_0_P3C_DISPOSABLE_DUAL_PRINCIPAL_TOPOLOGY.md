# M6.0 P3c — Disposable Dual-Principal Trial Topology Selection

**Date:** 2026-10-20

**Classification:** DESIGN_ONLY / HUMAN_REVIEW_REQUIRED / NONAUTHORIZING

**Decision:** `P3C_NO_GO_TO_EXECUTE_TRIAL`

**Baseline:** merged P3b PR #108, `main@442e73d2a9dddfa4ca2ef77de98a58f73506f8b8`.

This is a **selection of a conditional trial topology**, NOT an existing provisioned machine, verified filesystem, active custodian or permission to use root. The nonauthorizing P3 and P3a/P3b conclusions remain intact. ADR-039 Trace stays strictly local, read-only and nonauthoritative; ADR-040 Path A remains design-only; R0b C continues to refuse active v2 WAL reading. P0–P4 operational, v3 migration, trusted W1, R1, Collector/CLI and Worker/Task authority remain NO-GO.

## 1. Problem, concrete topology choice, and exclusions

**Question:** Can an uncooperative legacy ProjectCTL writer acting as the ordinary project user be prevented by a *genuinely independent* custodian identity from altering published package bytes, publication pointers and replay high-water, while a failure/restart protocol remains safe?

**Conditional selected laboratory topology: P3-C2 / T1.** One **owner-approved, throwaway Debian VM**, managed by a trusted administrator distinct from the ordinary ProjectCTL actor, contains a dedicated persistent virtual disk/filesystem and **two separate static non-root identities**: an untrusted legacy-writer/test client and an administratively controlled Custodian. A separate observer under administrator control records the denial/recovery evidence. All project inputs and receipt/issuer fixtures are synthetic, bounded and non-sensitive. No production ProjectCTL checkout, live database, state.sqlite, WAL, credentials, keys or public exporter is in the experiment.

**Selected here: architecture pattern T1; NOT selected:** VM/host identifier, actual custody directory, disk, filesystem, UID/GID, administrator, executable path, launcher, service unit, credentials or test commands. Those concrete values require owner approval and independent readback in **another authorization artifact**. The operator's observed `/tmp` read-write tmpfs is **rejected** as a persistent custody target. Filesystem labels (ext4, xfs, btrfs) are *candidate families to evaluate*, not proof that a filesystem actually exists or is safe.

**Alternative/fallback decision:** If the independent administrator, physically separate administrative control, or protected, nonvolatile store cannot be supplied, stop rather than implementing a same-UID sidecar. If hostile root, hypervisor or full-disk snapshot rollback is **in** the required attacker scope, local T1 is insufficient: halt and require separately chosen outside-VM monotonic/version authority. No external account, secret or service is approved here.

## 2. Topology and exact authority boundaries

```text
Trusted host/hypervisor administrator (TCB; independent of ProjectCTL user)
    |
    +-- Disposable Debian VM (no real ProjectCTL source or secrets)
          |
          +-- Untrusted static non-root legacy-writer identity
          |     - simulated old v2 launch paths, groups and inherited FDs
          |     - may request synthetic publication, cannot manage custodian
          |
          +-- Trusted static non-root Custodian identity (candidate only)
          |     - binaries, config, imports and ancestry controlled by admin
          |     - narrowly scoped authenticated intake and fixed artifact types
          |     - sole writer of staged immutable-version objects + ledger
          |
          +-- Admin-controlled independent observer
                - before/after credential, kernel-denial and reboot witnesses
                - not a self-generated success claim from the tested writer

Isolated persistent virtual disk / candidate filesystem
    -> administrative ancestors
    -> uniquely addressed staged objects (durable before publication)
    -> exactly one authoritative receipt+revision+high-water+manifest commit
```

**Trusted computing base:** host/hypervisor and host administrator, guest kernel/root/service provisioning and whichever storage layer actually enforces durability. A malicious guest root or host can change credentials and roll back the entire store; T1 makes *no* root-resistant or malicious host-rollback claim. A guest root trusted administrator is acceptable only if independently controlled and outside the adversarial writer. Never treat an admin user who shares sudo privileges/passwords with the project user as a separate authority.

**Untrusted principals:** ordinary project user, old v2 processes and scripts, supplementary GIDs, inherited pre-cutover FDs and sockets, writable Python import/dependency locations, user-level service launches, fabricated request metadata and all caller-controlled checksums. Root-equivalent privileges in an alleged writer account invalidate the proposed separation.

**Custodian identity prerequisites:** admin-owned entire executable/config/import and storage ancestor chains; no project-user write/chmod/unlink/rename/replace paths; no shared supplementary private GID/ACL/capability; no writable FD inherited into a legacy writer; no alternate mount/idmapped alias; no environment/PYTHONPATH/code-origin substitution; controlled IPC endpoint and independently authorized producer policy. Each property must be **tested adversely on the actual topology**, not inferred from `chmod` or service naming.

## 3. Storage decision and durability model (NOT yet an implementation)

- Reserve a new virtual disk backed by an independently identified **nonvolatile**, disposable storage medium; capture guest filesystem, host backing, overlay, namespace, bind mounts, device mapping, ACL/LSM and mount options. No `/tmp`, `ramfs`, `tmpfs` or source-project paths. Do not assume a virtual disk or an `ext4` label guarantees persistence under a VM reset.
- Admin creates custody storage under admin-controlled non-project-writable ancestors **only after separate approval**. Distinguish object store, staged objects, committed manifest pointer, transaction/ledger, audit witness and cleanup/retirement state. Pin finite artifact allowlist and object IDs; prevent symlink/hardlink/alias traversal and path replacement at every step.
- **Single authoritative commit:** commit one protected metadata record/transaction binding project/issuer scope, receipt ID, issue sequence, monotonic high-water, sealed object identity and publication status. Stage **exact bytes**; fsync each blob and containing directory *before* the record becomes committed. Select and verify a real datastore/transaction protocol later: do not claim two renames form one transaction or rely on user-written SHA/checkpoint as authority.
- Precisely declare the **linearization point** and stable readback method. No-clobber publication and object bytes must remain addressable across fresh-process/reboot recovery. Successful ACK is permitted only after required durability and independent readback criterion is satisfied. A lost ACK remains caller-ambiguous; no automatic retry, reissue or reconstruction from an old self-hashed inventory.
- Orphans from interrupted staging and terminal retirement require independently observed quarantine/retention policy. `EIO`, `ENOSPC`, missing fsync, corrupt/old ledger, stale issuer policy or failed no-replace must be typed failures and fail closed. No wildcard cleanup.
- **Rollback scope:** high-water can only be claimed protected against the ordinary writer if the authoritative record and its ancestors are controlled by the independent identity. Rolling back the complete guest/VM disk by a trusted host administrator is **out of scope**; detecting it requires an external monotonic anchor not selected.

**Distinguish evidence families:** CRED (actual separate identity), BLOB (nonreplacement), SEQ (protected sequence), DUR (filesystem/recovery), AUTH (producer/epoch) and EXP (export eligibility) never imply one another.

## 4. Required human approval package before *any* privileged trial

A new owner-approved, disposable-target-specific authorization must name/verify ALL entries below before administrators provision any account, disk, mount or service:

1. **Owner and observer:** owner approval signature/record, independent administrator/operator separation, independent witness; no same sudo credential, root capability or user-writable trust chain.
2. **Disposable host:** exact machine/VM/disk identity, isolation from real ProjectCTL paths and secrets, reset/rollback plan, backups boundaries and evidence destination; independent host attestation scope.
3. **Concrete custody storage:** absolute approved disposable path and each ancestor's UID/GID/ACL/LSM; exact nonvolatile FS/mount and snapshot/overlay properties; pre/post FS readback and no-clobber+directory-fsync capability probes; failure if unsupported.
4. **Two identities and launch provenance:** exact static UID/GID and groups, admin-controlled executable/config/import paths, system/user service rights, mount/idmaps, capabilities, sockets and inherited FD drainage; enumerate legacy writer launch routes and use a genuinely uncooperative old-writer negative control.
5. **Synthetic protocol:** bounded receipt/issuer policy, staged bytes, fixed allowed names, trusted one-record ledger, concurrency model, observable commit/ACK/reconciliation point, explicit no automatic retry.
6. **Operations and abort:** explicit command-by-command privilege request, precise disposable paths, crash/reset steps and observation owner; rollback, data retention/redaction, costs and stop rules; no writing to current Debian user's checkout.
7. **Evidence criteria:** mapping all P3-F01–F28 to scenario, observer, before/after snapshot, forced fault cut point, source of independent trust, decision and artifact retention. Every scenario starts NOT_RUN; no optimistic PASS.
8. **Review checkpoint:** an independent reviewer approves the *specific plan* and the owner separately authorizes the *specific privileged commands*. Approval of this document or PR is **not** authorization.

The following MUST remain false: root/sudo, adding identities or services, systemd/LSM/mount/kernel configuration, changing real DB/WAL, signing keys, operational v3/W1/R1, public Collector/CLI and Worker/Task expansion.

## 5. Order of future experimental claims; stop on first failed boundary

1. **Preflight/credential boundary:** identify actual VM/FS and principals; demonstrate independent administrator and deny all old-writer GID/FD/launch aliases. If fail, stop; do not claim a trusted service.
2. **Object identity:** pinned synthetic bytes, no-follow, no-clobber, races and aliases. If fail, stop; do not build a ledger around mutable bytes.
3. **High-water and single commit:** one authoritative transaction and replay refusal across fresh processes; if local full-disk rollback resistance is claimed, reject T1 or add a separately approved anchor.
4. **Durability/fault recovery:** file + directory fsync, record ordering, SIGKILL, forced reboot, ACK-loss, ENOSPC/EIO and cleanup/retirement; every cut point independently read back. If fail, quarantine, no inferred retry.
5. **Source/issuer and export:** no real ProjectCTL bytes or public interface in T1; separate P0/P1/P2/P4 proofs would still be required and are NOT satisfied here.

See companion [P3c trial episode matrix](M6_0_P3C_DUAL_PRINCIPAL_TRIAL_EVIDENCE_PLAN.md) for 28 specific scenarios and acceptance observations.

## 6. P3c decision and acceptable evidence

P3c can be accepted **as a documentation-only topology selection** when the proposed T1 trust graph, alternative stop condition, explicit future approval package, all 28 negative witnesses and machine-readable **NO_GO** are reviewed. No real dual-principal experiment is authorized or performed, and no service exists by implication. Passing docs/CI or a future same-UID test does not change P3's operational NO_GO.

After merge, ordinary-user operator checks only:

    git fetch origin
    git diff --check 442e73d2a9dddfa4ca2ef77de98a58f73506f8b8..origin/main
    git diff --stat 442e73d2a9dddfa4ca2ef77de98a58f73506f8b8..origin/main

**Final decision:** `P3C_NO_GO_TO_EXECUTE_TRIAL`; selected *research topology pattern* `P3C_T1_CONDITIONAL_DISPOSABLE_STATIC_DUAL_PRINCIPAL`. No production deployment and no operational permission.
