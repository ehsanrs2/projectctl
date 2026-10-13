# M6.0 Slice B1b — Versioned Evidence Inspection and Conservative Trace

**Status: Draft / untested — no Collector, CLI or live-WAL support**

Baseline: `main@7d43dfa1210078783db8f7c7177bff4e9923bff4` (PR #57 merged).
Governing architecture: ADR-039 (Accepted), Slice B1a Reader (merged).

## Scope

`projectctl/trace/validate.py` contains only **pure transformations**
over already captured source bytes. It never opens a database or file,
runs a worker, mutates a task, accesses a network or registers a CLI.

The new `inspect_artifact_snapshot` operation:

- chooses exact historical Pydantic models (v1, v2, v3 only where shipped)
  for nine fixed evidence source kinds;
- rejects unknown schema versions as `unsupported`, rather than coercing
  them to current schemas;
- validates source SHA-256 against the **same captured raw bytes**;
- parses JSON with duplicate-field rejection and no NaN/Infinity literals;
- rejects malformed data and unrecognized schema kinds with typed, safe
  error codes rather than raw parser/Pydantic messages;
- compares original unnormalized task/run/project identity fields against
  the selected scope, preventing Pydantic string trimming from authorizing
  whitespace-altered identities;
- returns only allowlisted public `TraceSourceDescriptor` metadata.
  It does not serialize the source's raw prompts, paths, errors or payload.

Not every historical artifact includes a `run_id`; ContextManifest and
ExecutionInputManifest carry task-level identifiers. Their structural
validation must **never** be mistaken for proven run binding. Existing
semantic parent digests, execution policy, provider assertions and
independent verification checks are **not** inferred here.

The new `conservative_trace_from_snapshots` operation:

- combines one previously validated private `TraceDbSnapshot` with an
  explicit mapping of validated source descriptors;
- adds only the known run row, run manifest and bounded event stream;
- orders public sources/findings deterministically and emits no raw file
  paths, stdout/stderr, provider details, worker claims or task IDs;
- **always** emits `assessments=[]` and a non-complete
  `incomplete|inconsistent` bundle, including when RunStore reports
  `passed`. No `supported` verification conclusion is permitted;
- preserves typed `missing`, `invalid`, `stale` or `unsupported`
  source observations without inventing success.

## Explicitly unresolved

1. **Live WAL:** B1a deliberately rejects WAL before connecting. This PR
   does not bypass that guard; normal WAL-enabled RunStore remains outside
   the supported real-read path.
2. **Cross-store consistency:** separate file reads and the SQLite snapshot
   have not yet been atomically bound or revalidated as a coherent set.
3. **Parent digests and independent authority:** parser success does not
   prove `ExecutionInput` -> claim -> Worker -> Verification -> Evidence ->
   Integration / Delivery semantic digest lineage.
4. **Project identity:** the pure function accepts an explicit project ID.
   A future Collector must establish it from safe, validated project
   authority; it cannot trust a caller-provided ID alone.
5. **Phase-specific optionality:** only the caller chooses which artifacts
   to inspect. Missing future-phase files must not be treated as failed
   verification or completed delivery.
6. **Public CLI:** no `projectctl trace export`, stdout reading or file
   destination functionality is enabled. No new release or version bump.

## Local acceptance tests

`tests/test_m60b1b_artifact_validation.py` exercises real v1/v2
historical ContextManifest models, source byte SHA, duplicate/invalid JSON,
unknown versions, identity mismatch and normalization, cross-project input,
missing evidence, unsafe source-kind bindings, deterministic conservative
bundle JSON, and no `supported` claims.

Run from an `uv`-managed checkout:

```bash
git fetch origin
git switch --track origin/feature/m6.0-b1b-versioned-artifact-validation
source .venv/bin/activate

python -m pytest -q \
  tests/test_m60b1b_artifact_validation.py \
  tests/test_m60b1_readonly_snapshot.py \
  tests/test_m60b0_trace_format_policy.py \
  tests/test_m60a_trace_contract.py

python -m pytest -q
GIT_PAGER=cat git diff --check origin/main...HEAD

git rev-parse HEAD
python --version
```

**Evidence status:** test code committed but no live checkout test
results for this PR have been supplied. GitHub Actions remains quota-blocked
per the repository owner's statement.

**Merge gate:** keep Draft until local tests and the conservative
privacy/identity semantics are independently reviewed. Safe live WAL,
atomic cross-source revalidation and Collector + CLI remain separate
work to be accepted before any operational exporter.
