# M6.0 P02 — Synthetic receipt provenance gap (not a producer)

**Status:** LAB_ONLY / design-and-falsification experiment. This PR does not implement P0/P1/P2 or an authorized source witness. Tracks issue #122; follows merged P01 PR #121 on main@adad585b91c2d54863ea54a6023bda92b8ee16c0.

## Why another test is needed

P01 proves a bounded rule for comparing synthetic source-epoch labels against a **hypothetical independent oracle**. P02 tests the logically preceding question: can a producer-supplied self-hashed receipt be mistaken for that oracle? **No.** A caller can format a valid-looking receipt for arbitrary epochs, digests and issuer IDs, including a mixed-epoch pair of leaves, without any connection to the source ProjectCTL authority. Structural correctness and cryptographic syntax never establish actual P0/P1 or P2.

ADR-040 Path A accepts only an eventual **writer-produced as-of Verification Seal** inside the same authoritative transaction as run transition and event prefix, after durable exact file publication. That operational writer/seal does not exist here. R0b route C still fails closed on active ProjectCTL WAL. The synthetic P3 custody trials do not bridge these source trust boundaries.

## Finite synthetic protocol

The function `inspect_untrusted_receipt(raw)` in `scripts/p02_synthetic_receipt_provenance_lab.py` is a **pure import-only** parser for UTF-8 canonical newline-terminated JSON (max 4096 raw bytes). It admits exactly one synthetic format:

- Fixed domain `projectctl.p02.synthetic_receipt`, protocol version 1, fake source schema version 2.
- Exactly one bounded ASCII `project_id`, `run_id`, `task_id`, and **claimed**, nonauthenticated `issuer_claim_id`.
- Positive synthetic `as_of_epoch`, `event_prefix_id` and `receipt_sequence`; `run_status=ready_to_integrate` for the first ADR-040 Verification scope.
- Two ordered leaves, `verification-manifest.json` and `evidence-manifest.json`, each with bounded claimed raw byte length and lowercase SHA-256-shaped digest. The parser **never reads the underlying leaf bytes**, so these are unverified claims.
- Required literal **nonproofs**: `source_origin=UNATTESTED`, `cross_store_epoch=UNATTESTED`, `issuer_auth=ABSENT`, and `custody_protection=UNVERIFIED`.

The parser rejects duplicate keys including escaped aliases, extra fields, malformed JSON, noncanonical encodings, unsupported versions/status, nonstandard constants, wrong order/path/length/digest syntax, non-ASCII or dangerous IDs, booleans disguised as integers, and any self-declared trust promotion. A valid packet returns only `P02_SYNTHETIC_RECEIPT_STRUCTURAL_ONLY`; it **never** returns a trusted, current, authenticated, source-proven, complete, or operationally admitted status.

## Key negative controls

| Synthetic observation | Parser decision | Scientific conclusion |
| --- | --- | --- |
| Canonical JSON + plausible two-leaf digests and issuer ID | STRUCTURAL_ONLY | Syntax is not independently authenticated source origin |
| Same packet replayed verbatim | STRUCTURAL_ONLY | Stateless parser cannot establish anti-replay; real external monotonic authority remains missing |
| Claimed as-of epoch N changed to N+1 and packet reserialized | STRUCTURAL_ONLY | Synthetic epoch claim itself is not a source witness |
| Verification digest from N and Evidence digest from N+1, both syntactically valid | STRUCTURAL_ONLY | **Mixed epoch can pass structural checks**; therefore no P1 proof is possible from this receipt alone |
| One leaf digest fabricated/recomputed by caller | STRUCTURAL_ONLY | Digest syntax cannot establish retention or custody integrity |
| Extra `signature_verified`, `trusted`, `source_epoch_proven` or signature field | REFUSE_INVALID_RECEIPT_FIELDS | No authority may be smuggled into schema |
| Set `issuer_auth=SIGNED`, `source_origin=PROVEN`, `cross_store_epoch=PROVEN` | REFUSE_UNSUPPORTED_SCOPE_OR_AUTHORITY | Do not convert caller assertions into proof |
| Duplicate/escaped alias, malformed JSON, wrong path, unbounded string or unknown version | Refuse | Parsing must be bounded and fail closed |

**Important distinction:** returning `STRUCTURAL_ONLY` on a mixed/replayed receipt is **not an unsafe acceptance**; the model has no trusted acceptance path at all. If a future consumer promotes this structural result to `P0/P1/P2_GO`, that consumer would itself violate the contract. This test cannot certify any producer, credential or currentness.

## Running this experiment

In a clean, ordinary-user development checkout on the exact PR head:

```sh
python -m pytest -q -rs tests/test_m60p02_synthetic_receipt_provenance_lab.py
```

Source package is not read, modified or copied. The test itself uses in-memory fake fixture bytes and may read its own module source as a no-runtime-import guard. It never reaches a real ProjectCTL, DB/WAL/SHM, installed service, host root, or P3 preserved guest custody.

## Nonclaims and next design gate

No real cryptographic signature, signing key, independently protected issuer registry, revocation, monotonic high-water, producer identity, writer exclusion, P1 same-epoch witness, source-side WAL nonmutation, independent immutable custody, live reader, Collector, CLI, or operational release is created or authorized. P0–P4 remain NO_GO.

**Next independent decision required before P03:** choose, by separately reviewed owner-governed architecture, (a) the actual authority that creates P0 source admission evidence; (b) what observable W1/ADR-040 as-of transaction and exact retained byte identities P1 can bind; and (c) which separately administered entity would authenticate a P2 assertion. Do not invent a production producer by extending the in-memory fixture.
