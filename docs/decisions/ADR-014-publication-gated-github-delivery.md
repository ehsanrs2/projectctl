# ADR-014: Publication-gated GitHub Delivery and Non-destructive Completion

Status: Accepted

## Context

M3.0b2 established a concurrency-safe GitHub claim/release protocol, but it deliberately stopped
before remote delivery and task completion.

The M1 integration lifecycle is local-first and fast-forward-only. A verified candidate may be
integrated into the local target branch while the corresponding remote branch still points at the
old base. Closing a remote team task at that point would report delivery before the verified code
is visible to the team.

A second concurrency problem exists in GitHub Issue completion. GitHub supports updating an
Issue's native `state` and `state_reason`, but ProjectCTL does not have a documented
compare-and-swap primitive for that mutation. Blindly PATCHing an Issue from open to closed could
overwrite a concurrent human decision such as `not_planned` or `duplicate`.

M3.0c therefore needs two independent guarantees:

1. verified code is durably observable on the configured remote target before task completion;
2. ProjectCTL completion does not overwrite concurrent human Issue state.

## Decision

### Delivery ordering

For task authorities whose delivery policy requires remote publication, ProjectCTL uses:

```text
verified candidate
    ↓
local fast-forward integration
    ↓
durable PublicationRequest
    ↓
exact-base remote publication
    ↓
remote candidate observation
    ↓
durable PublicationManifest
    ↓
additive canonical task completion
    ↓
durable completion event
    ↓
exact claim release
    ↓
PASSED
```

The run remains `INTEGRATING` until this delivery-finalization sequence completes.

No new RunStatus is introduced merely to expose internal publication sub-steps. The durable
publication artifacts and run events make those sub-steps observable and recoverable.

### Delivery policy

Task Authority resolution now also exposes a versioned `TaskDeliveryPolicy v1`.

Beads:

- publication required: no
- task completion evidence: local EvidenceManifest
- claim release after completion: no

GitHub:

- publication required: yes
- publication remote: `origin`
- task completion evidence: PublicationManifest
- exact remote claim released after completion: yes
- exact remote claim released after a durable human-decision block: yes

Application services consume the provider-neutral delivery policy rather than branching on
provider names.

### Publication request/evidence

Before remote mutation ProjectCTL writes `PublicationRequest v1` and anchors its digest in the
run event stream.

The request binds:

- run id
- task id
- provider/repository
- remote name
- target ref
- verified base commit
- verified candidate commit
- EvidenceManifest path/digest

After remote observation ProjectCTL writes `PublicationManifest v1` and anchors its digest in
the run event stream.

A successful publication manifest must prove the exact candidate commit is visible on the
configured remote target.

### Exact-base publication

GitHub publication uses an explicit expected-base Git lease:

```text
git push --force-with-lease=<target-ref>:<base-commit> \
  origin <candidate-commit>:<target-ref>
```

ProjectCTL first requires:

- the publication remote to represent the configured GitHub repository;
- both base and candidate commits to exist locally;
- the candidate to be a fast-forward descendant of the verified base.

The remote target is observed before and after the push.

Outcomes:

- remote already equals candidate → idempotent publication success;
- remote equals base → ProjectCTL may attempt exact-base publication;
- remote differs from both base and candidate → stale/diverged, fail closed;
- remote remains base after rejected push → publication failure, not fabricated success.

ProjectCTL does not bypass branch protection, repository rulesets, required pull requests, or
provider authorization.

Repositories whose policy rejects direct publication to the integration target are not silently
downgraded to another delivery mechanism. A future policy may explicitly support PR-based
publication, but that is outside M3.0c.

### Publication recovery

If a process crashes after writing PublicationRequest but before persisting PublicationManifest,
recovery observes the remote target:

- candidate present → reconstruct successful PublicationManifest;
- base still present → publication may be retried through the same exact-base request;
- any other SHA → fail closed as stale/diverged.

If a previously successful PublicationManifest exists, recovery re-observes the remote candidate
before proceeding. Durable local evidence alone is not treated as proof that the commit remains
published.

### Non-destructive GitHub completion

ProjectCTL does **not** automatically PATCH the native GitHub Issue state in M3.0c.

Instead, after successful publication it ensures and adds the reserved label:

```text
projectctl:completed
```

The mutation is additive: existing labels are preserved.

The GitHub task normalizer maps an open Issue carrying `projectctl:completed` to ProjectCTL
`DONE`.

Native GitHub closed state remains authoritative. In particular, a native
`state_reason=not_planned` remains `CANCELLED` even if a ProjectCTL completion label is also
present.

If an Issue is already closed as `completed`, ProjectCTL treats completion as idempotently
satisfied.

If an Issue is already closed for another reason, ProjectCTL refuses to reinterpret or overwrite
that human/external decision.

### Human-decision marker

For GitHub, `mark_needs_decision` is also additive and uses:

```text
projectctl:needs-decision
```

After the durable decision marker is written, ProjectCTL releases the exact GitHub claim so the
control-plane ownership ref cannot be stranded.

### Completion evidence

For local-only authorities, the TaskCompletionWriter continues to receive the EvidenceManifest
reference.

For publication-required authorities, the completion writer receives the PublicationManifest
reference/digest. This makes canonical task completion transitively dependent on the exact remote
publication proof.

The GitHub completion adapter independently revalidates that reference before mutating the Issue:
the manifest must exist inside the project, its digest must match, `published=true`, and
`remote_after` must equal the exact candidate commit. Application-level ordering is therefore not
the only publication gate.

### IntegrationManifest v2

`IntegrationManifest v1` remains exported for audit compatibility.

`IntegrationManifest v2` adds:

- publication_required
- publication_manifest
- publication_digest
- claim_released
- completed_at

A publication-required completed integration is invalid unless the publication manifest/digest is
present.

### Crash windows

The finalization sequence is intentionally idempotent.

Examples:

- crash after remote push → reconstruct publication by observation;
- crash after publication manifest → re-observe remote candidate;
- crash after task completion → durable `task.completion.observed` prevents destructive duplicate
  completion and allows claim release to continue;
- exact claim ownership changes after completion → ProjectCTL records a cleanup anomaly but does
  not rewrite the completed task into needs-decision or mutate the replacement owner's claim;
- transient/ambiguous claim release failure after completion → the run remains INTEGRATING so
  recovery can retry exact release without altering canonical task semantics;
- crash after exact claim release → idempotent release and final PASSED transition may continue.

Recovery never invents remote publication or task completion from local state alone.

## Consequences

Positive:

- GitHub task completion cannot precede remote-visible code;
- remote publication is bound to the exact verified candidate and evidence;
- stale remote targets are not overwritten;
- concurrent human Issue close reasons are not destroyed;
- publication/completion crash windows are recoverable;
- GitHub now implements the full task lifecycle required by the current execution gate;
- Beads keeps its existing local-only lifecycle.

Tradeoffs:

- GitHub `DONE` may be represented by a reserved ProjectCTL label while the native Issue remains
  open;
- teams that require native Issue closure can automate or perform that separately without making
  ProjectCTL overwrite human close semantics;
- repositories requiring pull-request-only delivery remain blocked by the direct-publication
  policy in M3.0c;
- publication requires Git transport write access and is subject to repository rules.

## Scope boundary

M3.0c does not:

- create or merge pull requests;
- bypass branch protections/rulesets;
- infer GitHub dependency/sub-issue relationships;
- replace GitHub native workflow policy;
- introduce parallel/multi-run execution.

M3.1 owns richer GitHub team semantics such as dependencies, sub-issues, and project metadata.
