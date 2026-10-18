# M6.0 M0o — Proposed Debian/KVM Closed-World Offline Writer-Embargo Deployment Profile

**Status: ARCHITECTURE PROPOSAL / OWNER REVIEW REQUIRED / NO OPERATIONAL AUTHORIZATION.**
**Baseline:** `main@0f1dac4338777e264167fa6207c5aab397e154a9` (M0n PR #84 merged).
**Governing decisions:** ADR-039 read-only, non-authoritative Trace export; ADR-040 Path A verification-only trusted Seal. Existing M0c offline cutover remains an unimplemented admission design. **v2→v3 production migration, writer Seal, R1 WAL Reader, Collector and CLI remain NO-GO.**

## 1. Decision boundary: one candidate, not a claim about the current VM

**Propose exactly one supported *pilot* topology, named `D13-KVM-EXT4-SINGLE-UID-ROOT-GATE-v1`:**

| Dimension | Required pilot constraint | What is actually established now |
| --- | --- | --- |
| Compute | One *new, isolated, disposable*, Debian 13 KVM/QEMU guest under operator control | Earlier Debian KVM guest was used for test-only M0h–M0n; **not qualified as the proposed closed-world topology** |
| Filesystem | One guest-local ext4 volume with owner-protected project and separate private backup area; no host bind, virtiofs, NFS, CIFS, FUSE, overlay/union, shared-volume or remote writer route | Existing lab confirmed only `/var/tmp` ext4 and `kvm`; that does not attest remote access or all aliases |
| Writer identity | One **dedicated, static, unprivileged service UID**, distinct from operator/root, with no interactive shell, no sudo, no additional launch credentials, no untracked shared group write privilege | **Not established**; the historical `ehsan` lab account with sudo is not eligible as this writer UID |
| Start authority | A root-controlled, audited systemd system-unit family and all known CLI/provider/child entry points; no reachable user-unit, cron, timer, socket, path-unit, manual `exec`, `systemd-run` or external API bypass | **Not established**. The systemd service manager is only a scoped lifecycle mechanism, not a global executable ban |
| Maintenance authority | Independent operator/root-owned controller with sole permissions to hold embargo and manage backup; writer credentials do not control root-owned gate, ownership, unit configuration or evidence | **Not established** |
| Project scope | Exactly one explicitly operator-selected, descriptor-anchored real v2 ProjectCTL source and its full DB/WAL/SHM + external JSON/inode ancestry; all aliases and writable destinations inventoried | **Not established** |
| Trust boundary | Single trusted guest administrator/root, no additional untrusted privileged actors, no remote mounts/containers/user namespaces with equivalent file authority | **Not established** |

This *constrained pilot* is a proposal for a future, separately authorized guest implementation. **M0o itself neither provisions that VM nor approves running privileged commands anywhere.** A shared multi-user developer workstation, current `ehsan` sudo checkout, unreviewed remote filesystem or arbitrary production project is OUT OF SCOPE. If the operator cannot constrain and prove the topology, reject Path A admission and consider the staged v2-compatible alternative in section 6.

## 2. Why the independent barrier must be two-layered

M0b/M0d/M0f/M0g/M0h/M0k/M0l/M0m/M0n collectively show an unmodified v2 `RunStore` can ignore a newly invented `flock`, lease or process supervisor; late independent writers and process-group escape exist; a namespace read-only *view* leaves other aliases writable; and Linux DAC can deny fresh opens but **cannot revoke old writable FDs**. M0n further paired an actual writable-FD inode witness with a pidfd exit for a *known, owned* process while outsiders still wrote.

The proposed embargo needs **two independent controls, neither sufficient alone**:

- **Launch/lifetime control:** root-controlled supervisor/operator prevents all eligible *managed* service/unit/timer/socket restarts, tracks descendants and termination, and accounts for all other launch surfaces. Masking a unit blocks that unit's activation; it does **not** make direct execution of the old binary impossible. A stopped cgroup, process-list snapshot or empty SQLite lease is evidence about one surface only. Before any admission, an independent reviewer must establish the closed-world launch authority for the deployment.
- **File-access control:** root-owned, inode/path-scoped DAC boundary denies *new* ordinary accesses by the dedicated writer UID to all authoritative DB+WAL+SHM, parent directories, file-replacement JSON staging/destinations and aliases. A single read-only bind namespace or per-process Landlock constraint is not a universal boundary. This is a **design obligation**, not permission to run the M0m fixture `chown` recursion on a real project.

**Order and race:** operator first reserves exclusive maintenance/entry authority; prevents known supervised starts; establishes an independent **deny-new-open** filesystem boundary; then drains/kills and reconciles all already-open writers, including children and handed-off descriptors. A writer opening just before DAC denial is **still an old-FD holder** and must be drained. Once the gate is held, independently test that ordinary late nonroot v2 DB/JSON attempts fail; an otherwise runnable old binary must not be able to *write*. A trusted root/capability actor is **outside DAC's protection** and must be explicitly included in the closed trust boundary. Do not infer drain from the order of operations or an empty cgroup.

**No safe root-driven ownership algorithm is selected by this document.** A production-grade pilot must first prove inode identity, path-ancestor anchoring, no symlinks/hardlinks, mount/namespace exclusions, no unsafe recursive race, safe transition and restoration of ownership/ACLs, and no newly writable alias. M0m's test-only `rglob + chown` must never be repurposed as a production migrator.

## 3. Full writer / file-surface inventory to be signed off

A complete per-project inventory must explicitly bind every relevant code entry point *and* OS launch authority. Minimum writers: `RunStore` create/event/transition/lease/heartbeat, Verification/Execution and evidence JSON publication, worker/provider descendants, recovery/rebind, scheduler and integration, other CLI/direct Python API clients, timers/sockets/restarts, any detached process or writer using an already-open database/JSON FD. Inventory the way each writer obtains its credentials and FDs, and how it exits and is barred from re-entry.

For **each** source inode, verify identity and ordinary/writable access paths for:
`state.sqlite`, `state.sqlite-wal`, `state.sqlite-shm`, JSON evidence/verification/manifest files, staged/rename destinations, directories and ancestry, historical copies, symlinks, hardlinks, bind mounts, alternate mount namespaces and separately writable artifacts. Nonexistent WAL/SHM today does not prove they cannot be recreated later. Unexpected hardlink count, unstable inode, unreviewed path or remote route => **NO-GO**. A list of paths/units is not a proof of complete scope if independent writers or aliases may exist.

The source project must never be inferred from `cwd`, an environment variable alone or arbitrary caller input. The maintenance controller must externally pin the selected project identity and relevant mount/volume boundaries; the backup target needs separately reviewed private ancestry, retention and durability.

## 4. Required finite-state maintenance protocol (FUTURE DESIGN ONLY)

States are *conceptual* and **none are executable or authorized by M0o**:

| Phase | Minimum entry evidence | Failure path |
| --- | --- | --- |
| `UNQUALIFIED` → `SCOPE_APPROVED` | One operator-signed deployment/source/UID/FS/cross-namespace/restart inventory and explicit downtime authorization | Unknown actor, alias, identity or UID → `NO_GO_TOPOLOGY` |
| `SCOPE_APPROVED` → `OPEN_DENIAL_HELD` | Independently held root-owned ownership/start gates; direct fresh old-v2 DB+JSON denial at every controlled entry route; protected gate itself cannot be modified by writer UID | Any late write, independent start with access, or ownership/path drift → `NO_GO_BARRIER_BYPASS` |
| `OPEN_DENIAL_HELD` → `FD_DRAIN_RECONCILED` | All live and potentially escaped writer descendants/FD holders inventoried and fully gone, including inherited/SCM_RIGHTS descriptors; inspect complete declared mount/UID scope; continuous gate witness | Any surviving/unknown writer or preopened fd → `NO_GO_UNDRAINED_FD` |
| `FD_DRAIN_RECONCILED` → `BACKUP_ELIGIBLE` | Verified **continuous** root gate, anchored source v2 identity/history/integrity, no legacy lease, independent fixed project/JSON evidence epoch, separately reviewed WAL-inclusive backup protocol | Unknown epoch, weak backup/fsync/retention or uncertain gate → `NO_GO_BACKUP` |
| `BACKUP_ELIGIBLE` → `MIGRATION_ELIGIBLE` | Only a *later* dedicated, explicitly owner-approved operational M0 candidate, reviewed SQL/old-client compatibility and durable recovery path | No operational candidate approval → `NO_GO_MIGRATION_NOT_APPROVED` |
| `MIGRATION_ELIGIBLE` → `RECONCILED` | Independent commit-outcome reconciliation, v3 schema/indices/event-prefix invariants, backup validity, no historical lease promotion; gate never dropped | Interrupted/unknown COMMIT, disk/fsync fault → **QUARANTINE**, no blind retry, reopen or restore |
| `RECONCILED` → `RELEASE_ELIGIBLE` | Explicit separate owner release; **only compatible v3 writer** has W1 generation/token + file mutex + single-transaction Seal semantics; old-v2 restarts blocked | W1 unimplemented / old v2 can reopen → `NO_GO_RELEASE` |

This does **not** merge SQLite and JSON into an atomic cross-store snapshot. A later actual trusted writer must publish durable file bytes and a Seal in the designed Verification epoch. R1 independently needs read-only/non-mutating WAL access with coherent Seal consumption. Backup and source-reader roles must remain separate.

## 5. External-authority acceptance invariants and fault model

To advance beyond review-only, a *future* disposable privileged guest pilot must show, with independent observation rather than user-provided `True` booleans:

1. The **actual systemd units and every restart trigger** are held barred, the dedicated UID cannot change the embargo, and a direct unmodified v2 interpreter cannot write to the protected target. Demonstrate service restart, timer/socket activation, CLI/direct Python, provider child and background heartbeat cases (or disqualify the environment).
2. The independently controlled filesystem gate covers **new opens, sidecar creation and JSON stage+replace**, including alias/mount view cases. Unsupported symlinks/hardlinks/capabilities/remote routes must fail closed.
3. A known v2 writer **already holding DB and JSON FDs before the fence** cannot survive the declared drain. Test inherited/duplicated/escaped FD holders and cooperative/noncooperative shutdown, with independent FD identity and release observation; a numeric PID or `cgroup.procs=0` alone is insufficient.
4. Faults at the boundary (new start racing embargo, exit timeout, EPERM/EACCES, PID reuse, unit restart, disconnected supervisor, power loss, locked SQLite WAL, user/group change, filesystem/mount shift) must return **NO-GO/QUARANTINE** and never resume v2.
5. The barrier remains continuously in force from operator admission **through** WAL-inclusive private backup, candidate migration, ambiguous-COMMIT reconciliation, recovery and explicit controlled release. No sampling window, timer or external caller may silently release it.
6. Private evidence must bind VM identity/provenance method, exact program SHA, source+inode/fs identity, barriers, detected actors, test actions/negative witnesses, backup identity, operator decisions and timestamps, with confidentiality controls. Logs can corroborate observation but **cannot authenticate themselves**; user-supplied booleans and JUnit/console logs are never remote attestation.

Do not use unprivileged named user/group observations as a proxy for controls over root/CAP_DAC_OVERRIDE or separate machines. If those adversaries are in the allowed deployment scope, this profile **cannot be approved**.

## 6. Design choice and scope-control checkpoint

**Preferred bounded proof path:** a *separately proposed*, disposable guest-only independent embargo prototype for profile `D13-KVM-EXT4-SINGLE-UID-ROOT-GATE-v1`. It may require root inside the *reviewed guest* in the future, **only after a new PR and exact opt-in**; no application or production migration can run from this document.

**Fallback if the closed-world topology cannot be proven:** revisit ADR-040's phased **v2-compatible cooperative writer rollout** (Option B) or defer operational M0. Cooperative locks alone do not retroactively stop live unmodified v2 writers, so even Option B still requires one trustworthy cutover boundary.

**Stop rule:** do not add further generic negative writer-scope labs after M0n. M0o must resolve (a) owner acceptance/rejection of the *profile assumptions* and (b) a separately controlled privileged-guest implementation acceptance plan. If any gate cannot be made independently testable, record `NO_GO_UNSUPPORTED_DEPLOYMENT` and return to product scope/ADR review instead of accumulating more experimental PRs.

**External technical references (behavior only, never deployment attestation):**
- [systemctl(1): unit masking/activation and lifecycle](https://www.freedesktop.org/software/systemd/man/258/systemctl.html)
- [systemd.exec(5): UID, StateDirectory and namespace caveats](https://www.freedesktop.org/software/systemd/man/257/systemd.exec.html)
- [open(2): file descriptors, opened file descriptions and inode/path identity](https://man7.org/linux/man-pages/man2/open.2.html)

**No files under `projectctl/`, service units, sudoers, production SQLite, schema versions, application authority, W1 writer or R1 Reader are modified in M0o. Merging the design does not imply a GO decision.**
