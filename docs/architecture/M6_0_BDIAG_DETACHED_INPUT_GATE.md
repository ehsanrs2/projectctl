# M6.0 B-Diagnostic Detached Input Gate — checksum is not authenticated provenance

**Status: TEST-ONLY DETACHED-FIXTURE EXPERIMENT. No Collector, producer, public CLI or real-source access.**
**Baseline:** merged B-Diagnostic PR #99, main b3feb34519461ebb853c1c694e6b9591c8859711.
**Architecture authority:** Accepted ADR-039 local non-authoritative read-only Trace; ADR-040 Path A as a future trusted writer Seal; R0b option C keeps active WAL fail-closed.

## 1. Decision boundary

M0 experiments have not demonstrated complete all-writer exclusion for operational migration. A separately protected detached input *could* eventually let an observer avoid opening the original live project. But independently checking a list of copied file hashes proves neither where the files came from, that they describe the same instant, nor that an owner-writable directory is immutable.

This PR checks only a fixed **synthetic ProjectCTL v2 rollback-journal** detached package. It contains no source snapshot producer or authenticated signature, never copies or reads an operator project and provides no public CLI. Tests create all source data themselves in temporary pytest directories.

### Test-only package layout

    projectctl-bdiag-detached-<test-suffix>/  (0700)
      bdiag-inventory.json                   (0400)
      .projectctl/                           (0700)
        state.sqlite                         (0400, rollback only)
        runs/                                (0700)
          run-bdiag-detached/                (0700)
            context-manifest.json            (0400)

The canonical JSON inventory lists exactly those two data paths, sizes and SHA-256 digests; it explicitly contains source_origin=UNATTESTED, cross_store_epoch=UNATTESTED, external_producer_signature=ABSENT and test_fixture_only=true. The project/run/task identifiers are synthetic constants. This is an **internally self-consistent manifest**, not cryptographic authentication of its creator.

## 2. Implemented verifier and bounded evidence

The helper at scripts/bdiag_detached_input_lab.py is **import-only experimental code** (no CLI and no call sites from production projectctl). Its only supported input is an ordinary-user-owned, private POSIX lab directory named with the exact test prefix. It checks:

- Fixed layout with no unexpected root, SQLite WAL/SHM/rollback journal or other file;
- Owner, mode 0700 directories, 0400 regular single-link file leaves, no symlinks or hardlinks, bounded byte lengths;
- Entire canonical inventory agreement, exact relative paths and digests; identity, size, ctime and mtime sampled before and after the private Reader runs;
- Existing B1 rollback-only SQLite run reader and artifact reader, B1b historical parser/validator, conservative Trace assembly and canonical JSON formatter;
- No source ProjectCTL directory access by the verifier, no SQLite VFS access to live WAL;
- Always completeness=incomplete|inconsistent, assessments=[], sanitized error codes and no raw event-payload/prompts/absolute worktree path in the derived Trace.

The observer can run after the **whole synthetic source directory has been deleted**, demonstrating only that subsequent read/replay uses the detached copy rather than a live origin.

The only permitted decision is NO_GO_DETACHED_FIXTURE_BYTES_ONLY. Source-origin, cross-store-epoch, independently-immutable, Collector/CLI, WAL Reader, writer Seal and migration flags are all false. No success output may turn those into authorization.

**Critical negative test:** a same-UID adversary can change the test ContextManifest and recompute the inventory's hashes. That republished package can still pass the byte-consistency checks, yet remains source_origin_proven=false, cross_store_epoch_proven=false, independently_immutable_proven=false. File mode 0400 is not an independently enforced immutable boundary: the file owner can change permissions.

## 3. Falsification matrix

| Scenario | Expected lab behavior |
| --- | --- |
| Synthetic source deleted after package construction | Repeatable incomplete trace using only detached bytes |
| Modified or missing DB, context or inventory | Refuse unmatched data |
| Noncanonical, duplicate-key or self-declared authorized inventory | Refuse |
| Symlink, hardlink, wrong permission or directory identity | Refuse |
| Unlisted WAL, SHM, hot rollback journal, foreign leaf | Refuse |
| File changed after first sampled snapshot | Refuse output |
| Same-UID modification and matching re-signed inventory | May pass byte check but **NO TRUST** in provenance, epoch or immutability |
| Syntactically invalid but inventory-consistent context | Conservative inconsistent trace, zero assessments |
| Raw secret in private event payload and absolute worktree path | Raw secrets not emitted in canonical output |

Input fingerprints measure bytes, modes, inode, size, mtime and ctime, not all transient VFS effects or atime. Their own fingerprint reads may update atime. The standalone SQLite B1 Reader opens via pathname after descriptor-based preliminary validation; concurrent same-UID swaps and ABA replacements are not proven impossible by this test. The fixture cannot independently prove that its original source was quiescent or that DB and JSON originate from one epoch.

## 4. Why this does not yet deliver the preferred detached-input product

A valid independent snapshot needs **both a producer and a protected custody boundary**; this PR provides neither. Next separate design gate must choose and verify:

1. **Safe producer:** exact DB+external-JSON capture at one independently evidenced source epoch, or an explicitly approved offline admission with all writers and preopened FDs ruled out, plus hot-journal refusal. Sequential copies of live WAL/SHM/JSON cannot assert atomicity.
2. **Source provenance:** independently verifiable project/run identity, issuer/producer authorization, and authenticated manifest/capture conditions. The local package cannot sign itself into being trusted.
3. **Protected custody:** non-hostile reader cannot replace, chmod or race stored bytes; unique immutable content address or separately enforced read-only protection, with explicit retention and privacy policy. A root-owned or privileged mechanism requires *new* explicit permission and review.
4. **Consumer:** path/descriptor and SQLite VFS hardening, hostile filesystem tests, no authority-side effects, exact same-epoch validation.
5. **Output contract:** remain incomplete/inconsistent and assessment-free for diagnostic-only uses. A Collector or public trace export command needs another accepted owner decision with privacy/destination/metadata/no-mutation tests.

There is no change to M0, W1 or R1 acceptance from this experiment, nor to the accepted ADR-040 Path A trusted-Seal strategy.

## 5. Operator runbook and acceptance ceiling

After owner review and merge, run only the focused **ordinary-user** test. Tests build and destroy disposable v2 SQLite/JSON fixtures under pytest tmp_path:

    cd "$HOME/projectctl-m0k-lab"
    git fetch origin
    git status --short
    git switch --detach origin/main
    source .venv/bin/activate
    python -m pytest -q -rs tests/test_m60bdiag_detached_input_gate.py

No sudo, root, changing file permissions or database journal modes in any real project, source-snapshot acquisition, AppArmor/systemd, v3 migration, W1 Seal, R1 Reader, Collector, public CLI or new Worker/Task permissions are within this PR.

**Disposition:** fixture-byte integrity and detached read composition LAB_ONLY; actual immutable snapshot, authenticated project provenance and cross-store historical epoch remain UNVERIFIED. Operational v2→v3, W1, R1 and Collector/CLI remain **NO_GO**.
