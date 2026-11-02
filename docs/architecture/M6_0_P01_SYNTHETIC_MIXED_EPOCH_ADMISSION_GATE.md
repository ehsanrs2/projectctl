# M6.0 P01 — Synthetic P0/P1 source admission and mixed-epoch refusal gate

**Status: LAB ONLY / no operational authorization.** The independent witness is an in-memory test oracle, not an actual authenticated source, trusted writer, Seal, or verified epoch.

**Dependencies:** ADR-039 (read-only, local, non-authoritative trace), ADR-040 Path A (accepted *design*, bounded as-of Verification only), R0b route C (current active-WAL ProjectCTL reader must fail closed), and issue #120.

## Hypothesis and negative witness

A self-consistent package may combine SQLite's epoch N with an external JSON artifact from N+1. Even after a caller recomputes both inventory hashes, there is no proven cross-store source epoch. A wholly old, internally valid package can also be replayed as falsely current. Per ADR-040, age alone does not invalidate an as-of N observation when its exact historical bytes remain available and validate. No synthetic comparison authorizes an operational ProjectCTL export.

The import-only pure model in scripts/p01_synthetic_epoch_admission_model.py compares a proposed Capture to a separately constructed TestOracleWitness. The oracle is **only test scaffolding**, which assumes (but cannot prove) an approved source, excluded old writer starts, drained preopened writable FDs, and a separately observed epoch. Constructing the oracle from caller-supplied data makes any positive result circular and invalid for production. Accordingly, even a successful comparison returns only SYNTHETIC_CONSISTENT_NOT_ATTESTED.

The finite model uses a synthetic project/run/task identity, a source version-2 label, a positive DB epoch, a proposed verification/event boundary with status ready_to_integrate, and only two in-memory synthetic Verification/Evidence leaves with SHA-256 values. **No real v2 RunStore Seal is assumed to exist.** A label such as epoch=N is not a cryptographic or transactional proof.

The fixture alone defines strict UTF-8 JSON objects with exactly `kind` and `epoch` fields. The kind must match the leaf and epoch must be an integer in 1..1,000,000; booleans, floats, duplicate keys (including escaped aliases), nonstandard constants, extra fields and malformed JSON are refused. Both parsed epochs must match all metadata and the historical oracle epoch. This is **not** a parser or schema assumption for real ProjectCTL manifests. Identities use the existing Seal contract's bounded ASCII syntax `[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}`, without normalization; hashes are lowercase SHA-256 and event boundaries are positive signed-64-bit integers.

`Capture.observation_claim` defaults to `as_of`: the capture's DB epoch identifies its historical target, matched against `oracle.epoch`. A `current` claim additionally requires a separately supplied hypothetical `oracle.latest_epoch` equal to that target. A newer latest epoch does not invalidate an `as_of` capture, but does refuse its `current` claim. Missing latest observation never establishes currentness, and malformed or backwards latest observations are refused for either claim. Even an accepted current comparison remains model-only and unattested.

## Falsification matrix

| Scenario | Expected result |
| --- | --- |
| Missing oracle, even with caller_claims_epoch_proven=True | REFUSE_P0_WITNESS_ABSENT |
| Assumed source admission / old binary embargo / open FD exclusion / epoch witness missing | REFUSE_P0_ADMISSION_UNPROVEN |
| Cross-project/run/task, invalid identity or incompatible source version | REFUSE_P0_IDENTITY_OR_SCHEMA |
| Inventory hash inconsistent with raw bytes; malformed synthetic JSON or digest | REFUSE_P1_INTERNAL_INTEGRITY |
| DB N + JSON N+1 with recomputed local and oracle hashes; metadata/files/target epoch disagree | REFUSE_P1_MIXED_EPOCH |
| False current claim for historical N; absent latest observation; malformed claim/latest observation | REFUSE_P1_CURRENT_UNPROVEN |
| Wrong verification status or event-prefix boundary | REFUSE_P1_STATUS_OR_EVENT_BOUNDARY |
| Modified raw bytes and recomputed local hash but no independent digest match | REFUSE_P1_UNWITNESSED_BYTES |
| Fully consistent model + hypothetical separate oracle | SYNTHETIC_CONSISTENT_NOT_ATTESTED |
| Historical as-of N with exact retained bytes, even when latest is N+1 | SYNTHETIC_CONSISTENT_NOT_ATTESTED |
| Tampered capture + forged matching oracle (deliberately circular negative control) | SYNTHETIC_CONSISTENT_NOT_ATTESTED, never operational trust |

## Validation and limitations

Ordinary unprivileged development checkout:

```sh
python -m pytest -q -rs tests/test_m60p01_synthetic_epoch_admission_model.py
```

The original focused model and test pair passed 26/26 cases before publishing. The hardened focused suite has 227 cases; local execution and hosted CI are separate evidence. The reference oracle fixture is authored separately from the capture builder; a deliberate forged-oracle test documents why even matching references cannot prove source independence. The test covers no filesystem path, no SQLite or WAL source reader, no network endpoint, no privilege. The no-I/O guard monkeypatches Path.open/sqlite3.connect in the model call. Filesystem/DB labels are **test data** and cannot by themselves certify an independently administered source.

**Nonclaims:** No actual P0 credential/start/FD exclusion, no P1 cross-store transaction witness, no writer-managed retention or fsync barrier, no trusted as-of Seal, no P2 signature or policy, no P3 anti-rollback, no R1 active-WAL read, no user-facing Collector/CLI or exported verified assessment, no actual ProjectCTL data and no VM/root action. Do not relax the existing R0b C refusal. P0–P4 remain NO_GO.

Any operational follow-up must be a separate scoped review proving where the independent source witness comes from, how exact durable bytes and event boundary are published and retained, and how an approved read can observe them without source modification.
