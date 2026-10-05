# ADR-023: Separate Task Authority, Code Transport, and Execution Ownership

Status: Accepted

## Context

M3.0b2 introduced a concurrency-safe remote claim for GitHub Issues by storing exact ownership in
a reserved Git branch ref.

That implementation proved an important primitive, but its original packaging conflated three
different concepts:

1. **Task Authority** — where canonical task state lives;
2. **Code Transport** — whether source code is local-only or attached to a network Git remote;
3. **Execution Ownership** — how ProjectCTL proves that one run owns work on one task.

The coupling became visible when Linear was added.

A Linear team may manage tasks while source code is:

- local Git with no network remote;
- hosted on GitHub;
- hosted on GitLab;
- hosted on a compatible self-managed Git server.

Likewise, a GitHub Issues task authority does not logically require source code to be hosted on the
same GitHub repository forever.

The existing `RemoteRefLease` implementation itself is based on Git commands and exact ref
leases. The primitive is not intrinsically a GitHub API operation.

ProjectCTL is local-first and Git-native. "Local-only" therefore means a local Git repository with
no network Git remote. Supporting a completely non-Git execution workspace would require replacing
worktrees, commit-bound evidence, candidate commits and fast-forward integration, which is outside
this milestone.

## Decision

### Independent axes

ProjectCTL models these independently:

```text
Task Authority       = Beads | GitHub Issues | Linear | future Jira
Code Transport       = local | git_remote
Execution Ownership  = task_native | local_lock | git_ref_lease
Delivery             = separate policy, not decided by this ADR
```

Task-provider identity must not be used as a proxy for code-host identity.

### ProjectConfig v5

ProjectConfig is additively versioned to v5 and adds:

```yaml
code_transport:
  mode: local
```

or:

```yaml
code_transport:
  mode: git_remote
  remote_name: origin
  remote_identity: gitlab.com/group/repository
```

`remote_identity` is a credential-free canonical `host/path` identity.

It intentionally excludes:

- username;
- password;
- access token;
- URL scheme.

Examples:

```text
git@gitlab.com:group/repo.git
https://gitlab.com/group/repo.git

both normalize to:

gitlab.com/group/repo
```

Provider credentials remain owned by Git/credential helpers and are not persisted in ProjectCTL
configuration.

### Backward compatibility

ProjectConfig v1-v4 remain readable through in-memory upgrade.

For existing v4 GitHub task-authority projects, ProjectCTL preserves historical behavior by
migrating in memory to:

```yaml
code_transport:
  mode: git_remote
  remote_name: origin
  remote_identity: github.com/<task_store.repository>
```

Existing files are not rewritten automatically.

Other legacy providers migrate to local transport because no network code-transport intent was
previously represented.

### Generic remote identity

Brownfield inspection records the identity of a supported network `origin` independently from
GitHub detection.

Therefore a GitLab origin can be observed as:

```text
gitlab.com/group/repo
```

without making GitLab the task authority.

ProjectInspection advances additively to v3.

### Adoption contracts

AdoptionPlan and AdoptionManifest advance additively to v4 and persist:

- code transport mode;
- remote name;
- remote identity.

GitHub adoption retains the existing default of the matching GitHub origin.

Other task providers default to local transport unless the user explicitly selects `git_remote`.
This preserves the human intent boundary: the mere presence of a remote does not authorize
ProjectCTL to use it for ownership or delivery.

### ExecutionOwnershipPolicy

A new public `ExecutionOwnershipPolicy v1` records the effective strategy:

- task provider;
- strategy;
- local/distributed scope;
- code transport mode;
- remote name/identity when applicable.

This is inspectable through:

```bash
projectctl execution-ownership
projectctl execution-ownership --json
```

### Beads task-native ownership

Beads retains its existing task-native claim semantics.

A configured network code transport does not replace the canonical Beads claim primitive.

### Local ownership

For non-Beads task authorities using:

```yaml
code_transport:
  mode: local
```

ProjectCTL uses a local exact claim marker under `.projectctl/locks/task-claims/`.

Claim creation is serialized by a ProjectCTL project lock and uses exclusive file creation plus
`fsync`.

The marker binds:

- provider;
- task id;
- run id;
- claim token;
- durable TaskClaimRequest digest.

Claim/reconcile/validate/release require exact marker identity.

Release is performed while holding the same claim-operation project lock and refuses deletion if
the marker content changed.

This provides ownership between ProjectCTL processes sharing the same project filesystem.

It does **not** claim:

- internet-distributed ownership;
- safety between independent copies of the project on separate machines;
- a provider-side lock.

A user who needs cross-machine ownership must configure a distributed strategy.

### Generic Git remote ownership

For:

```yaml
code_transport:
  mode: git_remote
```

ProjectCTL uses an exact Git remote ref lease independently from the task provider.

Before remote ownership operations, the actual remote URL is normalized and must equal the
configured `remote_identity`.

A non-GitHub task such as Linear may therefore use:

```text
refs/heads/projectctl/claims/linear/<task-slug>-<digest>
```

on a GitLab or compatible Git server.

The claim marker commit binds:

- task provider;
- task id;
- run id;
- base commit;
- integration target;
- claim token;
- request time.

Acquisition and release continue to use exact `--force-with-lease` semantics from
`RemoteRefLease`.

The Git hosting vendor is not part of the ownership contract.

Repository branch/rules policy remains authoritative. If a server rejects claim-ref
creation/deletion, ProjectCTL fails closed.

### Historical GitHub compatibility

When the task authority is GitHub and the configured code remote still matches the historical
GitHub task repository, ProjectCTL retains the existing GitHub claimer and reserved ref naming.

The provider-neutral Git claimer also preserves the historical `gh-N` ref derivation where
necessary.

This avoids invalidating durable ownership evidence solely because the architecture boundary was
refactored.

### Application boundary

Execution preparation, claim validation, recovery and release no longer obtain ownership by
calling `TaskAuthority.require_claimer()`.

They resolve the independent execution-ownership strategy.

Task Authority remains responsible for canonical task state and task lifecycle writes.

### Execution-ready gate

A valid ownership strategy is necessary but not sufficient for autonomous execution.

The effective gate now conceptually requires:

- task read semantics;
- safe execution ownership;
- canonical needs-decision mutation;
- canonical completion mutation;
- compatible delivery policy.

Linear still lacks proven canonical lifecycle writes, so adding local/Git ownership does not make
Linear execution-ready in M3.2c1.

GitHub task completion currently remains publication-gated, so GitHub task execution still requires
a network Git delivery path under the current delivery adapter.

### Doctor

Doctor now treats these concerns separately.

Task-store checks prove provider readability.

Execution-ownership checks prove:

- configured strategy;
- local-only scope where applicable;
- generic remote identity match;
- remote Git readability.

Doctor does not create a test claim. Git write permission and remote branch policy are proven only
by a real claim attempt.

### Delivery is deliberately separate

This ADR does not treat the existence of a Git remote as permission to publish code.

In particular:

- GitLab may require merge requests;
- GitHub may require pull requests;
- a user may have an origin only for backup and not authorize ProjectCTL publication;
- local-only projects require no remote publication.

M3.2c2 owns delivery-policy generalization.

## Consequences

Positive:

- Linear + local Git is representable;
- Linear + GitLab is representable;
- Linear + GitHub remains representable;
- task-provider credentials and code-host credentials stay separate;
- generic Git ownership reuses a tested exact-CAS primitive;
- local-only users do not need a GitHub/GitLab account or network remote;
- ProjectCTL no longer describes a Git transport primitive as inherently GitHub-specific;
- delivery authorization is not inferred from remote existence.

Tradeoffs:

- local ownership is intentionally not distributed;
- ProjectCTL still requires a local Git repository;
- generic Git servers may reject the reserved claim namespace;
- delivery/publication is not yet generalized in this milestone;
- TaskAuthorityCapabilities v1 still contains historical claim/release fields; effective execution
  ownership is now separately represented by ExecutionOwnershipPolicy and should become the
  preferred architecture surface.

## Rejected alternatives

### Require GitHub for all remote ownership

Rejected because exact Git ref leases are Git transport semantics and would unnecessarily exclude
GitLab/self-hosted repositories.

### Use Linear/Jira assignment as the generic claim

Rejected because assignment is task metadata and does not by itself prove atomic exact ownership
for one ProjectCTL run.

### Treat local lock as distributed ownership

Rejected because independent project copies on separate machines do not share the local marker.

### Auto-use any discovered remote

Rejected because discovery is not authorization. Non-GitHub task providers default to local unless
the user explicitly chooses network Git transport.

### Support non-Git workspaces in this milestone

Rejected because the current evidence/worktree/integration model is fundamentally Git-native.

### Generalize publication at the same time

Rejected because ownership permission and publication permission are different security/policy
questions. GitLab/GitHub review requirements must be modeled explicitly rather than inferred from a
working push transport.

## Follow-up

M3.2c2 should introduce a provider-neutral delivery policy independent from Task Authority.

It should distinguish at least:

- local integration only;
- direct exact-base network Git publication;
- externally reviewed delivery such as pull/merge request policy.

Only after delivery evidence and safe Linear task mutation are both proven may Linear become
execution-ready.

A later, separate architecture track would be required for completely non-Git workspaces.
