# M6.0 R0b — Current active-WAL feasibility: choose C (fail closed)

**Status: PROPOSED READER FEASIBILITY DECISION, not implementation authority.**
**Baseline:** merged rebaseline PR #97 at main f9b1c7ae31cfc1223586ca1001747dc36c67f0f7.
**Constraints:** Accepted ADR-039 local read-only/non-authoritative Trace; accepted ADR-040 Path A as-of Verification Seal design. No schema v3 migration, operational W1 publisher, R1 reader, Collector, public CLI or privileged guest experiments.

## Decision: C at the *current source and evidence baseline*

**Selected route: C — treat active ProjectCTL v2 WAL export as unsupported and fail closed until separate independently verified reader evidence exists.** This is not a claim that SQLite WAL can never be read without side effects, and not a reversal of ADR-040's trusted as-of Seal design. It says the *present repository and deployment evidence* cannot support route A or B **under ADR-039's stronger source-nonmutation and cross-store epoch requirements**. The existing production-facing read-only B1 snapshot deliberately rejects WAL headers before connecting: preserve that behavior.

The machine-readable, entirely nonauthorizing statement is in [r0b-current-feasibility-decision.json](r0b/r0b-current-feasibility-decision.json), with literal false flags for A/B proofs, source-WAL-Reader, Trace CLI, writer Seal, migration and root trial. Its successful tests do not promote any flag.

## What is supported, what is not

| Path | What official SQLite supports | What the M6.0 proof must additionally establish | Current result |
| --- | --- | --- | --- |
| **A — source-native mode=ro WAL reader** | SQLite 3.22+ can read a WAL-mode DB as read-only if WAL/SHM exist and are readable, or the containing directory permits sidecar creation, or immutable mode is selected | No writes or forbidden metadata side effects on DB, WAL and SHM **at any moment**, including SHM creation/rebuild, read-side checkpoints, cold open, active concurrent writer and crash; a coherent **DB + separate JSON** as-of epoch | **UNVERIFIED**. A successful SELECT is not enough |
| **B — atomic or writer-cooperative snapshot** | SQLite transactions/backup can yield a consistent **database** view, subject to source VFS behavior | Indivisible or externally authenticated epoch of DB/WAL and exact fixed external JSON bytes, durable immutable retention, storage scope and reader/no-mutation proof | **UNVERIFIED**. A sequential DB/WAL/JSON copy or backup alone is not sufficient |
| **C — fail closed** | No unsupported source must be opened or reported complete | Keep existing WAL refusal; do not produce unsupported complete/verified Trace | **Selected for current baseline** |

The public [SQLite WAL document](https://www.sqlite.org/wal.html) explicitly documents the read-only sidecar/immutable conditions. Its [WAL-index format](https://www.sqlite.org/walformat.html) documents that SHM is a shared-memory index, subject to normal changes and reconstruction. [SQLite URI flags](https://www.sqlite.org/uri.html) state that immutable skips locking/change detection and may yield incorrect results if files actually change; therefore using immutable on a **live changing source** is not an acceptable shortcut. [SQLite PRAGMA query_only](https://www.sqlite.org/pragma.html) forbids SQL writes but does not mean the connection cannot perform WAL checkpoint operations. None of these SQLite features prove coherence with separately published JSON.

## New actual disposable counterexample

[tests/test_m60r0b_current_active_wal_decision.py](../../tests/test_m60r0b_current_active_wal_decision.py) creates an entirely disposable **actual ProjectCTL v2 WAL schema** using its existing initializer under pytest tmp_path. It adds one test-only table to that disposable database, retains an active SQLite writer and has a native mode=ro, query_only reader open a WAL snapshot after a first read. The writer commits a second DB epoch, then **separately** publishes an epoch-2 JSON leaf. Within the pinned SQLite read transaction, the reader still sees DB epoch 1 but JSON epoch 2. Thus two individually valid reads can form a hybrid epoch that no single write transaction certified. A new SQLite read sees DB epoch 2. The test *does not* claim the SELECT performed no WAL/SHM writes; source-native effects remain unproven.

Another test confirms the current production-facing rollback-only snapshot reader refuses the disposable active WAL before native source connection. Exact decision data and absent public Trace registration are also checked. These tests require **no changes** to projectctl/, DB version, installed services or the operator's projects.

The original [R0 matrix](M6_0_R0_LIVE_WAL_READER_FEASIBILITY.md) already covers other isolated live-WAL/SHM/checkpoint scenarios and keeps candidate flags false. R0b deliberately does **not** repeat all its tests; it converts the observed capability gap into an explicit project delivery decision.

## Reopen gates (must be new independent, scoped work)

**Route A reopen proof:** a chosen OS/SQLite/VFS/filesystem matrix with independent kernel/VFS-level evidence about every DB/WAL/SHM source open, mmap/shared memory, lock, checkpoint and write side effect under real concurrent writers and cold/missing SHM. Address source-content vs atime/metadata policy. Even if source-no-write is established, independently bind external JSON to the same verified as-of Seal epoch.

**Route B reopen proof:** a trusted writer-cooperative or genuinely atomic snapshot cut with independently verified transaction provenance, retained immutable exact bytes, active writer/checkpoint interleavings, privileged/snapshot topology if relevant and no exporter-induced source mutation. A frozen SQLite snapshot alone does not include independently replaced JSON unless a separate synchronized version/epoch contract is proven.

**If neither reopens:** keep C. A user-visible *quiescent rollback-journal diagnostic-only incomplete* export would be a **different scope**, requiring its own ADR-039 privacy/mutation/CLI acceptance and never marketed as active-WAL or trusted sealed Trace.

**Important sequencing:** R0 is the feasibility decision *first*, not a complete R1. The accepted ADR-040 writer-side Seal path remains valid *architecturally* but operational W0/M0/W1 investment should be explicitly justified against this Reader gate rather than proceeding through endless M0 journal layers. F-01/F-02/F-03/F-04 remain open; R0b only documents the current unsupported choice.

## Acceptance boundary and operator instructions

This PR is limited to one doc, one checked-in JSON decision and one disposable-test module. It adds no source reader, live source connection path, Collector, CLI, migration, root helper, systemd/AppArmor policy, network call, or real project modification. Keep Draft and require exact-head GitHub CI. If merged, current expected operator-only nonroot check:

    cd "$HOME/projectctl-m0k-lab"
    git fetch origin
    git status --short
    git switch --detach origin/main
    source .venv/bin/activate
    python -m pytest -q -rs tests/test_m60r0b_current_active_wal_decision.py

**Never test this against a real project DB.** The test deliberately connects SQLite to a new disposable WAL DB, and that test-owned WAL/SHM **may** mutate. It is an experiment illustrating why unrestricted active source reads remain NO-GO, not a safe source reader recipe.

**Decision ceiling:** R0b selected C for present evidence **only**; R1/Collector and W1/M0 operational activation still **NO_GO**, as is any new worker/task authority.
