# M6.0 B-Diagnostic P2b — Synthetic Issuer Policy and Replay State Model

**Status: LAB_ONLY, pure in-memory threat model, not producer authentication or durable replay protection.**
**Baseline:** merged PR #103, main f23923de90f94cfb82e4d5d58c316b57e8f72e93 (2026-10-19).
**Governing:** accepted ADR-039 (non-authoritative local Trace), accepted ADR-040 Path A (unimplemented writer-published Verification as-of Seal), R0b current active WAL failure-closed option C, P0–P4 [Snapshot Producer and Trusted Custody design](M6_0_BDIAG_SNAPSHOT_PRODUCER_TRUSTED_CUSTODY_DESIGN.md), and [P2 synthetic receipt claims](M6_0_BDIAG_P2_SYNTHETIC_RECEIPT_CONTRACT.md).

## 1. Scope and acceptance ceiling

Merged P2 PR #103 established a strict in-memory receipt schema and demonstrated two critical counterexamples: (i) forged receipt plus matching attacker-supplied expected claims still passes **structural** matching; and (ii) a matching receipt can replay after caller-provided seen-history resets. This PR adds only a separate **pure lab model** where the test harness supplies issuer policy and a synthetic replay-state checksum anchor.

**The central difference:** a **declared** issuer/key ID matching a test policy is NOT issuer authentication. A receipt signature, key authority and protected storage do not exist. Similarly, a SHA-256 checksum of a checkpoint is not an independently protected durable checkpoint. Tests explicitly demonstrate that anyone who can roll back/recalculate both checkpoint and checksum can defeat the simulated replay filter.

Only the fixed state label NO_GO_P2B_ISSUER_REPLAY_MODEL_ONLY is permitted. Every success reports issuer_authenticated=false, source_origin_proven=false, cross_store_epoch_proven=false, independent_anchor_proven=false, durable_replay_prevention_proven=false, custody_proven=false; Collector/CLI, live WAL Reader, trusted W1 Seal and M0 migration flags are also always false.

## 2. Two deliberately untrusted model inputs

**Issuer policy:** an immutable, finite LabIssuerPolicy instance with claimed issuer ID, claimed key ID, policy epoch, key generation and revoked boolean. The policy is supplied **directly by the test caller**, not downloaded or authenticated from a trusted registry. The model compares P2 receipt claims against it and refuses unknown issuer/key, revoked policy or changed policy generation. A matching local policy is only a hypothetical allowlist condition, not proof of signature possession, authority to issue or validity at capture time.

**Replay state:** immutable LabReplayCheckpoint with revision, last strictly increasing issuance sequence and sets of synthetic receipt/package IDs, limited to 512 sample entries. LabChecksumAnchor stores SHA-256 fingerprints for that policy and state. The anchor is **also calculated by code available to the caller**, hence not an independent trust anchor. Model transitions return a candidate next state and next checksum. They do NOT save it, fsync, sign, notify a custodian, give an acknowledgement, or install it as a real authority record.

Both the receipt and expected source/project/run/task/Seal values are provided by the test harness. P2's canonical parser and refusal semantics are reused unchanged. No script accesses files, SQLite, network, OS identity/permissions or keys.

## 3. Proposed in-memory progression (NOT a durable commit protocol)

1. A test creates a policy, an empty checkpoint and a matching **locally derived** checksum anchor. This is only a starting hypothesis, not recovery from trusted storage.
2. P2b first refuses an unknown/mismatched checkpoint anchor, revoked policy or policy generation mismatch. It then invokes the existing bounded P2 receipt parser and compares issuer/key claims to the separate test policy.
3. If the in-memory sequence and sample ID sets show no prior receipt, the model returns an entirely nonauthorizing observation and a **candidate** updated checkpoint plus checksum.
4. A test harness can pass that candidate state to a simulated restarted model. Replaying the same receipt is refused and a strictly newer issuance is eligible for another **synthetic candidate**.
5. If the caller loses the state, carries mismatched state/anchor or changes policy without corresponding state reconciliation, admission refuses. **But** rolling back both the state and anchor allows the prior receipt to pass again; this is a required negative counterexample showing the missing independent custody/durable replay witness.

A real publication transaction would have to specify exactly when a receipt is durably committed, when an acknowledgement is safe, how uncertain outcomes are reconciled after a SIGKILL/reboot, and which *independently trusted* store supplies the anti-rollback high-water mark. No such feature is selected or implemented here.

## 4. Future negative evidence matrix (test results never turn into permissions)

| Attack or restart condition | Pure model expectation | Remaining missing evidence |
| --- | --- | --- |
| Ordinary first receipt, fixed test policy | Candidate state returned, NO_GO flags | Producer authorization and signature |
| Same receipt after feeding returned checkpoint into a new call | Refused by in-memory replay history | Durable independent history store |
| Candidate state computed but not used by any external actor | First receipt remains admissible using unchanged earlier state | Atomic commit and acknowledgement boundary |
| Saved checkpoint but old checksum reference, or vice versa | Refused | Trusted checkpoint identity pinning |
| Checkpoint and matching SHA anchor both rolled back | Receipt is admissible again; still NO_GO | Independently protected anti-rollback state |
| Attacker supplies matching forged issuer policy, receipt and checksum | Structural admission may pass but issuer_authenticated remains false | Independent issuer registry and key verification |
| Issuer revocation/key rotation/policy epoch mismatch | Refused until separately reviewed reconciliation | Authenticated policy publication and cutover |
| Duplicate receipt/package ID, nonmonotonic issue sequence | Refused when in-memory checkpoint actually contains prior records | Restart-persistent monotonicity/retention |
| Invalid P2 schema, fake VERIFIED signature or IMMUTABLE custody claim | Strict parser rejects | Actual versioned cryptographic contract |
| Source DB+JSON mixed epoch with perfectly matching receipt | **NOT detected by this model**; source_epoch proof stays false | Independent P0/P1 as-of witness |
| Malformed/over-capacity checkpoint and invalid checksum formats | Refused | Real storage bounds, crash recovery and integrity |
| Claimed receipt matches expected synthetic project/Seal values | Only caller-supplied equality is shown | Authoritative source of identities and Seal |

The tests must preserve at least two **positive structural but negative trust** witnesses: matching attacker-controlled policy/receipt, and rollback of both checkpoint and checksum. Without them, later reviewers could mistake a successful predicate for issuer authentication or replay durability.

## 5. Missing production implementation gates

- **P0:** independent admission of source project/run identity and exclusion of legacy writers/FD bypasses, or separately proven trusted writer cooperation.
- **P1:** actual W1 fenced Verification transition/Event/as-of Seal in one durable SQLite transaction and exact durable corresponding JSON bytes; source WAL remains fail-closed until independently proven nonmutating route.
- **P2:** a cryptographic issuer-verification *design decision* with independently provisioned/trusted keys, algorithm and domain separation, authenticated issuer allowlist/key lifecycle, revocation and authentic expected source identities. Key IDs and local JSON claims alone do not count.
- **P2 anti-replay:** independent durable monotonic high-water/ID registry, binding to real producer and package identity, anti-rollback storage, unambiguous acknowledgement and post-crash reconciliation on the selected deployment topology.
- **P3:** independently protected package and checkpoint custody, atomic no-clobber publication, fsync/crash/reboot evidence, retention/privacy review, protection from untrusted same-UID and privileged startup bypasses.
- **P4:** explicit owner authorization of read-only detached input, full privacy/redaction and destination constraints, no live WAL Reader fallback and diagnostic outputs always incomplete/inconsistent with assessments=[] unless separate end-to-end accepted provenance exists.

A future research-only step may present a **pure fault-state transition table** for prepare/commit/acknowledge/restart against an imaginary independent custodian, but neither this lab nor that table can certify a real filesystem, kernel or key authority.

## 6. Operator acceptance (only after owner reviews and merges PR)

The test suite is wholly in-memory and ordinary-user safe. No source files or system configuration are touched; the only repository changes are this document, one import-only script and one test file.

    cd "$HOME/projectctl-m0k-lab"
    git fetch origin
    git status --short
    git switch --detach origin/main
    source .venv/bin/activate
    python -m pytest -q -rs tests/test_m60bdiag_p2b_issuer_replay_model.py
    git diff --check f23923de90f94cfb82e4d5d58c316b57e8f72e93..origin/main

Do not create a real signing key, snapshot producer, trust registry or database replay table, invoke sudo/root, run an executable on any real ProjectCTL source, convert WAL mode, or install systemd/AppArmor policies. This PR does not authorize any of those actions.

**Disposition:** P2b synthetic issuer/replay **LAB_ONLY**. All real P0–P4 evidence remains UNVERIFIED. M0/v3, W1, R1, trusted Custodian and public Collector/CLI remain NO_GO.
