# M6.0 B-Diagnostic P2c — Synthetic Prepare/Commit/Acknowledge/Restart Fault Model

**Status:** LAB_ONLY; pure in-memory crash-boundary simulation, not a durability or recovery implementation.
**Pinned baseline:** merged PR #104, main 689b5172e2b90df357c2239187e49bb25b22da7f (2026-10-20).
**Governing decisions:** accepted ADR-039 (read-only, local, non-authoritative derived Trace), accepted ADR-040 Path A as an unimplemented bounded future writer as-of Verification Seal, R0b active-source WAL option C (fail closed), and the [P0–P4 Snapshot Producer and Trusted Custody review](M6_0_BDIAG_SNAPSHOT_PRODUCER_TRUSTED_CUSTODY_DESIGN.md).

## 1. Why this lab exists

Synthetic P2b PR #104 demonstrated that a caller can recalculate both a synthetic replay-state checksum and checkpoint, so neither issuer authentication nor durable anti-replay is proven. Before considering an actual protected custodian or state store, we need a reproducible **fault-state table** covering the boundary between a computed candidate, a hypothetical atomic commit, an acknowledgement and an independently recovered record.

This stage adds only:

- scripts/bdiag_p2c_fault_state_lab.py — a pure stdlib/P2b import-only hypothetical state machine, never wired into projectctl;
- tests/test_m60bdiag_p2c_fault_recovery_model.py — in-memory fault cutpoints and red/negative safety witnesses;
- this architecture and acceptance document.

There is no actual processor termination, SQLite connection, fsync, system clock, filesystem crash, background worker, network, signer, trusted issuer registry, encrypted/secret credential, source DB, live project artifact, durable replay log, CLI or process authority. All callers create entirely synthetic Python objects and pass them into functions.

**Decision is always NO_GO_P2C_FAULT_STATE_MODEL_ONLY.** No result proves issuer identity, source epoch, independently protected checkpoint, durable replay exclusion, commit permanence, delivery of an ACK, authorized Writer Seal, source WAL Reader, Collector/CLI or migration. Diagnostic Trace remains incomplete/inconsistent, assessments empty, and no actual Trace is emitted by this lab.

## 2. Four pure operations and the imaginary cell

| Operation | Input/return | Only modeled property | Not actually done |
| --- | --- | --- | --- |
| **Prepare** | P2 canonical synthetic receipt, test caller's expected identities, previously supplied cell -> LabIntent | P2b issuer-claim comparison and candidate next replay checkpoint | No slot mutation, lock, disk write, signature verification or reservation |
| **Commit** | Old LabSlot + prepared intent -> **new immutable LabSlot** | A Python equality compare-and-swap *predicate* against exact earlier checkpoint/anchor; next checkpoint and last-commit record appear together in one returned object | No multi-process CAS, atomic rename, durable transaction, fsync, WAL safety or authorization |
| **Acknowledge** | Matching returned new slot + intent -> LabAck | Reject ack before a matching hypothetical commit or for the wrong receipt | No packet sent, acknowledgement delivered, remote success or deduplication of response transport |
| **Restart** | A *caller-supplied* optional LabSlot, LabIntent, optional claimed-delivered LabAck -> LabRecovery | Classify supplied combinations into explicit ambiguous/missing/claimed states | No privileged independently trusted disk read, crash detection, custody verification or rollback protection |

LabSlot stores a synthetic P2b issuer policy, replay checkpoint and checksum anchor and, after a hypothetical Commit, a matching last-commit record. A deterministic SHA-256 commit ID binds selected test fields. **This hash is not a signature.** A caller can recreate the entire cell (including policy, data, checksum and commit record); equal-looking Python values do not imply an authenticated or durable write.

There are no in-place writes: Prepare, Commit and Acknowledge return objects. Their exact behavior is not a production commit protocol; the imaginary cell is useful only for falsifying an unsafe acknowledgement or retry assumption.

## 3. Recovery classes and strict NO-GO output

| Restart view | Model class | Interpretation only; NEVER permission |
| --- | --- | --- |
| No independently recoverable cell supplied | UNAVAILABLE_REFUSE | No automatic zero-state bootstrap or retry |
| Cell supplied but original intent missing | MISSING_INTENT_REFUSE | Cannot independently correlate issuance with this caller |
| Old precommit cell and original intent | PRECOMMIT_IN_SUPPLIED_MODEL | Only that the *untrusted supplied* cell looks old; not proof no external commit happened |
| New cell matching intent, no ACK confirmation | COMMIT_VISIBLE_ACK_UNKNOWN | Hypothetical commit is represented; ACK may have been lost, and no durable proof exists |
| Matching new cell and *caller-claimed* ACK object | COMMIT_VISIBLE_ACK_CLAIMED | Even this is not authenticated ACK delivery or source truth |
| Old cell plus *caller-claimed* ACK | ACK_WITHOUT_COMMIT_QUARANTINE | Suspicious contradiction; do not accept success or reissue automatically |
| New cell plus different ACK | ACK_MISMATCH_QUARANTINE | Disagreeing evidence; quarantine |
| Any unrelated, stale or contradictory state/commit ID | AMBIGUOUS_QUARANTINE | Require separately authorized reconciliation |

Every one of these returns decision NO_GO_P2C_FAULT_STATE_MODEL_ONLY. All other booleans, especially safe_to_retry_without_external_reconciliation, issuer_authenticated, commit_durable_proven, acknowledgement_delivered_proven, independent_anchor_proven, durable_replay_prevention_proven, source_origin_proven and cross_store_epoch_proven, are required to be literal false.

A caller's claimed receipt was delivered is NOT proof of delivery. A successful case is strictly a **model observation of supplied values**, not an operational admission or an instruction to retry.

## 4. Required fault/attack witnesses

**F-C01:** Crash immediately before Prepare: original intent missing -> refuse.
**F-C02:** Crash after Prepare, before Commit: old cell -> PRECOMMIT_IN_SUPPLIED_MODEL only.
**F-C03:** Crash after Commit, before ACK: new cell -> COMMIT_VISIBLE_ACK_UNKNOWN, no new admission.
**F-C04:** ACK constructed, but lost by caller/transport: same as F-C03; never assume "not acknowledged" means "not committed."
**F-C05:** Caller reports matching ACK after Commit: matching claim observed, not proven delivered.
**F-C06:** ACK appears without matching committed cell: quarantine.
**F-C07:** Commit from two intents prepared against one old cell: second fails the **in-memory** CAS if the first new cell is supplied; **counterexample:** the same old value can separately produce two divergent new objects. No interprocess exclusion is provided.
**F-C08:** Same receipt repeated against the postcommit cell: P2b model refuses as a replay only while the newer state is supplied.
**F-C09:** Crash/loss of cell or intent: refuses, never silently reconstructs empty checkpoint.
**F-C10:** A malicious caller replaces/rolls back the entire old cell and its checksum after an apparent Commit: prior receipt becomes syntactically admissible again. A separate caller-claimed earlier ACK reveals a contradiction, but there is **no trusted witness** in this model. This is the key negative control.
**F-C11:** Forged last commit ID or inconsistent checkpoint: refused/quarantined; a well-formed forged whole cell can still claim an arbitrary "commit" without independently authenticating it.
**F-C12:** Wrong receipt/package/Seal claim, malformed P2 schema, stale sequence, mismatched issuer policy or stale intent: refusal via P2/P2b or P2c structural checks.

Tests cover in-memory state transitions and deliberate fault injection with no real SIGKILL, reboot, data mutation, root execution or trusted metadata.

## 5. Production proofs still missing

Before an operator may even consider implementing a real producer/custodian:

- **P0:** prove authentic project/run admission and writer/FD exclusion, or approved cooperative W1 production boundary; no old-v2 writer bypasses.
- **P1:** independently establish a coherent cross-store Verification as-of epoch, exact retained DB/event/Verification/Evidence bytes and safe source nonmutation; R0b C continues to reject active WAL until proved otherwise.
- **P2 issuer:** select and approve actual signing and independently anchored key/issuer policy, signature domain/version/revocation and authorization rules.
- **P2 replay/P3 custody:** choose a truly independent owner of the monotonic receipt state and custody object; define the single durable linearization point and no-clobber publication semantics, protection from same-UID modifications, rollback-resistant identity, fsync/abort/readback, interruption windows and precise acknowledgement/restart reconciliation on the target OS/filesystem. This document does NOT grant a root/systemd/AppArmor trial.
- **P4:** separately authorize a reader/exporter with independently proven origin/epoch/privacy/source nonmutation and output destination rules; no public CLI or historical verified assessment follows from an in-memory model.

**Design stop condition:** If the source epoch, independent durable store or authenticated ACK evidence is missing, do not infer "not committed" from an empty old checkpoint, and do not automatically issue the same receipt again. A self-computed checksum and a status enum never establish those facts.

## 6. Ordinary-user focused validation after owner review and merge

No OS permissions, live SQLite DB, keys, services or real ProjectCTL user project are involved:

    cd "$HOME/projectctl-m0k-lab"
    git fetch origin
    git status --short
    git switch --detach origin/main
    source .venv/bin/activate
    python -m pytest -q -rs tests/test_m60bdiag_p2c_fault_recovery_model.py
    git diff --check 689b5172e2b90df357c2239187e49bb25b22da7f..origin/main

The CI must pass on the **exact** PR HEAD; passing tests are evidence of this **lab model alone**, not authority to install policies, create signer keys, provision a custodian, modify writer DB schemas or read live source WAL.

**Disposition:** P2c crash/recovery failure semantics LAB_ONLY. Operational P0–P4, v3 migration, W1 trusted Seal, R1 Reader, real protected Custodian and Collector/public CLI remain NO_GO.
