# ADR-024: Provider-Neutral Code Delivery and Additive Linear Lifecycle

Status: Accepted

## Context

ADR-023 separated Task Authority, Code Transport, and Execution Ownership. One coupling remained:
remote publication was still selected by Task Authority.

That is incorrect for combinations such as Linear + GitLab, Beads + GitHub, or a local task
authority whose verified code must be published to a team remote.

The presence of a Git remote is also not publication authorization. A remote may be backup-only,
may reject direct target pushes, or may require pull/merge-request review.

Linear introduces a second problem. ProjectCTL needs durable completion/needs-decision semantics
without overwriting native human workflow state. Linear exposes workflow updates, but ProjectCTL
does not have a documented compare-and-swap precondition that would make a read-then-state-update
safe against a concurrent human transition.

Linear does expose team-scoped issue labels and additive issue label mutations. Those allow
ProjectCTL to own a narrow namespace without replacing human labels or native workflow state.

## Decision

### Delivery is an independent policy axis

ProjectConfig advances additively to v6 and adds:

```yaml
code_delivery:
  mode: local | direct_git | review_required
```

Delivery does not derive from Task Authority.

### Local delivery

`local` means the verified candidate only needs successful local fast-forward integration before
canonical task completion.

Completion evidence is the durable `EvidenceManifest`.

A network remote may still exist for ownership or other human purposes. Its presence does not
change local delivery semantics.

### Direct Git delivery

`direct_git` is explicit authorization for ProjectCTL to publish the exact verified candidate to
the configured Git remote target.

It requires `code_transport.mode=git_remote`.

Publication remains:

- exact-base;
- fast-forward only;
- protected by an exact Git ref lease;
- reconciled through durable PublicationRequest/PublicationManifest evidence;
- fail-closed on remote divergence, auth failure, or branch/rules rejection.

The publisher is hosting-vendor-neutral. The configured credential-free `remote_identity` is
validated against the actual Git remote before publication.

Task provider identity is informational in PublicationRequest; it no longer selects the publisher.

Historical GitHub publication requests using `owner/repository` remain accepted when they map to
the configured `github.com/owner/repository` identity.

### Review-required delivery

`review_required` represents repositories where code must flow through a pull/merge-request
review path.

M3.2c2 models the policy but does not implement a GitHub PR or GitLab MR delivery adapter.

Therefore:

- the policy is inspectable;
- Doctor reports it;
- autonomous execution fails before claim;
- ProjectCTL never silently falls back to direct push.

A future adapter must produce durable review/delivery evidence before this mode can become
execution-ready.

### Legacy configuration migration

ProjectConfig v1-v5 remain readable without rewriting the persisted file.

Existing GitHub task-authority projects whose historical code transport exactly matches
`github.com/<task_store.repository>` migrate in memory to `direct_git` so M3.0c behavior is
preserved.

Other legacy configurations migrate to `local`. In particular, an existing Linear + GitLab
transport does not become publish-authorized merely because a remote exists.

### Linear lifecycle markers

ProjectCTL reserves two team-scoped Linear issue labels:

- `projectctl:completed`
- `projectctl:needs-decision`

ProjectCTL may create these labels when missing and add/remove only these reserved labels.

It does not:

- change native Linear workflow state;
- change assignee;
- replace the issue's label set;
- remove human-owned labels;
- interpret ordinary user labels as ProjectCTL lifecycle authority.

### Native terminal state precedence

Linear native terminal state remains authoritative:

- native completed -> DONE
- native canceled -> CANCELLED

For non-terminal native states:

- only `projectctl:completed` -> DONE
- only `projectctl:needs-decision` -> NEEDS_DECISION
- both markers -> NEEDS_DECISION
- neither -> existing Linear state/eligibility normalization

Both markers deliberately fail closed because they represent an interrupted or conflicting
ProjectCTL lifecycle transition.

### Crash-safe two-phase Linear completion

Linear completion uses a fail-closed marker protocol:

1. validate durable completion evidence;
2. verify current task state and incoming blocker relations;
3. add `projectctl:needs-decision` as a guard;
4. add `projectctl:completed`;
5. re-read current issue and blocker relations;
6. remove the needs-decision guard only after all checks still pass.

Consequences:

- crash after step 3 leaves NEEDS_DECISION;
- crash after step 4 leaves both markers -> NEEDS_DECISION;
- concurrent blocker/state ambiguity after staging leaves both markers -> NEEDS_DECISION;
- only successful completion removes the guard and leaves the completed marker alone.

This avoids a false durable DONE state during partial completion.

### Completion evidence

Linear completion accepts only a durable ProjectCTL completion artifact inside the project.

For local delivery this is a passing EvidenceManifest.

For direct Git delivery this is a PublicationManifest proving the exact candidate is visible at the
configured remote target.

Digest equality is revalidated before lifecycle mutation.

### Concurrent provider changes

Immediately before completion, ProjectCTL reads current Linear state and incoming blocker
relations.

After staging both lifecycle markers, it reads current issue state and blocker relations again.

A newly introduced unresolved blocker, canceled state, unknown relation, relation-direction
mismatch, or missing state prevents successful completion and leaves the decision guard durable.

ProjectCTL therefore does not need to overwrite Linear workflow state to express its own lifecycle
result.

### Ownership release

Claim release is selected from Execution Ownership, not delivery policy.

- task-native ownership keeps provider-native semantics;
- ProjectCTL local/Git-ref ownership is released after successful canonical completion;
- independent ownership is also released after the task is durably marked needs-decision.

This removes the final historical coupling between task-provider delivery flags and ownership.

### Inspection and Doctor

`projectctl code-delivery --json` exposes the effective CodeDeliveryPolicy v1.

Doctor reports Task Authority, Execution Ownership, and Code Delivery separately.

For direct Git delivery, Doctor may prove remote identity/readability but never performs a probe
push. Write permission and branch/rules policy are proven only by a real publication attempt.

## Consequences

Positive:

- Linear + local Git can complete safely without any network publication;
- Linear + GitLab direct publication is representable;
- Beads + remote direct publication is representable;
- GitHub remains backward-compatible with M3.0c;
- remote existence is no longer confused with publish authorization;
- Linear completion is additive and preserves human workflow intent;
- partial/crashed Linear completion fails closed to NEEDS_DECISION;
- application integration no longer asks Task Authority for a publisher.

Tradeoffs:

- `review_required` is not yet executable;
- Linear task-native claim/release capability remains unsupported even though ProjectCTL execution
  can use an independent ownership strategy;
- ProjectCTL lifecycle labels are visible provider metadata;
- team label write permission is proven only on first real mutation;
- Linear marker creation is not globally atomic, so creation races use read/create/re-read and
  reject ambiguous duplicate reserved labels.

## Rejected alternatives

### Infer direct publication from an existing origin

Rejected because discovery is not authorization.

### Change Linear workflow state to completed/blocked

Rejected because ProjectCTL cannot safely overwrite concurrent human workflow intent without a
proven compare-and-swap boundary.

### Replace the entire Linear label list

Rejected because that could delete human-owned labels.

### Use only a completed marker and validate afterward

Rejected because a crash between adding the completed marker and post-validation could expose a
false durable DONE state.

### Silently direct-push when review-required publication is unsupported

Rejected because branch/review policy is human intent and must fail closed.

## Follow-up

The remaining delivery gap is a review-aware adapter boundary for GitHub pull requests and GitLab
merge requests.

A future milestone should define durable review request/receipt contracts, exact candidate binding,
recovery after request creation, and host-specific reconciliation without weakening the direct-Git
or local delivery semantics established here.
