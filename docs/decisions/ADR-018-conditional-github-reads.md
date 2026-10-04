# ADR-018: Conditional GitHub Reads and Validator Revalidation

Status: Accepted

## Context

M3.1c1 introduced a versioned, integrity-checked derived cache for GitHub REST
representations. The cache records `ETag`, `Last-Modified`, `observed_at` and
`validated_at`, but M3.1c1 deliberately did not send conditional requests.

ProjectCTL now needs to use those validators without weakening the authority boundary:

- GitHub must remain authoritative.
- Cached payloads must not become an outage fallback.
- A `304 Not Modified` must advance validation freshness without pretending the body was fetched
  again.
- A normal `200 OK` must replace the derived payload and validator provenance.
- Authentication remains owned by GitHub CLI.
- HTTP response status and validators must be observed explicitly rather than inferred from an
  empty body.
- Multi-page reads must not be incorrectly validated by an ETag belonging to only one HTTP
  response/page.

GitHub documents conditional GETs using `If-None-Match` or `If-Modified-Since`. An authorized
`304 Not Modified` response does not consume the primary REST rate limit. GitHub CLI exposes
response status and headers with `gh api --include`.

## Decision

M3.1c2 adds conditional revalidation for single-response GitHub GET representations.

### Response envelope

ProjectCTL invokes authenticated GitHub GETs through the existing `gh api` boundary and adds
`--include` for conditional-cacheable reads.

The client parses:

- HTTP status code
- response headers
- JSON body, when present

A 304 is identified from the status line. An empty body is never interpreted as an empty task
representation.

### Validator precedence

For a valid matching cache entry:

1. use `If-None-Match` when an ETag exists;
2. otherwise use `If-Modified-Since` when Last-Modified exists;
3. otherwise perform an unconditional GET.

ETag therefore has explicit precedence when both validators are available.

Cached validator values containing CR/LF are rejected before they can become request headers.

### 304 Not Modified

A 304 is accepted only when ProjectCTL actually sent a validator from a matching valid cache entry.

On 304:

- cached payload remains unchanged
- payload digest remains unchanged
- `observed_at` remains unchanged
- `validated_at` advances to the local observation time
- response validators may update when GitHub returns them
- the cache integrity digest is recomputed

A 304 without a matching cached validator fails closed.

### 200 OK

On a successful 200:

- the returned JSON body becomes the new derived payload
- `observed_at` and `validated_at` are set from the new observation
- returned ETag / Last-Modified values replace previous validator provenance
- payload and integrity digests are recomputed atomically by the existing M3.1c1 cache store

### Provider failures

ProjectCTL never converts provider or transport failure into a cache hit.

This includes:

- authentication/authorization failures
- rate-limit errors
- 4xx/5xx responses
- GitHub CLI execution failure
- timeout/transport failure
- malformed response envelopes

If a valid cached payload exists and GitHub returns an error, the operation still fails.

This preserves GitHub as the authority and avoids silently scheduling against stale remote state.

### Pagination boundary

M3.1c2 does not attach one validator to a `gh api --paginate --slurp` aggregate.

An HTTP validator belongs to one concrete response representation/page. Treating the first page's
ETag as proof for a multi-page aggregate could validate stale data from another page.

Therefore:

- single-response reads such as repository and individual Issue GETs use conditional revalidation
- existing paginated Issue-list and relationship reads remain unconditional in M3.1c2
- page-aware cache-backed snapshot assembly is deferred to M3.1c3

M3.1c3 must preserve page identity or another equally strong remote-validation proof before it
uses cache freshness to reduce snapshot fan-out.

### Telemetry

Each conditional-cacheable read emits observational `github.cache.read` telemetry when the local
telemetry database exists.

Outcomes include:

- `miss_200`
- `refreshed_200`
- `revalidated_304`
- `provider_error`

M3.1c2 intentionally has no `fresh_hit` outcome because it never serves a locally fresh entry
without contacting GitHub. That behavior belongs to M3.1c3 after an explicit freshness policy is
bound to snapshot assembly.

Telemetry remains non-authoritative.

## Consequences

Positive:

- GitHub validators are now used through the existing authenticated CLI boundary
- 304 responses can revalidate cached representations without replacing payload bytes
- provider outages cannot silently turn stale cache data into task authority
- ETag and Last-Modified semantics are explicit and testable
- empty 304 bodies cannot be confused with empty Issue results
- pagination remains fail-safe rather than applying a validator beyond its proof scope

Tradeoffs:

- M3.1c2 does not yet reduce the number of HTTP calls required to build a full task snapshot
- paginated Issue and relationship reads still transfer their normal payloads
- `gh api --include` response-envelope parsing becomes part of the adapter contract
- cache-backed local fresh hits remain deferred

## Follow-up

### M3.1c3 — Cache-backed Snapshot Assembly & Scale

M3.1c3 should define and test:

- page-aware representation identity and revalidation for paginated reads
- explicit task-store freshness policy
- when a remotely validated entry may be reused without another immediate request
- deterministic invalidation
- bounded relation fan-out
- repository-scale request-count and latency assertions
- telemetry for true fresh hits and aggregate snapshot cache behavior

GitHub remains authoritative and the cache remains disposable derived state.

## References

- GitHub REST best practices: conditional requests and 304 behavior
- GitHub CLI `gh api`: `--include` and custom request headers
