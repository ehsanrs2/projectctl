# ADR-019: Cache-backed GitHub Snapshot Assembly and Freshness Safety

Status: Accepted

## Context

M3.1c1 defined an integrity-checked derived cache and M3.1c2 added authenticated conditional
revalidation for single-response GitHub GETs.

The remaining scale problem is snapshot fan-out. A GitHub task snapshot requires:

- the repository Issue collection
- blocked-by relationships for each Issue
- sub-issue relationships for each Issue

Repeated status, scheduling and autonomous-loop evaluations can therefore repeat many GitHub REST
requests even when the remotely validated representations have not changed.

M3.1c3 must reduce that fan-out without turning local cache state into task authority or weakening
execution-time correctness.

Two constraints are especially important:

1. an HTTP validator proves one concrete response representation/page, not an arbitrary
   `--paginate --slurp` aggregate;
2. bounded stale reads may be acceptable for ordinary status/scheduling, but execution preflight
   must not allow a just-added dependency or lifecycle change to hide behind a local freshness
   window.

## Decision

### ProjectConfig v3 freshness policy

Project config is additively versioned to v3.

Task-store configuration adds:

```yaml
task_store:
  provider: github
  repository: owner/repository
  cache_max_age_seconds: 30
```

The value is bounded to 0..3600 seconds.

- `0` disables local fresh-cache reuse and forces remote revalidation.
- a positive value permits reuse only when the integrity-checked cache entry's `validated_at`
  age is within that explicit bound.

ProjectConfig v1 and v2 remain readable and are upgraded in memory to v3 with a 30-second default.
Existing config files are not rewritten automatically.

### Page-aware representation identity

ProjectCTL no longer treats a multi-page GitHub collection as one cacheable aggregate.

Instead it reads concrete pages independently:

```text
repos/owner/repo/issues?state=all&per_page=100
repos/owner/repo/issues?state=all&per_page=100&page=2
...
```

The same rule applies to Issue relationship collections.

Each page is therefore a separate GitHubCacheRequest identity with its own:

- request fingerprint
- payload digest
- observed_at / validated_at
- ETag / Last-Modified
- integrity digest

The first page may omit `page=1` because GitHub defines that endpoint as the first page; later
pages include the explicit page query parameter.

### Fresh local reuse

Before a cacheable GET, ProjectCTL evaluates the matching cache entry against the configured
maximum age.

If the entry is valid and fresh:

- the payload may be reused locally
- no GitHub request is made
- telemetry records `fresh_hit`

If the entry is stale or absent:

- the M3.1c2 conditional GET path is used
- ETag is preferred over Last-Modified
- 304 advances validation freshness
- 200 replaces the payload/validator provenance
- provider/API/transport failure remains an error

A stale entry is never used after a failed revalidation attempt.

### Mutation invalidation

A successful Issue lifecycle-label mutation can invalidate multiple cached semantic
representations:

- the individual Issue representation
- one unknown Issue-list page containing that Issue
- scheduling metadata derived from the changed label

Without a durable Issue-to-page index, exact-page invalidation would be incomplete.

Therefore a successful task Issue label mutation invalidates all derived GitHub cache entries for
the configured repository before the post-mutation reread.

This is conservative but deterministic and safe. The cache is disposable derived state.

### Execution safety boundary

Ordinary task listing and scheduling may use the configured bounded freshness window.

Execution preflight is stricter.

Before task claim and again after distributed claim acquisition, ProjectCTL captures the task
snapshot with a provider-neutral read-cache max-age override of zero.

For GitHub this means every required cached page is remotely revalidated (or replaced) before the
execution context is accepted.

This preserves the existing stale-context invariant:

- a newly added dependency
- a lifecycle/status change
- changed scheduling metadata

cannot be hidden by the normal local fresh-cache window at the moment execution begins.

The application layer does not branch on GitHub; it supplies a provider-neutral cache-age override
to the Task Authority resolver.

### Telemetry and scale evidence

M3.1c3 extends the existing observational `github.cache.read` outcome set with `fresh_hit`.

Scale tests assert request-count behavior, not only payload equality.

For a snapshot containing N Issues on one Issue-list page, the initial correctness-first read still
requires approximately:

```text
1 Issue page + N blocked-by pages + N sub-issue pages
```

Within the freshness window, an unchanged repeated snapshot reuses those independently validated
representations and requires zero corresponding remote GETs.

This milestone optimizes repeated snapshot evaluations. It does not claim that the first cold
snapshot removes the native REST relationship fan-out.

## Consequences

Positive:

- repeated GitHub task/status/scheduler evaluations no longer repeat unchanged relationship GETs
- pagination validators remain correctly scoped to individual HTTP representations
- freshness policy is explicit, versioned and inspectable
- execution safety remains stronger than ordinary read freshness
- mutation invalidation cannot leave a completed/decision label hidden behind cached Issue data
- GitHub remains authoritative and cache deletion changes performance only

Tradeoffs:

- the first cold snapshot still performs per-Issue relationship reads
- repository-wide invalidation after task mutation is conservative
- ProjectConfig advances to v3
- ordinary status/scheduling can be bounded-stale for the explicitly configured window
- very large repositories still need future batching/provider-specific optimization if cold-start
  relationship fan-out becomes too expensive

## Rejected alternatives

### Cache the full `--paginate --slurp` output under one ETag

Rejected because one response/page validator cannot prove the freshness of every page in the
aggregate.

### Use a fresh cache entry during execution preflight

Rejected because it could hide a newly added dependency or lifecycle change during the safety
boundary where execution context must be revalidated.

### Fall back to stale cache when GitHub revalidation fails

Rejected because that would make derived operational state act as a second task authority.

### Invalidate only the individual Issue after label mutation

Rejected because the same semantic change may still be present in an unknown cached Issue-list
page.

## Follow-up

M3.2 may add additional task authorities through the existing provider-neutral ports.

Future GitHub scale work may consider provider-supported batching or graph queries for cold-start
relationship discovery, but only with explicit authority, pagination and concurrency semantics.
