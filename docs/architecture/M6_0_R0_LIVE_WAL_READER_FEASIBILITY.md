# M6.0 R0 — Live-WAL Read-only VFS Feasibility Evidence

**Status:** Experimental **tests-only** investigation; no operational
Reader, no source non-mutation proof, no trace Collector.
**Baseline:** `main@2e47b50b0308b0919114bbdd0f88e6ce97fed8e2`
(PR #65 merged). Architecture audit PR #66 remains a separate, unmerged
documentation review at the time R0 was branched.
**Governing:** ADR-039 read-only non-authoritative Trace; ADR-040 Path A
trusted writer-published as-of Seal (accepted designs only).

## Motivation and the precise hypothesis

A valid as-of Seal in a committed SQLite WAL transaction is not enough
for an operational read-only Trace. The exporter must retrieve it and
its event prefix without changing the authoritative DB/WAL/SHM files,
then bind the correct fixed-version file bytes to the **same epoch**.
Current `projectctl/trace/snapshot.py` correctly refuses live-WAL
databases before opening a native source SQLite connection.
B2a can only read a **raw detached candidate** and explicitly declares
`snapshot_proven=False`.

R0 asks a narrower, testable question: What do **native SQLite
`mode=ro`** reads do to existing WAL/SHM files in disposable conditions,
and which consistency properties can they actually establish?

## Implemented experimental method

Only `tests/test_m60r0_live_wal_reader_feasibility.py` is added. It
has NO import, registration or call site in `projectctl/trace/`,
`RunStore`, `projectctl migrate`, CLI, verification, providers or
scheduler. All native source-SQLite connections open freshly created
**disposable** test WAL fixtures under pytest `tmp_path`.

The test-local diagnostic type `R0Candidate` always sets these three
flags to **False**, and rejects attempts to set them True:

- `snapshot_proven=False`
- `source_nonmutation_proven=False`
- `cross_store_epoch_proven=False`

A successful `SELECT` is recorded only as `candidate_readable`.
Native SQLite `mode=ro` with `PRAGMA query_only=ON` and one
`BEGIN`/read/`ROLLBACK` is **deliberately executed on the disposable
source** to examine side effects. DO NOT copy this unapproved experiment
to production or run it against any real ProjectCTL DB.

The helper samples bounded regular-file SHA-256, device/inode, size,
mtime, ctime and atime for the main SQLite file, WAL and SHM before and
after. It reports changed source content/metadata, created sidecars and
access-time differences **without certifying the absence of transient
writes or races**. Reading files to sample them may itself advance
`atime` on some filesystems; the test does not confuse matching
samples or an unchanged atime with a formal no-side-effect proof.

## Experiment matrix

| Scenario | What the test establishes | What it does NOT establish |
| --- | --- | --- |
| Live writer, committed uncheckpointed WAL, existing SHM | Whether native RO SQLite reads latest committed fixture bytes | No general guarantee that SHM was never modified; no atomic JSON pairing |
| One pinned RO DB transaction while another connection commits | Existing SQLite WAL transaction preserves a consistent **database-only** read view | No fixed-file external evidence epoch and no source-sidecar non-mutation |
| Raw detached clone with missing SHM | Observe whether native RO VFS reads it or creates sidecars | Clone DB+WAL is not atomic at original source; clone readability cannot prove original epoch |
| Direct DB read with external JSON replacement mid-transaction | Confirm DB read transaction does **not** freeze external named JSON | Cannot label DB and JSON as the same as-of Seal |
| Checkpoint intentionally interleaved between samples and source connect | No conversion of successful SQLite read into proven atomic epoch | Full adversarial scheduler/state space not exhausted |
| Rollback-journal DB, missing source, symlinked WAL | Guard rejects unsupported/unsafe inputs without making a source SQLite connection | Does not prove absence of all filesystem metadata effects |
| Attempt to set proof flags to True | Result contract refuses false success | Type check is only test-local, not a production trust boundary |

## Preliminary SQLite observation (independent local experiment)

An independent disposable SQLite 3.46.1 Python experiment on the
reviewer's Linux sandbox read a committed WAL row using `mode=ro`.
WAL/SHM fingerprints differed between pre/post samples while its
writer connection remained open. That observation **does not isolate
which connection/process action caused the difference**, and is
**not** a proof that all native read-only connects necessarily mutate
these files. It is sufficient to reject an unverified assumption that
`mode=ro` alone satisfies ADR-039's side-effect-free condition.
The pytest matrix records its own platform behavior.

## Decision boundary and R0 exit criteria

R0 cannot be marked **PASS: supported production Reader** solely
because this tests-only matrix is green. Passing CI means the
experiment and its negative assertions ran correctly, not that all
observed changes were absent or that safety is proven.

A subsequent **separate** Reader architecture decision must choose
one route and prove its contract before any production implementation:

A. Source-native read-only WAL transaction with OS/VFS-level proof that
   the selected source file and sidecar mutations are forbidden or
   safely prevented **under active writers, absent SHM and checkpoints**.
   It must not rely on `immutable=1` against a live source or merely
   compare two samples.
B. A genuinely atomic, supported filesystem snapshot of the database,
   WAL and relevant artifacts or a vetted cooperative writer-published
   consistent copy; prove paths/retention/portability and a declared
   as-of Seal. A sequential raw detached copy is not enough.
C. Explicit **fail-closed** absence of a supported live-WAL Trace
   Reader on platforms where A or B cannot be proven.

**Important:** a writer-generated Seal has its own independent **Gate
W0**: one trusted transaction for status/event/Seal, after durable
verified file publication and same-run fencing. Gate R0 cannot
substitute for W0, and neither can promote L3 semantic lineage or L4
independent verification/delivery assessments.

## Tests and follow-up platform evidence

CI runs this matrix on GitHub Actions Linux/Python 3.12 alongside
the existing full suite, schema policy/export and pinned Codex SDK.
A separate local macOS/Linux matrix with ownership/access-time policies,
abrupt process termination and source data/WAL/SHM fingerprints is
required for an eventual **production** Reader proposal; no such
coverage is claimed here.

Optional operator smoke:

```bash
git fetch origin
git switch --track origin/experiment/m6.0-r0-live-wal-reader-feasibility
source .venv/bin/activate
python -m pytest -q tests/test_m60r0_live_wal_reader_feasibility.py
GIT_PAGER=cat git diff --check origin/main...HEAD
git rev-parse HEAD
python --version
```

## Disposition

**NO-GO for a working WAL Reader or Trace Collector until A or B has
been independently proven.** This R0 experiment must remain non-
authoritative, with no new source connection in production. No
Migration, trusted writer Seal emission, version bump, public Trace
schema/CLI, Worker/Task authority or release is modified by R0.
