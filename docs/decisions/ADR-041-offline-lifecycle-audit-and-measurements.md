# ADR-041 — Research lifecycle observations and optional measurements

Status: Feature-port preparation, offline qualification only; PR pending.
No merge into main or live experiment approval.

Provenance: corrected research implementation `4bf59132099cb798e0ccf5c49d936197aa220e44`.
This selective port is based on frozen main `4b3ce59f9f2f6daa9bb5b7e4dd77cf3eb49e12b4`;
see `docs/architecture/POST_D2_FEATURE_PORT.md` for scope and compatibility gates.

## Decision

Add `projectctl run audit RUN --project PATH --json` as a derived, read-only
inspection interface. It reuses the bounded private source reader, historical
artifact validators, canonical model digest algorithm, Run statuses, checkpoint
events, and the WorktreeManager path contract. It never constructs a mutable
RunStore or WorktreeManager, contacts a task/quota provider, or invokes lifecycle
dispatch or recovery. RunStore remains the lifecycle authority.

The report is versioned independently of ExecutionTraceBundle. It explicitly
reports independent source observations, not an atomic DB/filesystem snapshot,
verification assessment, readiness certificate, or authenticated event history.
ADR-039/040 consistency and Seal gates remain in force. In particular, the
existing reader's live-WAL rejection remains unchanged; a WAL source yields
unknown status and an inspection-only handoff. Do not promote detached WAL
probe readability into authoritative state.

The handoff is a preview, not a dispatcher or consent token. It may suggest an
existing stage for a separate owner decision, but permits inspection only and
never authorizes retry. Missing evidence, leases, inconsistent identities or
digests, target/candidate drift, and uncertain start/resume attempts suppress the
suggestion. A checkpoint remains a RUNNING Run with checkpoint evidence.

Existing stage commands gain optional `--measurements PATH` telemetry capture.
Without that option they retain their existing behavior and exit semantics.
Optional monotonic measurements use execution boundaries already present in the
application. WorkerResult v1 and all historical evidence stay unchanged. SDK
usage retains the pinned API's `last` and `total` scopes without cross-operation
aggregation or adding cached/reasoning subsets.

Telemetry is exclusively created before the existing command and contains no
prompt, task text, thread ID, exception message or credentials. Its pending,
returned, or interrupted outcome is observational only. It is neither the
durable exclusive dispatch intent required of a future dispatcher nor evidence
that an interrupted action can be retried. No new dispatcher is implemented.

## Consequences and limits

- Existing scheduling, quota, claim, ownership, verification, integration and
  recovery policies are unchanged.
- Live WAL observation remains unsupported. Inspection explicitly fails closed
  rather than acquiring source SQLite connections that may create SHM/WAL files.
- Repeat reads detect ordinary changes but do not establish atomicity or an
  authenticated baseline. Unknown historical dispatch and log integrity stay
  unknown; missing stdout never proves no dispatch.
- RunStore and artifact observations cannot prove current task-provider state.
  The report does not contact Beads and does not infer task completion from it.
- Measurement file inspection verifies shape, identity and clock provenance,
  not authenticity against a malicious writer. It never grants action authority.
- Live stage execution, any future retry/recovery decision, production
  promotion, and D3 require separate owner decisions.
