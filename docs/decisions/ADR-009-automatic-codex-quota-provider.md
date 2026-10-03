# ADR-009: Automatic Codex Quota Provider

Status: Accepted

## Context

M2.0 intentionally bounded autonomous execution because quota observations were manual.
ProjectCTL already models quota as account-global state with project-local policy, but the
application layer still instantiated ManualQuotaProvider directly.

Codex App Server now exposes a supported read-only JSON-RPC method,
`account/rateLimits/read`, including rolling windows, reset times, multi-bucket snapshots,
and an explicit `ordinaryUsageAllowed` backend permission signal.

## Decision

M2.1 adds an account-global quota provider resolver and a Codex App Server provider.

### Supported source

ProjectCTL starts `codex app-server` over stdio, performs the required
`initialize` / `initialized` handshake, then calls `account/rateLimits/read`.

ProjectCTL does not scrape the TUI, read Codex credential files, or call private backend
endpoints.

### Window normalization

ProjectCTL identifies standard windows by `windowDurationMins`:

- 300 minutes -> five-hour
- 10080 minutes -> weekly

It never assumes primary means five-hour or secondary means weekly.

### Bucket selection

When `rateLimitsByLimitId.codex` exists it is preferred. The legacy `rateLimits`
view remains a supported fallback only when it is unambiguous. ProjectCTL does not infer
model applicability from `limitName` or opaque bucket IDs.

### Backend permission

`ordinaryUsageAllowed=false` is authoritative and places quota in critical mode even
when percentages appear to remain. Null means unknown and does not imply recovery.

### Failure policy

Provider/runtime failures produce an unknown stale snapshot in scheduling/status paths so
autonomous execution fails closed. Direct live probes and doctor checks still surface the
underlying provider error.

### Persistence

Successful official observations are stored in the existing account-global
`quota_observations` table. No quota state is moved into a repository.

Manual quota remains supported and selecting/storing a manual snapshot switches the
account provider back to manual.

### Scope boundary

M2.1 observes authoritative quota. It does not predict the token/time cost of a task,
map selectable models to model-specific quota buckets, or remove the explicit M2 task
bound.
