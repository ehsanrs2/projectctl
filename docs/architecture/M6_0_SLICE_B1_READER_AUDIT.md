# M6.0 Slice B1 — Private Source Snapshot Reader Acceptance

**Status: Draft experimental implementation; untested on the owner's checkout.**

Base: `main@34510b411b3544a8923d75b2d6551cf4ee8ff8a1`  
Governing architecture: ADR-039 (**Accepted design**).  
This slice creates **private source-read primitives**, not a completed
`ExecutionTraceBundle`, public Collector, CLI, evaluation score or new
execution authority.

## 1. Implementation boundary

`projectctl/trace/snapshot.py` introduces two explicit operations:

- `read_run_db_snapshot(root, run_id)`: a bounded, read-only SQLite
  transaction over an existing `.projectctl/state.sqlite` row,
  `manifest_json` and up to 512 ordered event metadata records, all
  from the **same connection**. The returned internal
  `TraceDbSnapshot` contains a verified run/task identity, observed
  lifecycle status, source-version identification, derived SHA-256
  descriptors and allowlisted category-only event summaries.
- `read_run_artifact(root, run_id, kind)`: a POSIX no-follow,
  directory-descriptor-anchored bounded read of **one known leaf file**,
  returning at most 2 MiB of private bytes and their SHA-256.
  No arbitrary supplied path, globbing, file creation, symlink follow,
  recursive discovery, network access or provider execution is permitted.

The SQLite reader opens `mode=ro` and enables `query_only=ON`;
it must not use ProjectCTL's existing mutable `connect_db` or initialize
a missing state directory/database. Version-specific v1/v2
`RunManifest` parsers are selected by the source's explicit version;
unsupported schemas and mismatched run/task identities are rejected.

Events select **only** `id`, `created_at`, `event_type`; they
never select `payload_json`. Raw event types are mapped to fixed
categories without reproducing the source names. Only a fixed set of
columns is used to hash the run row, **not the entire SQLite database**.
Raw SQLite row identity and artifact bytes remain private/internal and
are not serialized in the public trace schema.

## 2. Known residual security/consistency limitations

These functions are deliberately not wired into an enabled CLI/Collector:

1. **WAL sidecars:** SQLite read-only mode can interact with `-wal`
   and `-shm`. The helper refuses incomplete pairs and compares
   file identity/size/mtime/ctime before and after a read. Such checks
   may *detect* a side effect but cannot retroactively undo one.
   A test specifically snapshots all three file bytes around a live-WAL
   reader. A failure **blocks** an operational release; do not suppress
   it or call it expected.
2. **Database/file atomicity:** one SQLite read transaction is internally
   consistent, but it does not atomically bind separately persisted JSON
   files. `read_run_artifact` checks FD/path identity; a full Collector
   still needs a bounded cross-source read/revalidation strategy and a
   typed `inconsistent_snapshot` result.
3. **Filesystem races:** no-follow descriptor traversal and post-read
   identity rechecks prevent straightforward symlink/path substitution.
   They do not establish a proof against an adversarial replace-and-restore
   attack with exact inode/content equivalence.
4. **Private data:** `TraceFileSnapshot.raw_bytes` and internal SQLite
   values may contain secrets. They are available only to internal
   Reader code and never copied to `ExecutionTraceBundle`. The future
   Collector needs strict version parsers and an allowlisted field map.
5. **Phase-specific artifact requirements:** the Reader can read one
   explicitly requested source; it does not decide whether missing
   verification or delivery files are appropriate for a planned,
   cancelled, failed or passed run. That is a separate Collector decision.
6. **Authority:** successful syntax/schema validation is not proof of
   independent verification or delivery. Initial Slice B must always
   emit `assessments=[]`.

## 3. Test matrix

`tests/test_m60b1_readonly_snapshot.py` covers:

- deterministic repeated cold-DB snapshots with exact no-mutation
  comparison of DB and known WAL/SHM files;
- real v1 and v2 historical run-manifest parsing, unknown-version
  rejection and run/task identity mismatch;
- no creating missing storage, no mutable `connect_db` invocation,
  rejected symlinked database and parent directories;
- strictly allowlisted evidence leaf path and no-follow ancestor handling;
- oversized file, malformed IDs and more than 512 events;
- no event-payload leakage and no private raw bytes in object repr;
- a live-WAL database with an open writer, asserting that the read
  causes **zero** DB/WAL/SHM byte changes or safely refuses without
  changing anything;
- refusal when WAL and SHM file presence is inconsistent.

Actual test results are **not yet known**. Failure of the live-WAL
non-mutation test is a blocker requiring an alternative supported
read strategy, not permission to weaken the requirement.

## 4. Local operator acceptance procedure

```bash
git fetch origin
git switch --track origin/feature/m6.0-slice-b1-readonly-source-snapshot
source .venv/bin/activate

python -m pytest -q tests/test_m60b1_readonly_snapshot.py \
  tests/test_m60b0_trace_format_policy.py \
  tests/test_m60a_trace_contract.py

python -m pytest -q
GIT_PAGER=cat git diff --check origin/main...HEAD

git rev-parse HEAD
python --version
```

Record focused/full-suite pass, skip/fail counts, exit codes and SHA.
GitHub Actions remains blocked by exhausted account quota, per the
operator's earlier statement; do not substitute that result for a
green hosted run.

## 5. Next gate (not implemented here)

**B1b** should parse each fixed historical JSON artifact using its
matching Pydantic schema, validate shared run/task/parent digests and
build a conservative `ExecutionTraceBundle v1` whose assessment list
is always empty. Only then, after complete side-effect and privacy
tests, expose a read-only JSON stdout CLI in a separate review.

Keep this PR **Draft** until local evidence and the SQLite/WAL safety
findings have been examined.
