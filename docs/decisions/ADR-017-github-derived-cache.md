# ADR-017: GitHub Derived Cache and Freshness Contract

Status: Accepted

## Context

M3.1a introduced structured GitHub dependency and sub-issue reads. Building a task snapshot now
requires the Issue list plus per-Issue relation reads. This is correct but creates API fan-out.

Before adding conditional requests or reusing cached payloads, ProjectCTL needs a precise contract
for:

- what a cached representation identifies
- what proves its integrity
- what "fresh" means
- how remote revalidation differs from initial observation
- how cache data remains derived rather than authoritative
- how cache corruption and path safety are handled

Using an unversioned ad-hoc cache would create a second, poorly defined source of truth.

## Decision

M3.1c1 introduces a versioned local derived cache under:

```text
.projectctl/cache/github/v1/<owner>/<repository>/<request-fingerprint>.json
```

The directory is operational state and remains ignored by Git.

GitHub remains the task authority. Deleting the entire cache may reduce performance but must not
change task semantics.

### Request identity

`GitHubCacheRequest v1` binds the exact REST representation:

- repository
- hostname
- HTTP method
- endpoint including stable query parameters
- GitHub REST API version
- Accept media type
- pagination mode
- slurp/aggregation mode

Only repository-scoped GET endpoints are accepted.

The request fingerprint is ProjectCTL's canonical JSON digest of that complete request identity.

Changing API version, media type, endpoint, repository, or pagination semantics therefore produces
a different cache key rather than reusing an incompatible representation.

### GitHub REST representation

ProjectCTL now explicitly pins GitHub GET requests to:

```text
Accept: application/vnd.github+json
X-GitHub-Api-Version: 2026-03-10
```

GitHub documents the REST API as versioned and recommends explicitly sending
`X-GitHub-Api-Version`. This also makes conditional-cache representation identity deterministic.

### Cache entry

`GitHubCacheEntry v1` stores:

- full GitHubCacheRequest
- request fingerprint
- JSON payload
- payload digest
- cache integrity digest
- observed_at
- validated_at
- ETag, when returned
- Last-Modified, when returned

`observed_at` is when the payload bytes/JSON representation were obtained from GitHub.

`validated_at` is the latest time the same representation was proven current by GitHub. In
M3.1c2 a successful `304 Not Modified` may advance `validated_at` without changing
`observed_at` or the payload.

### Integrity

Payload integrity and freshness provenance are both tamper-evident.

The payload digest binds the cached JSON.

A second integrity digest binds:

- request fingerprint
- payload digest
- observed_at
- validated_at
- ETag
- Last-Modified

Therefore changing a timestamp or validator cannot make stale data appear fresh without detection.

Corrupt or mismatched entries are never accepted as valid task data.

### Freshness

Freshness is evaluated from `validated_at`, not merely file modification time.

A caller supplies an explicit maximum age policy:

```text
age = now - validated_at

age <= max_age  -> fresh
age >  max_age  -> stale
```

A future validation timestamp fails closed instead of making an entry effectively immortal.

M3.1c1 does not define one global hard-coded TTL. M3.1c2/M3.1c3 may bind freshness policy to
runtime/task-store configuration after conditional-request behavior is implemented and measured.

### Validators

ETag and Last-Modified are optional because endpoint behavior may differ.

The cache contract preserves both.

M3.1c1 does not yet send conditional headers or serve task snapshots from cache. It only provides
the durable contract/store required for those later steps.

### Revalidation

The cache store exposes an explicit revalidation operation.

Revalidation:

- preserves the payload and payload digest
- preserves observed_at
- advances validated_at
- may update ETag/Last-Modified
- recomputes the cache integrity digest

This is the intended persistence path for a later remote `304 Not Modified`.

### Storage safety

Entries are:

- stored only beneath the project-local cache directory
- repository/request keyed deterministically
- written through a temporary file followed by atomic replace
- rejected if path resolution escapes the project root
- rejected when a cache entry path is a symlink

The cache is derived state, so no project-state SQLite schema migration is required.

### Invalidation

ProjectCTL provides exact-request and repository-level invalidation.

Invalidation removes derived artifacts only. It does not mutate GitHub, task state, Run state,
evidence, or Project State.

### Public contracts

M3.1c1 exports:

- `github-cache-request.v1.schema.json`
- `github-cache-entry.v1.schema.json`

These contracts are intentionally versioned before cache-backed behavior is introduced.

## Consequences

Positive:

- later conditional requests have a stable provenance contract
- stale/fresh decisions are inspectable rather than inferred from filesystem timestamps
- validators and payloads cannot be silently mixed across representations
- cache corruption cannot silently change scheduling state
- no SQLite migration is needed for disposable derived state
- GitHub remains the sole remote task authority

Tradeoffs:

- M3.1c1 alone does not reduce API call count
- additional JSON artifacts exist under .projectctl/cache
- callers must provide an explicit freshness window until policy is finalized
- cache corruption currently surfaces as an error to the cache consumer; later synchronization
  code may safely invalidate and refetch from GitHub

## Follow-up

### M3.1c2 — Conditional GitHub Reads

Use the cache validators to send authenticated conditional GETs:

- If-None-Match when ETag is available
- If-Modified-Since when appropriate
- 304 advances validated_at without replacing the payload
- 200 replaces the payload and validators
- provider/API errors never become synthetic 304/cache hits

### M3.1c3 — Cache-backed Snapshot Assembly & Scale

Use validated cache entries during GitHub snapshot construction with:

- explicit freshness policy
- deterministic invalidation
- cache hit/miss/revalidation telemetry
- bounded API fan-out
- scale tests on larger Issue sets

GitHub remains authoritative throughout.
