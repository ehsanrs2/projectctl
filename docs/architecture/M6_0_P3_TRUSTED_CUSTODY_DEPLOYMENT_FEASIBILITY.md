# M6.0 P3 — Trusted Custody Deployment Feasibility Gate (2026-10-20)

**Status: PROPOSED DESIGN/FEASIBILITY REVIEW — NO_DEPLOYMENT_GO.**
**Pinned source:** merged P2c PR #105, main 012e993fbf2c1ef797e974508953566e535c3b48.
**Authority:** accepted ADR-039 strictly source-read-only, local and non-authoritative Trace; accepted ADR-040 **Path A as design only**, bounded future writer-published Verification as-of Seal; R0b **C (fail closed)** for active project v2 WAL reads. P0–P4 operational evidence is still UNVERIFIED.
**Review companions:** [P3 deployment threat and test matrix](M6_0_P3_TRUSTED_CUSTODY_DEPLOYMENT_MATRIX.md) and [machine-readable nonauthorizing decision](p3/p3-custody-feasibility-decision.json).

## 1. Feasibility question and current answer

Can a deployed custody mechanism deny **the existing ProjectCTL operator/legacy writer** the power to change, replace, roll back or forge a detached package and its replay high-water mark after publication, while allowing only an independently authorized producer and no expansion of Worker/Task authority?

**Answer on the currently demonstrated repository and guest evidence: NOT YET.**
P2/P2b/P2c PRs #103–#105 check in-memory claims, simulated state equality and crash-state classification. They do not supply an independent filesystem/credential principal, atomic durable persistence, authenticated producer, trusted sequence, actual SIGKILL/reboot readback, or a protected package. PR #100's chmod 0400 private directory and self-recomputable SHA inventory are controlled by the same user and do not provide immutable custody. The earlier M0o–M0s negative witness shows that a legacy process with a candidate writer group could still write the synthetic source: nominal UID/GID separation, new cooperative locks or a service name **alone** do not establish code-origin isolation. M0x shows that another layer of cleanup journals does not automatically close the final failure/restart window.

**Conditional preferred topology to evaluate later: P3-C2, an administratively provisioned STATIC, separately credentialed local custodian, with root/admin-owned executable and non-operator-writable storage ancestors, a narrow authenticated publication channel and a single durable replay+package commit authority.** This is a **candidate** for an independently authorized disposable-machine trial, not a verified solution, deployment instruction or approval of privilege. If no administratively separate trust principal or independently protected high-water record can exist, retain NO_GO; do not substitute a same-UID sidecar.

## 2. What is protected, by whom, against whom

- **Source actor:** ProjectCTL user, old v2 processes, Workers, shell/test processes, and descendants including writable inherited descriptors, supplementary private group memberships, named pipes and previously opened sockets. Do not trust a PID name, friendly executable name, exported environment variable or unverified process path.
- **Proposed custodian actor:** separately provisioned fixed service identity with a credential boundary that the project user and old writers cannot assume or bypass; only the authorized custodian can change custody objects and the replay record. There is currently no such principal. Merely starting another Python process as the same user would not satisfy this criterion.
- **Administrator/host root/physical attacker:** remain part of the trusted computing base or require a stronger separately chosen threat model. Ordinary local DAC cannot protect against an administrator/root able to impersonate, rewrite the store or roll back the whole guest/disk. Do not assert full administrator/physical rollback resistance without an **additional independent anchor** (e.g. externally managed append-only version authority or evaluated hardware monotonic identity), which is **not** selected.
- **Client/producer:** independent P0/P1/P2 admission still required. An AF_UNIX peer credential, socket pathname, uid/gid match or code-signature claim does **not** automatically prove it is the approved, fenced W1 as-of producer or that its DB+JSON epoch is coherent.
- **Reader:** receives only a bounded, authenticated, finalized historical content identity through an independently reviewed read-only channel. No direct source project DB, live WAL or unbounded raw path traversal. No automatic complete/evaluated Trace.

**Separation test:** the actual task is not whether the custodian can write a different directory; it is whether **an adversarial uncooperative old writer using every available UID/GID/capability, inherited FD, start path and directory alias** can alter the committed package or trusted replay high-water. If yes or unmeasured, NO_GO.

## 3. Candidate comparison (NOT implementations)

| ID | Storage / identity topology | Same-UID tamper/replacement | Replay/rollback and durability | Decision at this baseline |
| --- | --- | --- | --- | --- |
| P3-C0 | Current same-UID 0400 detached directory + self-hashed inventory | Owner can chmod and/or rename; full path may remain writable | Both checkpoint and SHA anchor can be rolled back | **REJECT as trusted custody**; existing lab only |
| P3-C1 | Same UID, separate process or user-level systemd sandbox / advisory lock | Same credential or user-writable service code/socket; bypass routes remain | An ordinary process checkpoint has no independent anti-rollback | **REJECT as trust boundary** |
| P3-C2 | Static independently provisioned UID, admin-owned executable + custody tree, narrow authenticated handoff, independently controlled commit state | Could exclude project UID **if** all groups, ancestors, FD aliases, capabilities, startup and code origin are verified | Needs one durable append/linearization point, protected high-water, crash readback, versioned no-clobber publication | **PREFERRED CANDIDATE FOR FUTURE DESIGN TRIAL, currently UNVERIFIED** |
| P3-C3 | Dynamic service UID with managed state directory and sandboxing | Requires proof against UID recycling, service configuration, socket/FD escape and inherited groups | Dynamic UID is not an anti-rollback record or durable commit | **CONDITIONAL ALTERNATIVE, not selected** |
| P3-C4 | fs-verity, immutable inode flags or read-only mount alone | Can help defend contents in certain topologies; names, parent directory, prior versions and privileged bypass are separate | Hash integrity and inode immutability do not prove trusted origin, freshness or monotonic replay history | **ADDITIVE ONLY, not P3 alone** |
| P3-C5 | Independently administered off-host immutable/versioned object store + monotonic metadata | Could create a separate provider/admin trust boundary | Requires version/object-lock and account/retention semantics; add network, secrets, failure modes and local-first/privacy review | **OPTIONAL ALTERNATIVE; outside currently approved local deployment** |
| P3-C6 | Offline removable or sealed administrator-held medium | Potential independent custody under an explicit manual protocol | Human custody chain, rollback/version tracking and reinsertion reconciliation unproven | **MANUAL FALLBACK only; not an automated Custodian** |

**Do not assert availability:** the user's exact Debian filesystem, mount namespace, user/group maps, service manager permissions, kernel/LSM capabilities, trusted key store and acceptable custody location are not independently enumerated here. A design document cannot infer them from a green pytest result.

## 4. Conditional P3-C2 deployment topology — trust and authority edges

The following are **future approval requirements**, not steps to execute now.

1. **Administrative provisioning boundary:** independent static custodian UID/GID and parent directories outside operator-writable paths; service binary/dependencies/config and unit/launch provenance admin-controlled. The client must not be able to change custodian UID, supplementary group membership, effective capabilities, executable or code import path. Enforce explicit denial for old writer credentials and any project actor with group/FD inheritance. Document which administrator remains trusted.
2. **Authenticated intake boundary:** client cannot turn a user-written issuer/key ID or AF_UNIX peer PID into authenticated P2 producer identity. Verify an independently provisioned issuer/producer policy plus as-of source admission; only P0/P1/P2-qualified requests are eligible. A general-purpose file-copy or arbitrary path upload endpoint is forbidden. Before P0/P1 exist, **accept no real project input**.
3. **Package storage boundary:** fixed finite object IDs and allowed relative artifact kinds, no symlink/hardlink/alias traversal, project user cannot chmod, unlink, rename, remount or write any ancestor/object. Closed set of custody capabilities, private raw data access, retention/deletion/audit rules and strict output privacy. A content hash alone is not object identity; bind metadata and issuer/epoch sequence to that object.
4. **Single durable commit authority:** persist (a) issuer/project scope, (b) monotonically checked receipt identity and high-water sequence, (c) final content identity / sealed manifest pointer, (d) publication state, in **one independently committed authoritative record**. If physical files are separately staged, fsync content and containing directories **before** updating the authoritative record; commit the record exactly once, reconcile orphaned staging later. Do not assume that separate atomic renames of two files create a cross-file transaction.
5. **No-clobber publication:** a unique version/address cannot be silently overwritten by a second producer or old writer. A concrete Linux candidate is renameat2 with RENAME_NOREPLACE where filesystem-supported; directory fsync and crash-state readback still require independent tests. Fallback must **fail closed** if the filesystem does not support the required semantics; never silently replace the destination.
6. **Ack and restart:** do not emit a success acknowledgement until the authoritative committed record is demonstrably durable on the target storage and a restart-capable independently owned reader can find exactly the committed object. A lost ACK is **ambiguous for the caller**, not permission to issue a new receipt. A stale/corrupt/rolled-back high-water or unbound object yields quarantine/refusal rather than transparent bootstrap or a reconstruction from an attacker-provided inventory.
7. **Cryptographic/content integrity:** independently trust a producer/issuer registry and authenticated receipt; same-UID SHA checksum is only detection against accidental changes. A true signature by an independent key can authenticate receipt issuer, **not** source epoch; only separately witnessed P0/P1 can establish that. Key rotation/revocation/replay retention need their own acceptance.
8. **Recovery and retirement:** evaluate every fsync, commit/pointer, ack, consumer fetch, cleanup, restart and power-cut boundary; cover SIGKILL and independent boot owner, fsync errors, ENOSPC, permissions drift, revoked producer, abandoned staged data and final retirement. Never treat a final file or directory removal as proven durably reconciled until a separately checked terminal identity exists. No generic wildcard deletion of custody objects.

**Distinct truths:** same-UID exclusion is a credential/control test; storage durability is an OS/fs test; replay protection is a protected-state/protocol test; DB+JSON source coherence is a W1/P1 test; signer identity is P2; output eligibility is P4. Passing any one does **not** imply the others.

## 5. Platform constraints verified only from primary documentation

These are **documented platform capabilities**, NOT observations from the Debian guest:

- Linux fsync(2) notes that syncing a file does not necessarily sync its directory entry; separately syncing the containing directory is needed. [Linux fsync(2)](https://man7.org/linux/man-pages/man2/fsync.2.html).
- Linux renameat2(2) RENAME_NOREPLACE prohibits overwriting an existing destination but is **filesystem-dependent**; an atomic rename does not prove crash durability or replay protection. [Linux rename(2)](https://man7.org/linux/man-pages/man2/rename.2.html).
- systemd.exec(5) documents DynamicUser-managed state paths, UID recycling considerations, supplementary groups, and limits of per-user service sandboxing and AF_UNIX sockets. A systemd directive is a potential defense in depth, not an independent code-origin proof. [systemd.exec(5)](https://man7.org/linux/man-pages/man5/systemd.exec.5.html).
- Linux capabilities(7) and FS_IOC_SETFLAGS document CAP_LINUX_IMMUTABLE as the privilege required to set/clear inode immutability. This is not an operator-approved or tested storage strategy. [capabilities(7)](https://man7.org/linux/man-pages/man7/capabilities.7.html) and [FS_IOC_SETFLAGS](https://man7.org/linux/man-pages/man2/FS_IOC_GETFLAGS.2const.html).
- Kernel fs-verity verifies content against a Merkle-root-derived digest but the digest needs independent authenticity; substituting another file and replay of a *previously valid object* remain separate policy/identity problems. [Linux fs-verity](https://www.kernel.org/doc/html/latest/filesystems/fsverity.html).
- DAC path resolution and chmod permissions depend on effective filesystem credentials; directory search/write and parent ownership must be evaluated, not merely leaf mode 0400. [path_resolution(7)](https://man7.org/linux/man-pages/man7/path_resolution.7.html).

Never convert these references into a statement that a deployed ProjectCTL custodian exists, that root execution is safe, that fs-verity is enabled or that recovery is durable on a specific filesystem.

## 6. Independent evidence required BEFORE a privileged lab or implementation PR

See the companion [P3 matrix](M6_0_P3_TRUSTED_CUSTODY_DEPLOYMENT_MATRIX.md) for falsification cases P3-F01–F28. A separately owner-approved **read-only, nonprivileged inventory** can later collect: guest OS/kernel version; mounted filesystem and overlay/subvolume topology for a proposed *disposable* custodian location; current UID/GID/supplementary group and capability routes; parent inode/ACL/ownership and mount aliases; user versus system service rights; simulated workload and desired retention/privacy constraints. This PR does not collect them.

Before authorizing any real guest trial require all of:

- The owner names an explicit disposable topology and defines its trusted administrator/privilege boundary, including whether same-UID exclusion or also hostile-root/host-rollback must be prevented. Explicit approval is required for any account creation, root, service unit, LSM, mount/namespace or device action.
- An independent reviewer verifies that all old v2 writer and inherited-FD/group bypasses are excluded from *custody*, without conflating this with source writer quiescence. Previously observed M0 negative controls must be rerun, not assumed fixed.
- A transaction/recovery design identifies **one** committed authority, immutable package/version identities, policy/issuer identity, protected high-water, durable acknowledgement and exact crash-state reconciliation. No unbounded nest of cleanup journals.
- Target filesystem support is measured in a **disposable** isolated environment, including no-clobber and directory fsync; kernel/mount/LSM/user namespace behavior is not guessed.
- A separately evaluated issuer trust anchor and source P0/P1 same-epoch witness are available for any **real project bytes**. If not, the lab remains synthetic, independent of a production Collector.
- A least-privilege privacy/retention/security rollback plan, gate stop conditions, and a pre/post operator checklist exist. Passing unit tests alone cannot fulfill these real process/OS attestations.

**Stop on first missing gate:** no root or production trial. No promise of confidentiality or storage durability is made by this design.

## 7. Decision and next useful PR

**Current decision = P3_NO_GO_DEPLOYMENT_UNVERIFIED.** Keep a conditional design preference for P3-C2 only if future evidence demonstrates genuine independent administrative control and verified high-water state; otherwise remain fail closed, do not implement a same-UID custodian or add another self-certified in-memory journal.

**Highest-value next work (only if owner requests):** a **read-only feasibility inventory specification** with a bounded, nonprivileged command manifest for a wholly disposable Debian location, and a human-reviewed plan for actual two-principal adversarial tests. Do NOT provision the principals or modify the guest under this PR. An alternative is to decide explicitly that local independent custody cannot be provisioned and stop M6.0 operational export rather than spin additional lab layers.

**Implementation/no-go ceiling:** production M0 v2→v3, trusted W1 Seal, active-WAL R1, source DB+JSON same-epoch export, real snapshot producer, signing service, protected Custodian, public Collector/CLI and Worker/Task authority all remain **NO_GO**. Existing B-Diagnostic bundles remain incomplete/inconsistent with assessments=[], without independent source verification.

**Review classification:** docs and machine-readable **nonauthorizing** decision only, not new ADR or permission. No executable code, systemd unit, AppArmor profile, key, database or user project is modified by this PR.
