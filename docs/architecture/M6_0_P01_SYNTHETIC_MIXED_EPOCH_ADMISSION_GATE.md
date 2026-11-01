# M6.0 P01 — Synthetic P0/P1 source admission and mixed-epoch refusal gate

**Status: LAB ONLY / no operational authorization.** The independent witness is an in-memory test oracle, not an actual authenticated source, trusted writer, Seal, or verified epoch.

**Dependencies:** ADR-039 (read-only, local, non-authoritative trace), ADR-040 Path A (accepted *design*, bounded as-of Verification only), R0b route C (current active-WAL ProjectCTL reader must fail closed), and issue #120.

## Hypothesis and negative witness

A self-consistent package may combine SQLite's epoch N with an external JSON artifact from N+1. Even after a caller recomputes both inventory hashes, there is no proven cross-store source epoch. A wholly old, internally valid package can also be replayed. Neither case authorizes an as-of ProjectCTL export.

The import-only pure model in scripts/p01_synthetic_epoch_admission_model.py compares a proposed Capture to a separately constructed TestOracleWitness. The oracle is **only test scaffolding**, which assumes (but cannot prove) an approved source, excluded old writer starts, drained preopened writable FDs, and a separately observed epoch. Constructing the oracle from caller-supplied data makes any positive result circular and invalid for production. Accordingly, even a successful comparison returns only SYNTHETIC_CONSISTENT_NOT_ATTESTED.

The finite model uses a synthetic project/run/task identity, a source version-2 label, a positive DB epoch, a proposed verification/event boundary with status ready_to_integrate, and only two in-memory synthetic Verification/Evidence leaves with SHA-256 values. **No real v2 RunStore Seal is assumed to exist.** A label such as epoch=N is not a cryptographic or transactional proof.

## Falsification matrix

| Scenario | Expected result |
| --- | --- |
| Missing oracle, even with caller_claims_epoch_proven=True | REFUSE_P0_WITNESS_ABSENT |
| Assumed source admission / old binary embargo / open FD exclusion / epoch witness missing | REFUSE_P0_ADMISSION_UNPROVEN |
| Cross-project/run/task or incompatible source version | REFUSE_P0_IDENTITY_OR_SCHEMA |
| Inventory hash inconsistent with raw bytes | REFUSE_P1_INTERNAL_INTEGRITY |
| DB N + JSON N+1 with recomputed local hash; two files disagree; stale whole package | REFUSE_P1_MIXED_OR_STALE_EPOCH |
| Wrong verification status or event-prefix boundary | REFUSE_P1_STATUS_OR_EVENT_BOUNDARY |
| Modified raw bytes and recomputed local hash but no independent digest match | REFUSE_P1_UNWITNESSED_BYTES |
| Fully consistent model + hypothetical separate oracle | SYNTHETIC_CONSISTENT_NOT_ATTESTED |

## Validation and limitations

Ordinary unprivileged development checkout, exact PR HEAD:

```sh
python -m pytest -q -rs tests/test_m60p01_synthetic_epoch_admission_model.py
```

The focused model and test pair passed 26/26 cases in an isolated local Python execution before publishing; exact-head repository CI and operator checkout tests are separate evidence. The test covers no filesystem path, no SQLite or WAL source reader, no network endpoint, no privilege. The no-I/O guard monkeypatches Path.open/sqlite3.connect in the model call. Filesystem/DB labels are **test data** and cannot by themselves certify an independently administered source.

**Nonclaims:** No actual P0 credential/start/FD exclusion, no P1 cross-store transaction witness, no writer-managed retention or fsync barrier, no trusted as-of Seal, no P2 signature or policy, no P3 anti-rollback, no R1 active-WAL read, no user-facing Collector/CLI or exported verified assessment, no actual ProjectCTL data and no VM/root action. Do not relax the existing R0b C refusal. P0–P4 remain NO_GO.

Any operational follow-up must be a separate scoped review proving where the independent source witness comes from, how exact durable bytes and event boundary are published and retained, and how an approved read can observe them without source modification.
