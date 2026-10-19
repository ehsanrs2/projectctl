# M6.0 B-Diagnostic — Snapshot Producer and Trusted Custody design gate

**Status: PROPOSED SECURITY DESIGN FOR HUMAN REVIEW; NOT IMPLEMENTED AND NOT AUTHORIZED.**
**Pinned baseline:** merged PR #100 at main 608da94f250f1354ffa3c8f47a6282160e6b4577 (2026-10-19).
**Governance:** ADR-039 Accepted (read-only, locally derived, non-authoritative Trace); ADR-040 Accepted Path A **as a design** (writer-published Verification as-of Seal); R0b currently chooses C, fail closed for active source WAL. This proposal changes none of them. The active M6.0 project goal remains unchanged.

References: [detached input evidence and limitations](M6_0_BDIAG_DETACHED_INPUT_GATE.md), [R0b current WAL refusal](M6_0_R0B_CURRENT_WAL_FAIL_CLOSED_DECISION.md), [M6.0 implementation scorecard](M6_0_REBASELINE_2026_10_19.md), and [security review matrix](M6_0_BDIAG_PRODUCER_CUSTODY_SECURITY_MATRIX.md).

## 1. Decision in brief

**Propose only a staged direction, not a production implementation:**

- **Immediate:** preserve PR #100's fixed synthetic detached fixture as LAB_ONLY, with self-asserted inventory SHA-256 and literal source_origin=UNATTESTED, cross_store_epoch=UNATTESTED, external_producer_signature=ABSENT. No promotion to a trusted snapshot, Collector or CLI.
- **Preferred long-term source-of-epoch:** reuse the owner-accepted **ADR-040 Path A**, limited to one successful non-review VERIFYING -> READY_TO_INTEGRATE Verification transition. A future reviewed trusted writer must first durably publish the fixed Verification/Evidence bytes, then atomically commit the Run transition, relevant events and immutable as-of Seal. This is an unimplemented dependency (W/M gate), not a producer available today.
- **Independently protected detached custody:** consider an entirely separate, narrowly scoped trusted custody authority that receives only explicitly allowed committed data and can refuse replacement of published package identities by untrusted readers/old writers. A signature/certificate or ownership scheme alone does not make a broken source epoch true. No such authority is currently provisioned or certified.
- **Fail-closed alternative:** if W1 source-epoch authority, custody or R1 nonmutating read cannot be proved, do not emit a trusted historical trace. An independently authorized diagnostic-only offline-input design could still emit incomplete, assessment-free observations, never verified state; there is no approval for that CLI here.

**Principal finding:** a trusted producer AND a custody/verification trust anchor are needed; neither is supplied by PR #100. A cryptographically authenticated hash of sequentially copied DB and JSON bytes is still a potentially inconsistent snapshot. No currently demonstrated option satisfies all production gates.

## 2. Trust boundaries and actors

| Actor | Permitted role in a future proposal | Must NOT be assumed trusted |
| --- | --- | --- |
| Existing v2 writer / old binaries | Existing project authority only; may hold SQLite/WAL, writable JSON descriptors and alias paths | Advisory locks introduced in v3, PID process lists, masks on one service, or a new snapshot protocol that old code does not obey |
| Future trusted W1 writer (not present) | Conditional generation+token lease and run mutex participant; publication of exactly one approved as-of Verification epoch | Any caller-supplied owner string, same-UID imported Python code, or an unfenced old writer |
| Snapshot capture producer (not present) | Obtain a *proved coherent* source epoch, bounded bytes and capture witness under a separately accepted topology | Plain SQLite backup, sequential WAL/JSON copy, SELECT-only connection, self-described quiescence |
| Custody authority (not present) | Authenticate producer and the exact data manifest; create a durable immutable/versioned content identity inaccessible for replacement by untrusted actors | chmod 0400, a same-UID JSON checksum, a signature by a key accessible to the same untrusted writer/reader |
| Diagnostic Reader / future Exporter | Verify independently vouched bytes and metadata; emit deterministic allowlisted redacted incomplete evidence only | Raw source project paths, key material, Writer/Task permissions, unsupported live WAL connections |
| Owner / guest root | Explicit governance and future privileged trial approval, with enumerated actions and rollback | This document does not grant or reuse any past root authorization |

**Threat scope:** accidental crashes, partial publication, deliberate same-UID changes and resigned manifests, old v2 writers, writable inherited FDs, path aliases/mounts, replay/stale bundles, untrusted metadata and malformed input. A compromised trusted host root or compromised signing key cannot be defeated solely by a signature from that same authority. State the residual trusted-computing-base assumption explicitly in any later rollout.

## 3. Required proof chain, in order

### Gate P0 — admission and source identity (not implemented)

Record the *authoritative* project/run/task identity and original DB version without mutating the project. Admit only a separately approved offline topology with **externally enforced** quiescence (including old writers and already-open writable descriptors), or an accepted cooperative W1 as-of publication boundary. Never treat a clean process list, an application-level lock or the existence of a WAL/SHM sample as proof of this gate.

**Refuse** if any live writer, ancestor alias, inherited FD, untrusted startup route or source-id mismatch is not accounted for. Root-owned service policy, namespace or VM snapshot may be considered in a later explicitly privileged, disposable-environment proposal; none is authorized now.

### Gate P1 — same-epoch capture (not implemented)

Define a finite allowlist of DB/sidecars and JSON versioned artifacts, exact source versions and hashes. For ADR-040's initial Verification case, source bytes must have been durably published under a fenced same-run writer and bound to the transition/event/Seal in **one SQLite commit**. The capture must use an approved read or atomic/writer-cooperative snapshot mechanism that can obtain that epoch without modifying the authoritative DB/WAL/SHM; R0b presently blocks active-WAL direct reading.

**A consistent SQLite backup is database-only.** A filesystem-consistent instant of concurrently written SQLite and JSON may be an intermediate workflow state, not an accepted Verification epoch. After publication, a later JSON replacement makes older Seal bytes unavailable unless the exact old version is retained and separately verified. Do not infer as-of identity from two stable hashes or a valid-shaped SHA string.

### Gate P2 — independently verifiable producer assertion (not implemented)

A proposed versioned receipt must bind, at minimum, domain separator/protocol version, source project/run/task/version identities, approved as-of Run transition and event reference, source Seal identifier/sequence, exact sorted allowlisted relative paths, byte lengths and digests, source snapshot method, and custody package identity. It must also bind a unique issuance ID and replay/retention policy. Unknown/missing fields and unknown versions fail closed.

Require **independent** authentication (reviewed public-key trust anchor and signature verification, or a comparably documented root/custodian authenticated transport). The verifier must NOT trust a self-signed receipt or a key shipped writable inside the package; key ID alone proves nothing. Key registration, rotation, revocation, issuance authorization, retention and clock/sequence/replay validity need a separate accepted design.

**Signature validates who asserted the data and whether receipt bytes changed. It does NOT prove that the issuer captured a coherent source epoch.** P0 and P1 are logically independent, mandatory evidence.

### Gate P3 — custody handoff and publication (not implemented)

A trusted custodian must accept only P0/P1/P2-qualified input, validate fixed types and exact inode/content identities, stage in a fresh private destination, fsync data and directories, publish by a versioned no-clobber commit, and retain an independently verifiable immutable identity and unambiguous failure/recovery state. The custodian's protection must prevent unauthorized reader/legacy-writer *replacement*, not just deny writes through a particular CLI. No generic glob cleanup or in-place overwriting of an accepted package.

Test interruption before and after each file fsync, directory publication, receipt verification, final pointer publication, return-to-caller and retirement. On ambiguous outcomes: quarantine + independent reconciliation, never auto-certify success. A final directory deletion following the last journal removal is **not solved** by adding another journal layer (M0x lesson).

Protection could be a separately enforced storage ACL/credential boundary, independently owned immutable/versioned store, read-only mount snapshot or another specifically reviewed OS/filesystem mechanism. Current same-UID chmod 0400, hashing and locally stored receipt remain insufficient. Any root/kernel policy or VM snapshot exercise requires fresh operator approval.

### Gate P4 — detached consumer / diagnostic export (not implemented)

Only after independently authorized P0–P3, a future consumer may validate producer authority/receipt, source identities/epoch, path and size allowlist, exact bytes and revision, key revocation/replay state and custody immutability. It must treat unknown or stale input as unavailable/inconsistent, avoid all direct live-source access and never repair DB, seal or Writer state.

The **first bounded diagnostic output** still has completeness=incomplete|inconsistent, assessments=[], no raw prompt/event payload, no absolute project paths, no independently supported delivery and no new Task/Worker privileges. Any public Collector/CLI or output-to-file mode requires a **separate ADR-039 safety/privacy and destination acceptance**. A complete trusted R1 as-of export additionally needs the actual W1 writer Seal and a separately proven source-nonmutating Reader route; no stage here grants either.

## 4. Architecture options and proposed selection

| Candidate | Source-epoch basis | Custody/provenance basis | Blocking problem / recommendation |
| --- | --- | --- | --- |
| S0: current self-hashed detached fixture (#100) | None: sample DB and JSON may be mixed | Same-UID inventory, no independent issuer | **LAB_ONLY; reject for real project admission** |
| S1: operator-stopped old v2 project + sequential private copy | Claimed quiescence, unsupported while uncooperative writers/FD aliases survive | Might later have independent custodian | **NO_GO** until externally enforced all-writer embargo, durable backup and post-cutover proof; inherits M0 blockers |
| S2: one filesystem-wide atomic point-in-time snapshot | Filesystem point; NOT automatically successful Verification boundary | Trusted snapshot authority + protected medium, yet to be scoped | Candidate only after proving storage topology, SQLite/WAL consistency, identity and application epoch; privileged work separately authorized |
| S3: trusted W1 as-of Seal + separately protected detached capture | **Preferred architecture Path A**, once actual fenced durable Verification transaction is proved | Independent authorised producer/recipient and immutable versioned content address | Best alignment with accepted ADR-040; **not implementable for production at current baseline** |
| S4: SQLite backup plus detached JSON and locally signed checksum | Consistent DB only, unbound external JSON | Signature authenticates issuer, not epoch | **Reject as sufficient proof** |

**Proposed scope choice:** pursue **S3 as a design dependency**, while explicitly declining to implement S1/S2/S3 under this PR. S2 can remain a separately reviewed fallback for environments that have a demonstrably coherent and protected storage snapshot. Do not change R0b's C or start operational M0/W1 solely because this design is merged.

## 5. Hard failures and correct user-facing semantics

- **Missing/unsupported source, stale epoch, manifest mismatch, unverifiable issuer or custody:** return typed refusal/unavailable; no raw filenames, project secrets or signing keys in output.
- **Partial valid capture / crash during publication:** never expose an apparently successful receipt; keep quarantine and evidence. Do not automatically restore source DB/JSON.
- **Valid package hash but no independently trusted source admission:** source_origin_proven=false and cross_store_epoch_proven=false even if bytes are internally consistent.
- **W1 source Seal historically overwritten:** the exact referenced old bytes must still be independently available and verified; otherwise historical read is unavailable, not reconstructed from newer filenames.
- **Source VFS read can alter DB/WAL/SHM or evidence freshness unknown:** R0b option C (fail closed). A snapshot producer must not quietly use the unapproved R0 direct WAL test reader.
- **External provider/task state not included in trusted local epoch:** never infer independent remote delivery or successful verification from the existence of a signed snapshot.

## 6. Decisions reserved for a later, separate owner review

Before beginning executable Producer/Custodian work, the owner must explicitly choose and approve:

1. The supported *deployment topology* and whether a truly independent trusted custody principal and key storage are available.
2. Which method *actually* produces one as-of DB+JSON epoch (future S3 writer cooperation or demonstrated coherent storage S2), and the full source artifact allowlist.
3. Whether the first deliverable is only detached **diagnostic** content or a historical Seal-backed claim; changing public Trace proof metadata needs a separate versioned contract decision.
4. Who controls keys, protected storage, rollback/reboot reconciliation, retention/deletion, and privacy of the raw stored artifacts.
5. Which independent adversarial and actual platform tests must pass before any privileged pilot; no previous M0s root permission carries forward.

**Exit from this document stage:** owner-reviewed explicit P0–P4 gates, no production path wired, and exact-head CI on this documentation-only PR. Signing the document does not produce a source-attested snapshot or close any of F-01–F-06/F-09.

## 7. No-go / operational ceiling

The following remain **NO_GO**: live/source WAL R1, validated producer/custodian, production DB v2→v3 M0 migration, trusted W1 Verification Seal, public Trace Collector/CLI, root/systemd/AppArmor policy deployment, changes to Task/Worker permissions, and treating detached bytes as historical evidence. Existing test-only PR #100 can continue to return only NO_GO_DETACHED_FIXTURE_BYTES_ONLY.

This is design and security review **only**. No shell scripts, executable examples, test source access, actual guest modifications, migrations or policy files are supplied by this PR.

## 8. External reference boundaries (background, not acceptance evidence)

- [SQLite WAL documentation](https://www.sqlite.org/wal.html): read-only WAL may be opened under documented WAL/SHM, directory-write or immutable conditions; the ability to read **does not** satisfy ProjectCTL's independently proven nonmutation and external JSON epoch requirements.
- [SQLite WAL-index and sidecar lifecycle](https://www.sqlite.org/walformat.html): SHM is a mapped coordination index with lifecycle effects; a disk copy of DB or WAL bytes alone is not an application-level epoch certificate.
- [Linux chmod](https://man7.org/linux/man-pages/man1/chmod.1.html): file mode bits are permission state, not proof of independent immutable custody against the file owner.

These references support threat-model assumptions but provide **no evidence** that a source ProjectCTL database, proposed snapshot producer or custodian currently meets P0–P4.
