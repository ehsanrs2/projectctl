# ADR-037: Serialize Execution Authority Mutation With Run Admission

Status: Accepted

## Context

M5.1 introduced reviewed, additive mutation of the human-managed scope catalog. The adoption path
checked that no run was active while holding `context-scope-adoption.lock`. New run preparation
used a different `run-prepare.lock`.

Those locks did not exclude one another. A run could therefore become active after the adoption
path checked quiescence but before it wrote the new policy. That violated the intended contract:
ProjectCTL-controlled scope authority cannot change across the no-active-to-active run transition.

A second consistency gap existed in catalog snapshots: adoption read raw catalog bytes to compute a
digest, then called a loader that independently reread and parsed the file. Concurrent edits could
make the reviewed bytes and parsed catalog represent different snapshots.

Finally, stale lock reclamation used a check-then-unlink sequence without serializing reclaimers.
Two contenders recovering one dead-owner lock could race so that one removed a newly-created lock
belonging to the other contender.

## Decision

### One shared execution-authority gate

Introduce the project-level `execution-authority` gate, implemented through
`execution_authority_gate(project_root)`.

Both operations acquire this gate **before** their operation-specific lock:

```text
run preparation:
  execution-authority
    -> run-prepare
      -> preflight / plan
      -> durable run record
      -> task claim
      -> isolated worktree
      -> durable CLAIMED state
    -> release

scope adoption:
  execution-authority
    -> context-scope-adoption
      -> final catalog snapshot
      -> no-active-run check
      -> durable adoption request
      -> atomic policy write and validation
      -> durable receipt
    -> release
```

The gate is held through the full critical transition, not only around the initial check.

Run preparation acquires the gate before execution-readiness preflight. It keeps the gate until a
durable active run has reached `CLAIMED`, or until failure/recovery state has been durably recorded.
If a crash leaves a `PLANNED` or `PREPARING` run, that active record remains the authority for the
next adoption attempt to observe after the stale lock is safely reclaimed.

Scope adoption still checks for active runs while holding the gate. The check is required even with
the shared gate because a run admitted before adoption acquired the gate remains active after its
own gate is released.

### Lock order and contention behavior

The operation-specific order is fixed:

- `execution-authority → run-prepare`
- `execution-authority → context-scope-adoption`

Higher-level orchestration locks may be held by callers, but no path may acquire the authority gate
after taking either operation-specific lock.

Project locks are fail-fast rather than waiting locks. If another operation owns the authority gate,
the competing operation raises `ProjectLockError` and performs no planning or authority mutation.
The caller may retry after the in-flight operation completes. This avoids an implicit wait or
lease-stealing policy.

### Safe stale-lock reclamation

All stale lock removal is serialized by a separate OS advisory guard. On POSIX this uses
`flock`; on Windows it uses the platform byte-range lock. The advisory lock is automatically
released when its process exits, including a crash.

The stale owner is rechecked while the reclamation guard is held. A contender never unlinks a lock
file based on a stale observation made outside that guard. Existing fail-closed behavior for
malformed or foreign-host lock metadata remains.

### Single-read catalog snapshot

The catalog loader now has a byte-parser boundary:

```text
read catalog bytes once
  -> compute digest from those bytes
  -> parse and validate those same bytes
```

Adoption's `_catalog_state()` uses that parser directly. It no longer calls a path-based loader
that performs a second read. Post-write validation independently reads the new authoritative bytes
and verifies the reviewed digest/schema as before.

### No schema or policy-semantic change

M5.2a does not rename the catalog, change optional/required scope semantics, or introduce a database
migration. Those decisions belong to M5.2b.

Direct human edits remain outside ProjectCTL's process lock model. The existing clean-repository
preflight and stale/digest validation remain necessary for that boundary.

## Failure and recovery behavior

- Gate contention: fail closed with `ProjectLockError`; no planning/adoption mutation occurs.
- Adoption crashes before policy write: durable request plus exact before-state permits safe retry.
- Adoption crashes after policy write: exact reviewed after-state permits receipt reconstruction.
- Ambiguous catalog state: fail closed for manual audit.
- Run preparation crashes after durable run creation: active `PLANNED`/`PREPARING` state remains visible; adoption cannot infer quiescence from a released stale lock.
- Stale lock has malformed metadata or belongs to another host: do not reclaim automatically.
- Two processes attempt to reclaim one stale lock: reclamation is serialized; at most one can remove the observed stale lock, and only one contender can acquire the operation lock.

## Verification

Tests cover:

- adoption owning the shared gate prevents run preparation from entering preflight/planning;
- run-admission gate ownership prevents scope mutation, and the active-run check still blocks a retry;
- catalog digest and parsed model come from one byte read;
- stale-lock reclamation contenders cannot delete a newly-created lock;
- existing live-owner, dead-owner and ambiguous-metadata lock behavior remains fail-closed.

## Consequences

Positive:

- ProjectCTL-controlled scope mutation and new run admission now share one exclusion boundary.
- A stale scope snapshot cannot be constructed from different raw and parsed reads.
- Stale-lock recovery no longer has a competing-reclaimer check/unlink race.
- Existing scope policy and artifact schemas remain compatible.

Trade-offs:

- Scope adoption and run preparation fail fast under gate contention; callers must retry.
- The gate spans provider/task-claim and worktree preparation, intentionally favoring correctness over
  admission throughput.
- Human edits outside ProjectCTL remain governed by Git cleanliness and digest revalidation, not
  process locking.
