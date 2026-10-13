# M6.0 B2a — Detached WAL Feasibility and Cross-source Consistency Gate

**Status: Experimental candidate, NOT an operational WAL reader or accepted trace collector**  
**Baseline:** `main@76d62a50575a8c76ea47c5f7ee5761f222af4f0d` (PR #58 merged)  
**Architecture:** ADR-039 (Accepted bounded local-only design)  
**Implementation:** `projectctl/trace/wal_probe.py`; `tests/test_m60b2a_detached_wal_probe.py`

## Why the existing reader cannot support real ProjectCTL runs

B1a `read_run_db_snapshot` deliberately refuses the WAL SQLite file header
before connecting. That protects original `-wal`/`-shm` sidecars, but
ProjectCTL's normal `connect_db` enables WAL.

SQLite's [WAL documentation](https://www.sqlite.org/wal.html#read_only_databases)
permits some read-only WAL connections when `-wal` and `-shm` already exist
or the containing directory is writable. It does **not** promise that an
application's absolute **no-write-to-authority** requirement is automatically
met. Its [backup API documentation](https://www.sqlite.org/backup.html)
describes transaction-consistent live-database copies but requires opening
the source through SQLite; the source-VFS sidecar behavior therefore still
needs to be explicitly resolved for this project's security contract.

## B2a experiment: isolated candidate, no authority promotion

The private function `probe_detached_live_wal(root)`:

1. Uses the existing POSIX `_directory_chain` and `O_NOFOLLOW` helpers to
   open the existing `.projectctl/state.sqlite` and `state.sqlite-wal`
   by fixed names. No source SQLite connection, migrations, locks, file
   initialization, network or Worker operations occur.
2. Takes a bounded byte snapshot of each source (limits: 32 MiB DB and
   16 MiB WAL), compares pinned-fd identity before/after, and rejects
   malformed/missing WAL or rollback-mode sources. These are **feasibility
   bounds**, not adopted general-purpose data-size limits.
3. Reads the two files a second time and rejects mismatched byte samples.
4. Creates **owner-private `0700` temporary staging outside the selected
   project**, populates fixed `0600` copies, then invokes SQLite only on
   that *detached staging*, with `mode=ro`, `query_only=ON`, a bounded
   transaction and `PRAGMA integrity_check`. Any SQLite `-shm` mutations
   and cleanup affect the temporary copy alone.
5. Re-reads the source pair and rejects any observed changes.
6. Returns only two candidate SHA-256 digests, `detached_integrity="ok"`,
   and **`snapshot_proven=False`**. It returns neither private raw bytes
   nor an `ExecutionTraceBundle` and cannot be used as a `present`
   descriptor/verification conclusion.

The experiment does **not** read or copy the source's `-shm` sidecar.
The derived stage may build its own `-shm`; the original file is untouched
by this probe. No database record, task, event or project identity is
disclosed via its return value. Private raw staged bytes can contain secrets:
do not expose them or upload the temporary directory.

## Critical limitation: two matching copies are NOT an atomic snapshot

The DB file and WAL are read **sequentially**, not within one SQLite
transaction or a filesystem-level atomic snapshot. A writer or checkpointer
can interleave across these reads, producing a byte combination that:
- is individually valid yet never existed as one coherent committed state;
- causes SQLite on the *staged* pair to ignore an incomplete/corrupt WAL tail;
- appears identical on repeated reads after an ABA-style concurrent change;
- appears correct under `integrity_check` but omits a committed transaction.

Therefore even passing all tests **cannot prove latest committed WAL
completeness** or a coherent ProjectCTL run. Double-read comparison and
SQLite stage integrity are useful rejection checks **only**. Never set
`snapshot_proven=True` based solely on them. No Collector/CLI may call
this function as an authority source or trust its digests as evidence.

## Proposed architectural paths to resolve the actual consistency gap

### Path A — cooperative authority-consistent snapshot (evaluate first)

Investigate an existing ProjectCTL-owned read barrier/snapshot interface
that can coordinate SQLite and persisted run artifacts **without** modifying
or locking execution authority in unapproved ways. Source SQLite backup APIs
need tests that show they cannot create or edit source sidecars; if this
cannot be demonstrated, the normal SQLite backup path is not acceptable.

### Path B — filesystem-managed atomic snapshot

A supported filesystem snapshot primitive would capture SQLite DB/WAL and
the run artifact directory together at one instant. It must be available
on supported environments without elevated privileges, satisfy root
containment and privacy, and clean up without project mutations. This is
not currently promised.

### Path C — conservative explicit refusal

If neither A nor B can prove cross-source consistency and source
non-mutation, retain B1a's safe WAL refusal or allow a separately
documented, **non-authoritative and explicitly incomplete** diagnostic
snapshot only after its own policy review. Do not silently call a
best-effort detached read a verified authoritative run snapshot.

## Tests and acceptance

`tests/test_m60b2a_detached_wal_probe.py` proposes checks for:
- WAL kept open by a real writer, with its uncheckpointed commit visible
  in the staged copy;
- exact byte/mtime/ctime/inode equality for original DB/WAL/SHM before
  and after a successful probe;
- a guard proving every `sqlite3.connect` call goes to the private copy;
- changes injected during the staged inspection causing a typed refusal;
- no directories created if source is absent, symlinked WAL rejection;
- oversize/malformed/non-WAL refusal; private staging directory cleanup;
- rejection when `TMPDIR` is configured inside the source project;
- explicit `snapshot_proven=False` and no disclosure of source payloads.

The current branch has **not** been tested on the owner's checkout.
Even a green result allows only the feasibility conclusion and a
human-reviewed next consistency strategy, **not** use in the exporter.

Run focused/related/full tests on the `uv` environment:

```bash
git fetch origin
git switch --track origin/experiment/m6.0-b2a-detached-wal-probe
source .venv/bin/activate

python -m pytest -q tests/test_m60b2a_detached_wal_probe.py \
  tests/test_m60b1b_artifact_validation.py \
  tests/test_m60b1_readonly_snapshot.py \
  tests/test_m60b0_trace_format_policy.py \
  tests/test_m60a_trace_contract.py

python -m pytest -q
GIT_PAGER=cat git diff --check origin/main...HEAD
git rev-parse HEAD
python --version
```

## Release and authority boundary

No changes to `docs/PROJECT_STATE.yaml`, ADR-039, `RunStore`, Worker,
verification, run admission, SQLite migrations, CLI registration or
`ExecutionTraceBundle v1`. Package remains `0.41.0`; no tag or release.
The account's earlier GitHub Actions quota exhaustion is not green hosted
CI. Merge only after local smoke/full-suite checks and security review;
the experimental probe **must remain non-authoritative even if merged**.
