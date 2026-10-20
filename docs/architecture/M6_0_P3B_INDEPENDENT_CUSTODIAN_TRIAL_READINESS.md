# M6.0 P3b — Independent Custodian Trial Readiness Gate

**Status:** DESIGN + OFFLINE REVIEW ONLY — P3B_NO_GO_TRIAL_UNAUTHORIZED (2026-10-20).
**Pinned baseline:** merged P3a PR #107, main@d68a80120f7ba8be6d56bad2465950536ae8d509.
**Contract inheritance:** ADR-039 (source-read-only nonauthoritative Trace), ADR-040 Path A (future writer-published as-of Seal, DESIGN ONLY), R0b C (active v2 WAL fail-closed), and P3 C2 (conditional separately credentialed static custodian). All P0–P4 real proofs remain UNVERIFIED/NO_GO. No existing Worker/Task privilege changes.

## 1. Decision from P3a observation

A Debian ordinary-user P3a observation was supplied separately by the operator: a candidate *example* /tmp appeared as a read-write tmpfs with a shared writable, sticky directory. This is **not a viable target for durable Custodian storage**: observing a tmpfs mount never proves persistence across reboot; sticky-bit protections do not provide independent custody. The observed current user's absence of effective capabilities is NOT evidence about legacy-v2 writer groups, inherited FDs, namespaces, the proposed service identity, or the kernel's denials. The PR does not reproduce the raw observation, numeric identities, host release, private locations or raw /proc contents.

**Verdict:** P3B_NO_GO_TRIAL_UNAUTHORIZED. No alternative candidate durable filesystem has been selected or independently inspected. Even a plausible ext4/xfs/btrfs label would be **UNVERIFIED**, not GO: directory ancestry, real mount semantics, remount options, snapshot/rollback scope, code origin, ACL/LSM policies and independent administrator all require separate witness.

## 2. Offline review implementation (does not implement custody)

The standalone script scripts/p3b_trial_readiness_review.py reads **one** bounded P3a JSON object from stdin (maximum 16 KiB) and prints a *path-free, identity-free* JSON review to stdout. It never opens a file, socket, database, or filesystem inventory source; never launches a child, writes a file, provisions an account, or invokes privileged tooling. The review rejects duplicate keys, extra keys, raw/path-bearing fields, unexpected source decisions, attempts to assert any authorization, missing P3a unknowns and structurally inconsistent ancestry.

Example for a previously reviewed **sanitized P3a JSON** only, using an operator-managed shell pipe:

    python scripts/p3a_nonprivileged_inventory.py --candidate-dir /tmp | python scripts/p3b_trial_readiness_review.py

The example is an *observation of a known disposable metadata target*, not approval to store Custodian data in /tmp or to create anything there. Run with a normal user, never with sudo. The P3b CLI refuses root execution. It emits no input values, UID/GID, kernel release, filesystem name, hostname, device, mountpoint or project path: only fixed enums, fixed blockers, and all-false authorizations. Invalid input exits with a fixed refusal. A successful exit indicates only that the review ran and emitted NO_GO.

**Trust ceiling:** P3a output is supplied by the calling user. Shape checks cannot authenticate the kernel, a mount table, a producer, an administrator, or source data. Test success is not a substitute for actual independent kernel/OS and restart observations.

## 3. Threat boundary that a future disposable experiment must declare

| Threat | Proposed treatment | Required independent future witness |
| --- | --- | --- |
| Existing ProjectCTL user and uncooperative v2 writer | Adversarial within project credentials, groups and all old launch paths | Denials on actual *custody* paths, executable/config, IPC and ledger, including GIDs, ACL/LSM, symlink/hardlink/mount aliases and inherited writable FDs |
| Custodian process/code itself | Trusted only if separate static principal and admin-controlled binary, imports, config, ancestors | Independently verified provisioning, effective filesystem IDs, capabilities, source provenance and update policy |
| Caller/producer, fake PID, claimed issuer | Untrusted until separate P2 proof and P0/P1 source Seal | Signed/authenticated receipt policy and trusted DB+JSON source epoch; AF_UNIX peer UID by itself is insufficient |
| Crash, missing ACK, disk-full, replay or checkpoint restore | Adversarial fault model; never automatically retry | Exactly one authoritative durable commit, independent protected high-water, directory fsync and fresh-process/reboot readback |
| Host administrator/root, malicious VM snapshot/host-disk rollback | Explicitly **inside TCB** for local C2 design unless threat scope is enlarged | If root/host rollback must be prevented, choose a separate external/hardware monotonic authority; otherwise STOP, no misleading protection claim |
| Reader/public output | Untrusted for original source coherence without P0/P1/P2/P3 | P4 gate, redacted bounded artifacts, retention and no active v2 WAL access |

A static UID with writable code/config or a shared UID/FD/group does **not** establish the trust boundary. An in-memory replay model or checksum is not independent monotonicity. The owner must identify an independent administrator separate from the ProjectCTL operator/legacy writer; otherwise no C2 trial is meaningful.

## 4. Explicit decision record before any real two-principal trial

A separate *future* owner-reviewed approval is needed, recording all of the following; none is supplied by this PR:

1. **Disposable-only boundary**: target guest/VM ID, ownership, no project/production DB, no real secrets, no user workspace mutation, source/reset snapshots and cleanup/retention plan.
2. **Threat scope and TCB**: who is the trusted administrator/root/host, whether whole-VM rollback is in or out of scope, whether external trust anchor is demanded.
3. **Concrete filesystem and custody location**: a never-before-used disposable **non-tmpfs** candidate; exact mount, overlay/bind/namespace/idmap/ACL/LSM facts, parent permissions, device/filesystem support and fsync/no-clobber plan; no implicit substitution of /tmp.
4. **Two principals and code origin**: identities, UID/GID/supplementary groups, effective/bounding capabilities, protected binaries/import paths, service manager configuration, IPC credentials and preopened FD policy; active legacy writer negative witness, not a cooperative mock.
5. **Single authoritative receipt/ledger commit**: object staging, pinned bytes, file and directory fsync, unoverwriteable identity, atomic record and high-water, one linearization point, restart readback and quarantined orphans; never treat two renames as one transaction.
6. **Source and issuer separation**: P0/P1 and P2 remain unmet for real data. Future experiments must use **synthetic data only** until source coherence and authentication are proven independently.
7. **Fault injection and independent witness**: privileged steps/commands reviewed in a distinct approval, precise kill/ENOSPC/EIO/corruption/reboot cut points, second principal to observe each rejection, immutable evidence location and typed failures.
8. **Privacy, budget, blast radius and abort**: finite artifacts, no raw project prompts/tokens, no export endpoint, cleanup plan with retirement witness, stop at first unexplained bypass, no wildcard destructive cleanup.

Even a fully completed human approval would authorize only the precise disposable experiment described there, never production P0–P4, v3 migration, W1, R1, Collector/CLI or any background service.

## 5. Mapping to the existing P3-F01–F28 matrix

Use the **existing** P3 matrix; this PR does not claim to run or close any case.

| Evidence family | Required trial episodes | Admission rule |
| --- | --- | --- |
| Credential & code (F01–F08) | chmod/rename denials, old GID/FD/service start routes, admin-owned code and spoofed IPC | All legacy routes denied under independent witness or NO_GO |
| Blob identity (F09–F11) | symlink/alias and TOCTOU no-follow; simultaneous identical-content publishers | No overwrite/replacement, source bytes pinned, or NO_GO |
| Protected sequence (F12–F14) | old ledger + SHA rollback, VM restore threat declaration, issuer revocation at commit | Independent high-water survives allowed rollback scope; otherwise NO_GO |
| Durability & recovery (F15–F25) | file/dir fsync, ledger ordering, filesystem support, SIGKILL/reboot, lost ACK, EIO/ENOSPC, retirement | No ACK before durable linearization; ambiguous ACK quarantined; independent restart readback or NO_GO |
| Privacy & source authority (F26–F28) | redaction, mixed-epoch signed bytes, attempts at public CLI/WAL access | No real source until P0/P1/P2 proven; no output or new Worker/Task authority |

For each episode require test ID, **separate observing principal**, pre/post kernel-level denial or readback, exact cut point, negative control, artifact hash tied to an independently protected record, and a human reviewer. Negative controls must include syntactically valid self-hashed malicious/old objects. Any untested or ambiguous episode remains FAIL-CLOSED, not PASSED.

## 6. P3b acceptance and operator-only checks

- **P3b code acceptability:** bounded parse, no input reflection, no host privileges or source reads, all outputs contain decision P3B_NO_GO_TRIAL_UNAUTHORIZED and false authorizations; negative tests and CI pass.
- **P3b operational finding:** always NO_GO. Passing parser tests cannot certify a particular directory or trial readiness.
- **Future design review output:** choose a disposable target and independent administrator **in another PR**, with explicit human approval and exact actions. If impossible, STOP M6.0 operational custody rather than accepting a same-UID surrogate.

Operator on Debian, as ordinary user, after branch review:

    python -m pytest -q -rs tests/test_m60_p3b_trial_readiness_review.py
    git diff --check d68a80120f7ba8be6d56bad2465950536ae8d509..HEAD

Optional non-mutating pipe (run only after reviewing both scripts):

    python scripts/p3a_nonprivileged_inventory.py --candidate-dir /tmp | python scripts/p3b_trial_readiness_review.py

Neither creates files or installs services. **All operational authorities remain NO_GO.**
