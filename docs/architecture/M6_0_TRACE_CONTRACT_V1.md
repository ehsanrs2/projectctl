# M6.0 Slice A — Trace v1 Contract, Source Inventory & Privacy Review

**Status: Proposed for ADR-039 review — no collector/exporter exists.**  
**Implementation baseline:** `main@2f3cf5d18bae47544b7e99ed9bff954c005c0594`  
**New proposed public schema:** `execution-trace-bundle.v1.schema.json`  
**Ownership:** derived, read-only, non-authoritative; `docs/PROJECT_STATE.yaml` is still the active-goal authority.

## 1. Model and trust boundaries

`projectctl/schemas/trace.py` defines **output-only** `ExecutionTraceBundle v1`,
`TraceSourceDescriptor`, `TraceEventSummary`, `TraceFinding` and
`TraceAssessment`. The public registry adds the v1 JSON Schema. There is
**no collector, export CLI, database writer, provider adapter or scheduler
consumer** in Slice A.

The model explicitly allows:

| Field | Origin/semantics | Restriction |
| --- | --- | --- |
| `project_id`, `run_id` | Source identity only, not operator/user identity | Short ASCII identifier, no directory separators or emails |
| `observed_run_status` | `RunStore`-reported lifecycle observation | Cannot exist without a present run record; **not** proof of verified delivery |
| `completeness` | Structural status `complete/incomplete/inconsistent` | `complete` needs run record + run manifest, no findings/missing sources; a passed run additionally needs verification+evidence sources |
| `sources[]` | Fixed whitelist of source kinds, validation state, schema version, byte SHA-256 and typed reason | No filenames, arbitrary JSON or raw bytes; source kinds unique and sorted |
| `events[]` | Event sequence, UTC timestamp and allowlisted category | No original event type, actor, payload, exceptions or logs |
| `findings[]` | Stable typed reason code and optional source kind | No free-form error strings, path names or secret-bearing context |
| `assessments[]` | Optional `supported/unavailable/indeterminate` support label | `supported` needs present independent anchors; **model validation alone does not prove linkage** |

All nested models are `extra="forbid"`. Identifiers are not copied from
potentially sensitive arbitrary Git branch names or provider response IDs.

**Critical semantic constraint:** `TraceSourceDescriptor.validation_state ==
"present"` and a structurally valid `TraceAssessment.support == "supported"`
are **data-shape claims only**. Slice B/C must prove source digests,
run/task identity, historical schema interpretation and cross-artifact
lineage before emitting either. A real worker-reported success can never
substitute for independent Verification + Evidence.

## 2. Existing sources and bounded locators

Inventory verified against current files; paths below are *internal source
candidates*, **not fields exported to the bundle**.

| Source kind | Existing location / reader | Versions / constraints |
| --- | --- | --- |
| `run_record` | `RunStore.get(run_id)` at `projectctl/storage/runs.py` | SQLite row; not itself a verification verdict |
| `run_event_stream` | `RunStore.events(run_id)` | SQLite events include payloads; **never export payloads** |
| `run_manifest` | `RunStore.manifest(run_id)` | Current reader is v2; v1 historical model exists but has different fields |
| `execution_input_manifest` | `.projectctl/runs/<run-id>/execution-input-manifest.json` | v1/v2 strict parser in `projectctl/schemas/execution_input.py` |
| `claim_transition_evidence` | Execution-input/claim persistence in `projectctl/application/execution_inputs.py` | v1 only; exact file location must be confirmed before enabling collector |
| `context_manifest` | `.projectctl/runs/<run-id>/context-manifest.json` | v1/v2/v3 versioned models |
| `worker_result` | Durable execution artifact store, location to be confirmed | v1; raw message/output is forbidden by default |
| `verification_manifest` | `.projectctl/runs/<run-id>/verification-manifest.json` | v1/v2; independently parse, validate base and identity |
| `evidence_manifest` | `.projectctl/runs/<run-id>/evidence-manifest.json` | v1/v2; overall_pass must not be trusted before digest lineage check |
| `integration_manifest` | `.projectctl/runs/<run-id>/integration-manifest.json` | v1/v2/v3; a local integration is distinct from external publication |
| `publication_manifest` | Delivery integration artifacts, location to be confirmed | v1, references authenticated provider evidence; **no raw responses** |
| `review_receipt` | Review-required delivery artifacts, location to be confirmed | v1; never treat a pending review as completed delivery |

Source collection for each kind requires an explicit allowlisted locator.
**Unknown paths are not discovered with recursive globbing.** Before Slice B,
validate source paths relative to a known project root and a known run ID,
reject symlinks and escaped paths, and implement a consistent read snapshot.

### Schema/byte lineage vocabulary

- **Content SHA-256:** hash of the exact *single-read* source byte snapshot.
  For SQLite rows/events, define a canonical serialization and transaction
  consistency policy before calculating the hash.
- **Semantic digest:** existing artifact-specific ProjectCTL contract;
  do not equate it with raw SHA-256 or recompute it using a newer schema.
- **Git commit ID:** source revision or verified integration base; not the
  same thing as content or semantic digest.
- **Provider assertion:** externally reported status, never automatically
  elevated to verified code outcome.
- **Unsupported historical schema:** a source with an unknown schema version
  cannot be marked `present`. Keep kind/version and typed `unsupported_schema`
  reason; never coerce an unknown version into a current Pydantic model. The
  known-version table in `projectctl/schemas/trace.py` is an *inventory*, not
  an implicit migration or guarantee that each old reader has been wired.

## 3. Snapshot and determinism proposal (not yet implemented)

1. Acquire a read-only, bounded SQLite snapshot for `RunStore` row/events.
2. Capture only required artifact bytes by whitelist; compute SHA-256 from
   those same bytes before parsing. Do not read unbounded directories or
   allow symlink redirection.
3. Revalidate the observed run status/manifest identity against the starting
   snapshot (or label the result `inconsistent` on change). Do not hold
   execution-authority locks or silently retry forever.
4. Order sources by source-kind name, events by SQLite sequence ID,
   findings by (reason code, kind) and assessments by kind. Normalize event
   timestamps to UTC; **omit export wall-clock timestamp**.
5. Serialize deterministic UTF-8 JSON with stable key ordering/separators.
   A hypothetical future export digest identifies only the derived bundle,
   **never** a new ExecutionInput/EvidenceManifest authority.
6. Source identity checks precede assessment generation. On a race or
   corrupt evidence, export a safe typed finding or fail without side effects.

**Open design gate:** exact read-only SQLite transaction and filesystem
snapshot consistency are not solved by the Pydantic contract. The existence
of `RunStore.manifest` does not establish historical v1 reader parity.

## 4. Privacy threat model and disclosure allowlist

| Threat | Default decision | Acceptance test |
| --- | --- | --- |
| Prompt, secrets or provider output in nested JSON | No raw fields / no `dict[str, Any]` pass-through | Reject unexpected top-level/nested keys |
| Raw stdout/stderr or tool logs in event payload | Export *category* and sequence only | Reject payload, actor, raw event type and log field |
| Host-specific paths, worker thread, lease owner, user email | Do not copy; source descriptors contain no file path or actor field | Reject path-like identifiers, email-like strings and extra fields |
| Cross-project reference or symlink/traversal | Do not read: mark typed reason or fail closed | Slice B adversarial filesystem fixtures |
| Unsupported/edited/corrupt source | Record `unsupported/invalid/stale` with typed reason, no passing assessment | Invalid/missing/unsupported tests |
| Worker self-reported PASS | Observed status only; independent verification lineage required | Verify worker-only assessment cannot be supported |
| Inconsistent multi-artifact read | Emit `inconsistent_snapshot` finding, no false complete trace | Slice B concurrent modification injection |
| Exfiltration through network export | No network/export/upload code in initial milestone | Source dependency/API audit and no-action tests |
| Revealing project/run IDs or digest correlations | Bounded IDs and SHA are still potentially identifying | Operator must approve whether pseudonymization is required |
| Output-file symlink swap | CLI is absent in A; future explicit output requires safe atomic no-clobber policy | Slice B destination-security tests |

Privacy guarantee is **bounded to permitted fields** in v1. Identifier text
or digests can still reveal information through correlation; no claim of
cryptographic anonymization is made. In particular, **do not** put raw
exception messages into the typed reason-code fields.

## 5. Executable Slice A test matrix

`tests/test_m60a_trace_contract.py` covers:

- public schema export; strict `v1` kind/version;
- JSON roundtrip with deterministic field ordering;
- extra top-level and nested private fields rejected;
- digest and source-version constraints; missing and unsupported evidence;
- reject a complete trace when required source anchors or consistency fail;
- reject claimed run status without a RunStore source;
- sorted unique sources, findings, assessments and event records;
- worker-result-only attempts to claim independent verification;
- absent assessments in an observed passing RunStore status;
- traversal/email-like identifier strings rejected;
- timezone normalization and equal deterministic JSON output.

### Before merge

```bash
source .venv/bin/activate
uv pip install -e ".[dev,codex]"
python -m pytest -q tests/test_m60a_trace_contract.py tests/test_schema_export.py
python -m pytest -q
git diff --check origin/main...HEAD
```

Existing Codex SDK tests may be unavailable in environments without the
optional dependency; the non-skippable contract is separately checkable with
`bash scripts/m52b-codex-sdk-contract-check.sh`.

**Evidence status:** tests authored and code reviewed in GitHub; NOT run in a
private working checkout from this session. The owner's GitHub Actions quota
is reported exhausted. Keep the Slice A PR Draft until tests have actual
operator-run evidence.

## 6. Acceptance decisions before Slice B

The architecture reviewer must explicitly resolve:

1. Whether exported project/run IDs and raw content digests are acceptable
   under the default privacy level or need pseudonymization.
2. The exact per-kind source locator, historical parser and source-version
   compatibility. No guessing missing file paths.
3. The bounded SQLite snapshot + stable file-read policy under concurrent
   writes and interrupted export.
4. Whether support-level names need strengthening to avoid mistaking
   structural presence for validated lineage.
5. Whether the conservative initial output must omit assessments entirely
   until Slice C; the v1 model permits an empty list.

ADR-039 remains **Proposed** until these privacy, provenance and concurrency
decisions are accepted. No exporter will be enabled by this design slice.
