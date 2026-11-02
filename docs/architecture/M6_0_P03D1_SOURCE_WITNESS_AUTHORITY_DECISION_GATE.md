# M6.0 P03-D1 — Source-witness authority and as-of epoch topology decision gate

**Status: PROPOSED / OWNER DECISION REQUIRED / DOCUMENTATION ONLY. No authority or deployment approval.**

**Pinned review baseline:** merged P02 PR #123, `main@b4f087dc324788e58de7b9774ab2e62f782ea567` (2026-11-02).

**Governance:** ADR-039 accepted local non-authoritative, strictly read-only Trace design; ADR-040 accepted narrow Path A *design*; R0b chooses route C, active WAL fail-closed. P01 (#121) tests a hypothetical independent oracle; P02 (#123) falsifies promotion of a self-hashed receipt into provenance. The preserved P3i–P3n synthetic custody trials are separate and do not establish source admission.

## 1. Exact problem and selected scope

The next necessary step is not another synthetic receipt schema. It is a decision about **who** can independently establish a source epoch and **what durable evidence** binds that claim to actual ProjectCTL state. A SHA-256 of sequentially copied state.sqlite + JSON, a JSON field `epoch`, a signed manifest, a systemd unit name, or a test oracle constructed from the package is not P0/P1 evidence.

Initial eligible lifecycle boundary **only**: successful, non-review `VERIFYING -> READY_TO_INTEGRATE` for one selected project/run/task, after exact `verification-manifest.json` and `evidence-manifest.json` bytes are durably published. No review/PASSED, integration, remote provider completion, historical repair or automatic source migration is in scope.

**Decision this PR makes:** prefer *investigating S3* (cooperating trusted writer + independently verifiable retained as-of Seal) because it matches accepted ADR-040. **Decision it deliberately does NOT make:** no approval to implement S3, assert a deployed controller/issuer/custodian, lift R0b C, or touch an operational source. A conditional S2 fallback remains unselected and unproven.

## 2. Existing facts and what remains missing

| Source / finding | Established or documented | Does not establish |
| --- | --- | --- |
| [ADR-040](../decisions/ADR-040-trace-snapshot-publication-consistency.md) | Accepted Path A *design* requires durable fixed-leaf bytes, file + parent-directory durability and one DB transaction with Run transition, events and immutable Seal | A real writer, independent issuer, retained historical bytes or non-mutating WAL Reader |
| [W0 protocol](M6_0_W0_WRITER_FENCING_AND_SEAL_PROTOCOL.md) | Candidate generation/token + per-run artifact mutex, and proposed status/event/Seal transaction | All existing v2 writers cooperate or are excluded |
| [M0o closed-world profile](M6_0_M0O_DEBIAN_KVM_CLOSED_WORLD_DEPLOYMENT_PROFILE.md) | Candidate isolated Debian 13/KVM/ext4, root-controlled entry embargo, distinct static writer UIDs, FD drain and independent maintenance control | That any current VM is qualified, old starts are globally denied, or source migration is approved |
| [M0q origin](M6_0_M0Q_EXECUTION_ORIGIN_AND_START_AUTHORITY.md) and M0r | Python import/exec path and candidate credentials can undermine assumed code identity; a confined unit does not confine unrelated same-credential code | Executable provenance or global mandatory launch authority |
| [R0b](M6_0_R0B_CURRENT_WAL_FAIL_CLOSED_DECISION.md) | Active v2 ProjectCTL WAL and separately published JSON lack a proven nonmutating, same-epoch read | Permission to use mode=ro, query_only, immutable=1, SQLite backup or double-copy as a trusted exporter |
| [P3 custody feasibility](M6_0_P3_TRUSTED_CUSTODY_DEPLOYMENT_FEASIBILITY.md) + P3i–P3n trials | Bounded synthetic custody/no-clobber/normal-reboot observations | Real package issuer, real source epoch, host power-loss durability, rollback resistance or P0/P1 success |
| [P01](M6_0_P01_SYNTHETIC_MIXED_EPOCH_ADMISSION_GATE.md), [P02](M6_0_P02_SYNTHETIC_RECEIPT_PROVENANCE_GAP.md) | Pure negative control for mixed/current/forged oracles and self-attesting receipts | Truth of a test oracle or external authenticated evidence |

Real state as of this baseline: production ProjectCTL project state remains v2; real W1 Verification Seal not installed; Reader deliberately refuses active WAL; P0, P1, P2, P3 and P4 operational evidence all **UNVERIFIED / NO_GO**.

## 3. Trust-domain ownership: no invented actors

| Boundary | Future responsibility and minimum evidence | Trust failure/refusal | Owner / current fact |
| --- | --- | --- | --- |
| **P0 admission controller** | Pin one source identity, fixed FS/namespace/UID topology, DB schema/history and exact allowed paths; hold independently governed old-writer *start* and *fresh-write* denial continuously; reconcile live/preopened writable FDs and aliases before capture | Process-list-only, cooperative `flock` only, old v2 direct start, inherited SCM_RIGHTS FD or writable alternate alias: `NO_GO_P0` | Root/controller with exclusive authority only a **proposed** trust model; no actual approved deployment/owner evidence |
| **W1 source writer** | Immutable reviewed code+imports, independently controlled launch identity, monotonic fenced generation/token, no-follow durable exact file leaves, **one** SQLite Run status + events + Seal commit under same run mutex | Old code with candidate UID/GID, mutable executable/imports, files without parent fsync, two separate commits, ambiguous commit falsely retried: `NO_GO_W1` | W0 design exists; real compatible writer absent |
| **P1 epoch producer** | Observe/admit exactly a proven W1 published as-of Seal (or independently qualified S2 cut), manifest bytes, bounded event prefix, immutable exact old bytes/absence policy and source version | Sequential DB/WAL/JSON copy, file digest matches without time binding, unverified checkpoint, stale mislabeled current: `NO_GO_P1` | No real epoch producer exists |
| **P2 issuer/verifier** | Independent issuer registry/approved source-to-key policy and canonical signed claim binding source, epoch, Seal, exact leaves and package; rotation/revocation/replay policy and no client-accessible private key | Self-signed packet, attacker-writable key, unknown/revoked issuer, signature mistaken for source truth: `NO_GO_P2` | No approved real signer/registry/key identity selected |
| **P3 custodian** | Separate protected receipt/store/monotonic anti-replay authority, uniquely no-clobber publication after durable byte and directory barriers, fresh-reader post-restart reconciliation | Same-UID mutable package, replay/rollback, orphan adopted without authorization, ambiguous ACK blindly retried: `NO_GO_P3` | P3i–P3n are synthetic only; deployment NO-GO |
| **P4 exporter** | Read and verify only already authenticated and protected detached as-of packages, issue redacted deterministic bounded incomplete diagnostics pending separate product acceptance | Source WAL opened by exporter, private raw content exposed, unproven remote Task result called verified, CLI created without review: `NO_GO_P4` | R1/live reader/Collector/CLI still blocked |

**TCB limitation:** A trusted guest administrator/root or issuer compromise is not defeated by an assertion signed by that same actor. Define who holds privileged start, source write, issuance and custody powers independently before claiming any source attestation. Privilege separation is *not* proven by distinct usernames alone.

## 4. Architectural alternatives — do not silently select a shortcut

| Route | P0/P1 potential | Decision for this review |
| --- | --- | --- |
| **S3: cooperative W1 trusted writer + as-of Seal + separate custody** | Native application Verification boundary can bind durable artifact digests, Run status, event prefix and Seal atomically, if ALL writer paths are externally controlled and exact referenced bytes remain available. Separate nonmutating WAL read remains mandatory. | **Preferred investigation** because ADR-040 selected Path A; not approved for implementation or use. |
| **S2: independently controlled atomic FS snapshot plus app boundary** | A genuine single instant of DB/WAL/JSON can be captured, but may be intermediate state; requires a separately evidenced committed application boundary, same mount scope and no source mutation. | Conditional fallback, no platform or privileges qualified. |
| **S1: operator-stopped legacy v2 and sequential copy** | Could be adequate only after a separate independently proven *continuous* closed-world embargo and DB/JSON logical epoch proof, currently absent. | **Not sufficient** at current baseline. |
| **S4: SQLite backup + external JSON + local hash/signature** | DB transaction alone cannot bind separately replaced JSON; signature authenticates issuer, not epoch. | **Reject as standalone P1 proof**. |
| **C: fail-closed** | Refuse unsupported provenance or reader path; makes no positive evidence claim. | **Mandatory current operational result** until all separate gates prove adequate. |

## 5. Falsifiable witness plan for a later, separately authorized experiment

1. **External P0 start/FD boundary:** enumerate each legacy v2 entrypoint, inherited writable descriptor, alias/mount, actor/group and policy; independently challenge launches/opens both before and after embargo while the gate remains held. A single surviving bypass refuses. An operator checkbox or PID sample is not a continuous witness.
2. **Reproducible W1 publication timeline:** in disposable only, record fixed-leaf `openat`/no-follow, exact byte digests, file fsync, parent-directory fsync, conditional fenced SQLite transaction with `verification.passed` + `run.transition` + canonical private Seal, and commit-unknown reconciliation. Verify no claimed success before durable commit. Status/event/Seal must be one transaction.
3. **Exact as-of and freshness:** explicitly separate a retained historical `as_of N` (can be valid when latest is N+1) from an unsupported `current` claim. If historical fixed-path bytes were overwritten without trusted retention, classify as **unavailable**, never substitute N+1 bytes.
4. **Reader access:** independently prove no source authority DB/WAL/SHM content or forbidden metadata writes under active WAL/SHM, cold open and checkpoint interference. Include atime policy and transient write observation. In the absence of a proof, R0b C remains.
5. **External P2 issuer challenge:** replace issuer key ID, revoke key, re-sign a mixed-epoch candidate with a valid but unauthorized key, forge a test oracle, replay a fully consistent old package and duplicate a sequence. A valid signature must still fail P1 if the source epoch is not independently evidenced.
6. **Custody/nonclobber and reboot:** retain separately protected receipt/object identities, compare cold-reader state after normal reboot, classify orphan/ambiguous ACK without repair; never promote old P3 synthetic results to these future real-source cases.

## 6. Required owner decisions before any executable P0/P1 follow-up

- **D1: supported topology/TCB.** Which isolated environment and static source/writer/controller identities can be independently administered? Does any actor with old-code authority still obtain a new writer credential or source FD? Unknown => `NO_GO_TOPOLOGY`.
- **D2: actual W1 source publisher vs fallback.** Is the first approved experiment a *new disposable, inert W1 transaction fixture* only, or a later live writer migration? No code or migration approved by this document. The initial production writer remains v2.
- **D3: source proof/retention.** Where will the exact original Verification/Evidence bytes and a Seal event boundary be durably retained and which version/sequence anchor is independent of mutable named leaves? Unknown => historical proof unavailable.
- **D4: issuer and custody trust split.** Who provisions a non-client-owned key/transport identity and monotonic replay anchor? Operator-supplied fields are not authentication.
- **D5: independent audit and recovery.** Who observes start/FD exclusion and disk transaction boundaries, and can independently reconcile crash, checkpoint, root restart, filesystem metadata, snapshot rollback and partial handoff? No such observer is currently attested.

Until decisions are explicit and separately evidenced: **P0_P1_P2_P3_P4_NO_GO**, `R0B_C_FAIL_CLOSED`, `P3_NO_GO_DEPLOYMENT_UNVERIFIED`, no real project data, root command, systemd/AppArmor policy, key provision, writer migration, WAL Reader or public export.

## 7. One-next-slice rule

A future authorization, if granted, should target **one** falsifiable missing link at a time. The smallest defensible next *executable* slice would be an **ordinary-user disposable W1 commit-boundary timing/fault fixture**, not a real ProjectCTL source writer, with explicit negative controls for separate transactions, overwritten evidence bytes, ambiguous commit and stale same-run tokens. It still would not prove P0 root start exclusion or R1 WAL nonmutation. A privileged Debian KVM trial requires new independent scope and explicit owner consent.
