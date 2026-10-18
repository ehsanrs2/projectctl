# M6.0 M0o — Operator/Reviewer Decision Record and Executable-Pilot Exit Criteria

**Status: NOT FILLED / NO PROOF / NO AUTHORITY.** This is an architecture review sheet, not a machine-readable admission permit. No reviewer response, checkbox, `true` value, uploaded stdout, GitHub CI result or `sudo` credential can authorize migration.

**Candidate profile:** [M0o Debian/KVM closed-world deployment profile](M6_0_M0O_DEBIAN_KVM_CLOSED_WORLD_DEPLOYMENT_PROFILE.md), revision `D13-KVM-EXT4-SINGLE-UID-ROOT-GATE-v1`.
**Repo baseline:** `main@0f1dac4338777e264167fa6207c5aab397e154a9`; M0n PR #84 merged after 28 operator-reported VM test cases passed, with previously reviewed CI `1089 passed, 6 skipped`. Neither set of observations qualifies a real deployment.
**Decision default:** `NO_GO_M0O_TOPOLOGY_UNVERIFIED`. Explicit owner review may accept *only* this proposed test topology and the next pilot test plan; operational migration stays NO-GO.

## A. Candidate coverage and independent evidence requirements

Every row below is initially **UNVERIFIED**. Only a later owner-approved independent pilot can mark actual enforcement **OBSERVED**; M0o design acceptance may instead mark a requirement **REVIEWED FOR FUTURE PILOT**, never **PROVEN**. Evidence must be collected for a specific disposable VM, source fixture and fixed program SHA. A passing controlled-case test **cannot** stand in for untested scope.

| Gate | Exact qualification requirement | Independent/negative proof that a later pilot must supply | State at M0o |
| --- | --- | --- | --- |
| P0 — Owner/time/scope | Explicit one-project downtime, independent root/operator ownership, disposable VM identity and no host/prod mounts | Offline guest inventory and approved source/device boundary, separate confidential review | UNVERIFIED |
| P1 — Dedicated writer credential | Static dedicated unprivileged UID; no sudo, interactive/shared credential, group privilege, CAP_DAC_OVERRIDE, root equivalent or untracked user namespace | Root-owned UID/credential inventory, direct old-v2 process and alternate credential challenge | UNVERIFIED |
| P2 — Filesystem closure | Local ext4 only; strict pinned project/DB/WAL/SHM/JSON/staging identity; no unreviewed hardlink, symlink, bind/remote mount, inode swap, filename replacement or sidecar recreation | Independent path/inode/mount inventory and fail-closed alias/sidecar probes | UNVERIFIED |
| P3 — Start gate | All service, timer, socket, path unit, restart and independent CLI/direct API launchers inventoried and root-held; same-UID late writer denied by filesystem gate even if it executes | Trigger each claimed start class during hold; a process start **alone** is not failure if write is denied; any write **is** failure | UNVERIFIED |
| P4 — FD and descendant drain | All writers preexisting or racing gate, descendants, escaped session/cgroup, inherited/duplicated `SCM_RIGHTS` FD and root-capable actors either definitively excluded or drained | Preopen live SQLite+JSON FDs, race new opens, verify *all declared holders* gone; no reliance on a single PID, empty cgroup or process snapshot | UNVERIFIED |
| P5 — Independent continuous barrier | Root authority holds both access/start controls despite controller crash, timeout, failover, service automatic restart and alias attempt | Independent cross-time barrier witness; power/kill/restart tests; halt/quarantine on unknown interval | UNVERIFIED |
| P6 — WAL-inclusive backup | Source v2 application ID/history `[1,2]`, resolved legacy lease; anchored owner-private WAL-inclusive backup with trusted no-clobber publication, file+directory fsync, retention and independent verification | Faults before/after publication, disk-full, backup integrity, old-v2 mutation challenge during backup | UNVERIFIED |
| P7 — Cutover/recovery ambiguity | Exactly reviewed candidate v3 DDL/compatibility; commit-unknown quarantine, no automatic restore/retry, retained source and backup identities | Fault/kill/power-loss tests and independent state reconciliation across v2/v3 WAL/history | UNVERIFIED |
| P8 — Release | Old-v2 client denied; only reviewed v3 W1 writer fencing+Seal, explicit operator-approved release and durable file publication | Old-v2 restart attempts before/after release, W1 generation/token/JSON mutex, single SQLite transaction test | UNVERIFIED |
| P9 — Reader/product separation | R1 source WAL Reader non-mutating and coherent with Seal; real Collector/assessments/CLI separately validated; never use backup probe as exporter | Independent WAL/SHM byte/inode metadata read-only proof, correct as-of Seal binding, privacy and non-authority tests | UNVERIFIED |

**Hard dependency:** only P0–P5 govern independent exclusion design/guest pilot; P6–P9 still block any *operational* migration/release/Trace capability even if every earlier gate eventually succeeds. Positive M0m/M0n test behavior does not satisfy P3/P4 because the outsider remained writable in the admitted test scenario.

## B. Non-negotiable refusal examples

The reviewer must reject an admission claim whenever any of these is possible or untested:

- Unmodified v2 can run as a privileged/root actor, borrow `sudo`, obtain a root helper, access via a hidden mount/user namespace, a second guest/remote client, a duplicated FD or an alias outside the ACL/DAC boundary.
- `systemctl stop`, `systemctl mask`, `KillMode=control-group`, empty `cgroup.procs`, `ps`/PID lists, clean SQLite lease rows, two matching samples, or a newly invented `flock` is the **only** evidence of no writers.
- `chmod`/`chown` is presented as revoking pre-opened FDs, or a process's pidfd exit is presented as draining FDs inherited by other processes.
- SQLite DB is blocked but WAL/SHM, directory `O_CREAT`, JSON temporary staging + replace or backup destination remains writable, or another hardlink still reaches the same inode.
- A developer's working VM, production/host mount, or existing `ehsan` sudo identity is silently treated as the dedicated isolated writer profile. A root-equivalent administrator must be in the explicit trusted-controller scope, not an untrusted writer.
- A freeze/timeout/commit exception silently drops the embargo or automatically restores/reopens projects and old-v2 clients.
- A positive GitHub test suite, self-reported operator JSON or unverified review signatures are treated as independent enforcement or provenance attestation.
- A valid migration rehearsal is equated with a working W1 trusted Seal or R1 read-only live-WAL Reader. Both remain separate mandatory gates.

Any exception or unanswered ownership question is **NO_GO_UNSUPPORTED_DEPLOYMENT**, **not** an authorization override.

## C. Decision outcomes, with strict ceiling

These labels are **human review categories**, not callable `GO` statuses:

| Reviewer decision | Permitted consequence | Forbidden consequence |
| --- | --- | --- |
| `NO_GO_M0O_TOPOLOGY_UNVERIFIED` | Request missing topology/evidence and keep ordinary tests isolated | Claim closed-world deployment |
| `NO_GO_UNSUPPORTED_DEPLOYMENT` | Revisit Option B cooperative rollout or scope/ADR | Migrate, restore, restart old clients |
| `M0O_DESIGN_ACCEPTED_FOR_GUEST_PILOT_SPEC_ONLY` | Write a **new Draft PR** for a private, disposable, operator-opt-in implementation and adversarial acceptance matrix | Treat systemd/DAC as already enforced; change real service, permissions or database |
| `PILOT_OBSERVATIONS_REVIEW_ONLY` | Later review independently captured guest evidence tied to exact SHA | Auto-admit production migration |
| `NO_GO_BARRIER_LOST_OR_COMMIT_UNKNOWN` | Quarantine, preserve private backup/evidence, operator-specific recovery | Blind restore/retry, premature service release |

**No path in M0o returns or implies `authorizes_migration=true`.** Even future `M0O_DESIGN_ACCEPTED_FOR_GUEST_PILOT_SPEC_ONLY` is not operational acceptance. The actual migration/backup/W1/R1 work requires separately approved security/recovery/product PRs and evidence.

## D. Minimal future pilot acceptance matrix (not executed in this PR)

A future **separate privileged guest-only PR** must include a non-mutating `--inspect` mode, explicit disposable VM/root/operator acknowledgment for each mutating action, no arbitrary project path, no host/production namespace/mount access, no service changes outside a uniquely named script-owned pilot unit, bounded cleanup and independent provenance plan. It must test:

1. **Expected denial:** new old-v2 process (including late manual executable, timer, socket and service-triggered route) cannot modify project DB, WAL/SHM or independent JSON once embargo held.
2. **Old-FD survival *before* drain:** deliberately preopen both DB/JSON descriptors and prove the new-open DAC barrier alone is insufficient; **do not claim gate passed yet**.
3. **Drain before admission:** stop all pilot-owned writer descendants and any inherited/duplicated FD holders, and show independent tracked exit; if an outsider remains, reject without upgrading.
4. **Race/failure:** concurrent new open, supervisor restart, malicious/faulty restart order, service escape, filesystem alias/path swap, SIGTERM refusal, controller crash/disk error each produce bounded fail-closed outcomes.
5. **Continuous hold:** independent observations that no write occurs from the last verified drain until the *simulated* maintenance/recovery/release boundary; use dummy actions, **no v2→v3 migration**.
6. **Evidence:** operator-specific guest evidence stored privately with exact source SHA, negative test results, cleanup status, supported topology record and explicit redaction of project/credential data. A test runner's own assertion is never remote attestation.

The real guest pilot must not depend on `newgrp`/sudo tricks that bypass identity validation, and must not modify an existing project. Test-only root operations demand a separately reviewed runbook **after** a Draft PR; M0o deliberately contains no executable `sudo`, `systemctl`, `chown`, `kill` or SQL commands.

## E. Reviewer sign-off information to record privately (not secrets in the repository)

- Proposed pilot VM identity, disposable snapshot provenance and isolation review.
- Dedicated service UID and distinct root operator trust assignment.
- Fixed path/inode/volume/alias inventory and complete actor+restart-source ownership inventory.
- P0–P5 evidence plans, explicit residual unsupported scenarios, timeout/quarantine and rollback/recovery owner.
- Decision: **UNREVIEWED** until owner explicitly accepts/rejects the design constraints, then independently accepts future pilot scope.
- Exact proposed next PR contract, maximum authorized blast radius, cleanup plan and *no migration* statement.

## F. Review discipline

This PR contains **documents only**, no new security implementation or synthetic decision-policy tests. Require exact-head GitHub CI to remain passing and a manual threat model review. **Do not merge automatically.**

**If the owner accepts this profile, the next milestone is a controlled, dedicated disposable-guest proof of independent root-owned admission and complete writer/FD drain — not another generic diagnostic lab and not operational v2→v3 migration.**
