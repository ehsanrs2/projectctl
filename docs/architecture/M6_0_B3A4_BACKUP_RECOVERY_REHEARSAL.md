# M6.0 B3a4 — WAL-inclusive Backup/Restore Rehearsal for Future v2→v3 Migration

**Status:** Isolated lab only, NOT an authorized production migration, backup command, restoration tool or source reader.
**Baseline:** `main@1dcb25dff1c6f4a4697499425d03648c46faaeb9` (PR #64 merged).
**Governing:** ADR-039 (read-only export); ADR-040 Path A (trusted writer seal), both Accepted.

## Goal and scope

B3a3 proved that individual v2→v3 migration statements and version
bookkeeping can be rolled back atomically on disposable **real ProjectCTL
v2** SQLite schemas. It did **not** prove the durable backup and recovery
side of a production upgrade, especially with committed-but-uncheckpointed
WAL frames.

This new bounded lab uses SQLite's **connection backup API**, selected
only by caller-owned disposable v2 fixtures, and creates a verified
no-clobber **backup file** in an existing disposable directory. It keeps
the main system at `PROJECT_STATE_DB_VERSION=2`.

## B3a4 experimental mechanism

`projectctl/trace/seal_backup_lab.py` exposes
`rehearse_disposable_v2_backup(source, destination, fault_hook=None)`.

The caller must already hold a source `sqlite3.Connection` (opened for
maintenance, NOT export). It must not have an active transaction and
must be on the supported POSIX platform. The lab checks the source's
ProjectCTL `application_id`, exact v2 `user_version` and
`PRAGMA integrity_check`. It refuses an in-memory source, nonexistent
or immediate symlink destination directory, or an existing destination.

For an allowed disposable fixture it:

1. Creates a mode-0600 staging file in the existing destination folder
   with `tempfile.mkstemp`.
2. Runs SQLite's `source.backup(target)` so **committed WAL records are
   included in the SQLite-consistent backup**, not blindly copied as
   separate DB and WAL file bytes.
3. Closes the destination database, reopens staging, checks ProjectCTL
   ID, v2 and `integrity_check=ok`.
4. Calls `fsync` on the completed staging file.
5. Publishes via **hard link to a new name**, not `os.replace`, so an
   existing named backup cannot be overwritten (`EEXIST`).
6. Calls directory `fsync` after the link and removes the staging name
   in cleanup. The completed backup remains private to the local folder.

The explicit `fault_hook` is for controlled tests at four points
BEFORE final publication: just after staging creation, copy, validation
and file fsync. If a simulated fault happens, it must not publish a
named backup and must remove its stage name.

This **backup API legitimately opens the source SQLite connection**,
possibly interacting with its WAL/SHM machinery; unlike the eventual
read-only exporter, **a migration maintenance writer does not promise
source sidecar non-mutation**. Do not reuse this path in the trace
collector.

## Covered lab tests

- Real disposable v2 ProjectCTL database under `tmp_path`, with an open
  WAL writer and a committed observation, is fully copied into an
  independently openable v2 backup.
- Copying that backup into a *new disposable restore target* recovers
  the expected observation without replacing the source database.
- Four injected prepublication failures leave **no named backup** and
  clean up the staging name; source fixture remains readable.
- Corrupting staged bytes after copy and before validation refuses
  publication.
- No overwrite of existing backup and no symlink follow at the final
  leaf or immediate parent.
- Missing destination folder and an active source transaction fail
  before creating output.
- In-memory source and incorrect v3 source version are rejected.
- No Runtime migration registration: v2 initialization remains v2
  and `GLOBAL_STATE_DB_VERSION` is unchanged.

## Residual risks — BLOCKING a production migration

1. **Maintenance quiescence is NOT enforced.** A correct SQLite online
   backup gives a consistent SQLite database, but without a
   separately proven exclusive maintenance/writer coordination
   protocol it may not correspond to the exact pre-migration state
   intended by the operator. It does not include separate JSON files,
   and it does not create a cross-store as-of Seal.
2. **Full crash durability is NOT established.** There is currently
   no power-loss or kill-process test during/after hard-link publication
   and directory fsync. If fsync fails *after link creation*, a named
   backup can be visible while its durability is uncertain; treat it
   as untrusted until independently validated, do not auto-restore.
3. **Security is prototype-only.** Only the immediate parent symlink
   and destination existence are checked; ancestor symlinks, path swap
   races, hard-link permissions, storage identity, malicious directory
   replacement, quota, full disk and parent inode retention require
   descriptor-anchored production design. Do not copy this file into a
   privileged migrator unchanged.
4. **Backup privacy, retention and authenticity** remain undecided:
   backup includes the entire private SQLite authority, potentially
   sensitive run state/manifest/event payloads. Mode 0600 is not
   encryption, authentication, retention, or secure deletion.
5. **Restore policy NOT implemented.** The test restores only into a
   fresh disposable filename; no operation overwrites a live database
   or removes/corrects WAL/SHM. A real rollback requires explicit
   maintenance lock, separate writable/recovery mode, ownership and
   user intervention, plus exact before/after state validation.
6. **Migration launch not implemented.** No `projectctl migrate`
   wiring, no `PROJECT_STATE_DB_VERSION` bump, no durable v1→v2→v3
   migration chain, no verification writer instrumentation and no
   `trace_seals` in production.
7. The existing `projectctl/storage/sqlite.py::_sqlite_backup`
   remains unchanged. No assumptions about its durability or migration
   gating are introduced by passing this lab.
8. **Collector/WAL reader is distinct.** The export reader cannot open
   the source to make this backup or produce Seals; B2a remains
   `snapshot_proven=False` and Slice B `assessments=[]`.

## Next production gate (separate reviewed PRs)

A. Approve a **maintenance and reader/writer quiescence protocol**,
   including how to detect active Run leases and concurrent provider
   processes, and ensure one source epoch is backed up and migrated.

B. Specify anchored no-follow backup directory operations, fail closed
   on unexpected symlink/mount/permissions, controlled backup naming,
   owner-private retention budget, full WAL capture and verified
   `integrity_check` with stepwise fault injection including fsync
   after publication.

C. Specify and test backup recovery: durable migration state marker,
   ambiguous-commit detection, v2/v3 version agreement,
   restore **only through an explicit operator-approved maintenance
   action**, recovery of WAL/SHM safely, and no fallback to silently
   reading mixed or outdated state.

D. Upgrade real `projectctl migrate` and v3 initialization *only*
   after that protocol and the final table keys/foreign-key same-run
   integrity are accepted. Existing v2 clients must reject v3 without
   unexpected mutation.

E. Separately integrate Seal publication with the trusted verifier's
   `VERIFYING -> READY_TO_INTEGRATE` transaction; verify same-run JSON
   durability and digest lineage. Safe live-WAL read remains an
   independent Gate R before any Trace Collector.

## Exact-head CI and optional local smoke

CI on this PR must pass both the full Python build/test/schema export
and pinned Codex SDK jobs. CI passing this controlled fixture does
not establish production backup safety. Targeted local tests are
optional while exact-head CI is green; actual fsync, crash and concurrency
tests will require real supported environment acceptance later.

```bash
git fetch origin
git switch --track origin/experiment/m6.0-b3a4-backup-recovery-rehearsal
source .venv/bin/activate
python -m pytest -q tests/test_m60b3a4_backup_recovery_rehearsal.py
GIT_PAGER=cat git diff --check origin/main...HEAD
git rev-parse HEAD
python --version
```

**No merge without owner instruction.** If reviewed and merged, this
remains a disposable backup/restore feasibility test only; no operational
database, writer authority or Exporter is changed.
