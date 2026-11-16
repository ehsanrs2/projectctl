# G7 — Synthetic epoch-anchor independence contrast

**Issue:** #151. **Baseline:** merged G6 PR #150 at
`91f1c540818157243fe2d5f80c301af2360bcecf`.

This is an *experiment*, not an accepted cross-store consistency mechanism.
Reuse the G6 A/B fixture generator and actual G5→G4 preview. No new
production schema, reader, writer, issuer, cryptographic key, runtime or CLI.

## Falsifiable matrix

| Case | Independently pinned *test-only* A/B digest-pair match | Self-recomputed digest match | Actual G4 authority |
| --- | --- | --- | --- |
| DB A + Context A | A only | Yes | UNATTESTED |
| DB B + Context B | B only | Yes | UNATTESTED |
| DB A + Context B | Neither | Yes | UNATTESTED |
| DB B + Context A | Neither | Yes | UNATTESTED |
| Coherent A evaluated against pinned B | No | Yes if regenerated | UNATTESTED |
| Context replaced after capture | Previously pinned A rejects *current* pair | Yes if regenerated | Historical G4 output still UNKNOWN |
| Attacker replaces the supposed anchor | Replaced digest can match mixed pair | Yes | UNATTESTED |

The external fixture oracle is generated from known fixture history before
the candidate pair is assembled. The two SHA-256 digests represent exact
raw bytes, not semantic validity. It distinguishes **these chosen
differing fixtures only**. Such a table does not make an independently
published trusted as-of epoch, even when the values match. The attack
demonstrates why self-attested content hashes do not authenticate epoch
origins or writers.

## Boundary versus earlier work

- G6 established that same-task mixed bytes can pass G2/G4 structural checks
  while G4 correctly labels `cross_store_epoch=UNATTESTED`.
- W1c already models disposable fenced writer, durability order, atomic
  status/event/seal transaction and crash-window reconciliation. G7 does
  **not** duplicate W1c or modify its contract.
- The prior M6.0 B2b snapshot consistency review defines the required
  *separate* Writer gate and non-mutating active-WAL Reader gate.
  Test-only oracle independence does not satisfy either.
- No claim about ABA, full file-system snapshot, trusted source admission,
  durable immutable old-byte retention, custodian independence, or proof
  of present/current Run state is supported.

## Reproduction

On an ordinary nonroot Linux account:

```sh
python -m pytest -o addopts='' -q -rs tests/test_m60m6a_g7_anchor_contrast.py
python -m pytest -o addopts='' -q -rs tests/test_m60m6a_g6_epoch_mixing.py tests/test_m60m6a_g7_anchor_contrast.py
```

Until actual CI or local evidence is recorded, this is a test specification,
not an assertion that these commands passed.

**Nonpromotion:** LAB_ONLY; M6b P0–P4 remain NO_GO,
R0b stays C_FAIL_CLOSED. To proceed beyond the synthetic experiment
requires a separately authorized producer/trust-topology decision in
Issue #124, independently held durable commit/epoch evidence, exact
artifact retention, safe active-WAL reader and custody/privacy review.
