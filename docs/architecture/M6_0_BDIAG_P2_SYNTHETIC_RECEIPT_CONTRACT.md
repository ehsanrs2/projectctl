# M6.0 B-Diagnostic P2 — Synthetic Snapshot Receipt Contract

**Status: TEST-ONLY / PURE CLAIMS VALIDATION, NOT PRODUCER AUTHENTICATION.**
**Base:** merged PR #102, main e7784004d5fddd50f34d7916f8edd7e05afdfbca (2026-10-19).
**Controls:** accepted ADR-039, accepted ADR-040 Path A (future Verification as-of Seal only), R0b active-source WAL refusal C, and [Snapshot Producer & Trusted Custody P0–P4 design](M6_0_BDIAG_SNAPSHOT_PRODUCER_TRUSTED_CUSTODY_DESIGN.md) from merged PR #101.

## Narrow hypothesis and nonclaims

The preceding detachable fixture (#100) is self-hashed and has no independent provenance, custody or cross-store epoch. The design review (#101) made P2 a mandatory independent producer-receipt authentication requirement. This PR tests only a **synthetic, bounded, deterministic receipt representation and its structural negative gates** — never cryptographic verification, real writer/capture service, independent trust anchor, persistent replay registry or source custody.

The new import-only helper at scripts/bdiag_synthetic_receipt_lab.py is **outside the packaged projectctl runtime**. It does not access files, databases, network, keys or OS policy; it neither produces nor consumes real ProjectCTL snapshots and does not register a CLI. Tests are purely in-memory. Nothing invokes the helper from a production Reader/Collector.

**Explicit decision is always NO_GO_P2_SYNTHETIC_RECEIPT_ONLY.** Even a perfectly parsed and context-matched receipt has literal false flags for issuer_authenticated, source_origin_proven, cross_store_epoch_proven, custody_proven, durable_replay_prevention_proven, Collector/CLI, live WAL Reader, trusted writer Seal and migration.

## Exact synthetic format — no hidden trust

The bounded canonical JSON receipt has schema_kind projectctl.bdiag.synthetic_receipt, schema_version 1, domain projectctl.m6.0.bdiag.p2.synthetic-only.v1, one stable newline and ASCII-escaped deterministic key ordering. The JSON decoder rejects duplicate keys (including escaped duplicates), malformed UTF-8, all floats/non-finite numeric tokens, unknown/missing fields and noncanonical encodings. Maximum byte length is 4096.

Only one synthetic run identifier is admitted. A receipt includes:

| Fields | Structural purpose | Why it is not proof |
| --- | --- | --- |
| issuer_claim, key_id_claim, signature_state=UNVERIFIED_NO_SIGNATURE | Bind **asserted** issuer/key identity for comparison with an externally supplied expected-claims map | No signature or independent public-key registry exists. The same party can forge both receipt and caller context |
| project_id, run_id, task_id, source_db_schema_version=2 | Detect incorrect synthetic source identity and schema when expected claims are unchanged | The reference identities are **caller-supplied**, not authoritative ProjectCTL source admissions |
| asof_status=ready_to_integrate, seal_sequence, event_prefix_id, seal_sha256 | Bind the **shape** of a future ADR-040 Verification as-of claim | No actual W1 Seal, Run transition, event transaction or independently confirmed DB/JSON epoch is present |
| artifact_bindings | Exact, sorted three-entry allowlist, lengths and SHA-256: synthetic DB, VerificationManifest and EvidenceManifest relative paths | The bytes are not opened, hashed against a real file, archived or authenticated |
| receipt_id, issue_sequence, package_id | Finite unique-issuance, monotonic-sequence and package identity fields | Receipt IDs come from an untrusted caller; the helper has **no** durable issuance log |
| capture_method=UNATTESTED_SYNTHETIC, source_epoch_state=UNATTESTED | Explicitly reject any declaration of proven capture or valid epoch | Mixed-epoch DB+JSON can still be self-consistent at the claim level |
| custody_state=UNPROTECTED, retention_policy=UNSPECIFIED_TEST_ONLY | No independently protected custody, no promised retention | chmod, local hash or claimed custodian cannot promote trust |

The experimental receipt deliberately cannot carry signature bytes, producer keys, arbitrary paths, private worker payload, issuer certificate or a field asserting verified trust. It also does not know a real project's as-of state. This is **not** an accepted public format or final P2 cryptographic protocol.

## Test matrix and what the witness actually means

| Case | Test observation | Accepted level |
| --- | --- | --- |
| Canonical key-order-stable encoding and strict parser | Deterministic byte fingerprint, validated *claimed* identity against a **caller-supplied** context | Lab structure only |
| Alter project/run/task, issuer or key claim, event prefix, Seal digest/sequence, package ID with expected context held fixed | Refusal with safe generic reason | Does not establish trusted expected context |
| Forged issuer/key/package/Seal digest **and matching forged expected context** | Can still pass syntax and equality tests; every authority flag remains false | **NEGATIVE WITNESS against authentication-by-JSON** |
| Unknown version/domain, false VERIFIED signature or IMMUTABLE custody state, arbitrary extra fields | Refuse, do not trust unapproved protocol extensions | Future real signing requires different accepted version |
| Noncanonical/duplicate keys, truncated/oversized bytes, nonfinite/float/bool integer fields | Refuse, no raw secret/path in errors | Parser only; not all production hostile-file cases |
| Reordered/duplicated/extra allowlisted artifacts, incorrect lengths/algorithms, traversal paths | Refuse | Does not validate real artifact bytes |
| receipt_id/package_id already in **caller-supplied** seen sets, revoked *claimed* issuer, nonmonotonic issue sequence | Refuse as a bounded negative filter | History, revocation and issuer legitimacy are **not** independently authenticated or persisted |
| Repeat exact same receipt with empty histories (fresh process simulation) | Both parses pass, yet durable_replay_prevention_proven=false | **NEGATIVE WITNESS against durable anti-replay claims** |
| Attempt to mutate output flag to true | Immutable result invariant refuses | Zero authority granted |

Checks deliberately exclude system wall time, cryptographic keys, on-disk registry, real SQLite transaction, detached-file hash verification and filesystem topology, so the result cannot accidentally pretend to close P0, P1, P2, P3 or P4.

## Required separate exit gates

**P0:** prove authentic source admission, all-writer boundary or approved writer cooperation and real project/run identity.
**P1:** prove one durable Versioned Verification as-of Seal plus exact retained DB/event/Verification/Evidence bytes (or separately accepted genuinely coherent atomic cut) and source-side nonmutation.
**P2:** choose a real independently controlled signer/trust anchor, approved crypto/canonical receipt version, key rotation/revocation, issuer permission and replay rules; test tampering against independent verification rather than matching attacker-controlled expected claims.
**P3:** independently enforce versioned immutable custody, crash-safe publication/retention, anti-replacement and post-restart reconciliation.
**P4:** read from genuinely admitted detached material, validate source/provenance/epoch/privacy and explicitly approve Collector/CLI output destinations. An incomplete diagnostic remains assessment-free and cannot be upgraded to historical truth.

These are future owner-reviewed decisions. **No** real key generation, signing service, source project access, permission change, WAL connection, W1 writer activation, v3 migration, root/systemd/AppArmor, operational Collector/public CLI or Worker/Task authority is approved by this PR.

## Operator after owner review and merge

The only new executable material is a **pure in-memory** pytest module, suitable for an ordinary-user Debian checkout:

    cd "$HOME/projectctl-m0k-lab"
    git fetch origin
    git status --short
    git switch --detach origin/main
    source .venv/bin/activate
    python -m pytest -q -rs tests/test_m60bdiag_p2_synthetic_receipt_contract.py
    git diff --check origin/main...HEAD

No project data, no signer keys, no private path and no superuser privileges are required. The last diff command is empty on a merged main; for reviewing this PR's patch before merge, use its merge-base and PR branch appropriately.

**Disposition:** P2 STRUCTURAL LAB_ONLY. Entire P0–P4 production proof remains UNVERIFIED. R0b current active WAL option C and all M0/W1/R1/Collector NO_GO states remain unchanged.
