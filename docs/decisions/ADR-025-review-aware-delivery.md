# ADR-025: Review-Aware Delivery and External Merge Reconciliation

Status: Accepted

## Context

ADR-024 made Code Delivery independent from Task Authority and explicitly modeled
\`review_required\`, but left that mode fail-closed because no pull-request or merge-request
delivery boundary existed.

A review-required repository has materially different semantics from direct Git publication:

- ProjectCTL is allowed to publish a candidate branch, but not to update the protected target
  directly;
- creating a PR/MR is not delivery completion;
- review and merge are external human/provider actions;
- the target may change while review is open;
- providers may merge by fast-forward, merge commit, squash, or rebase;
- a process may crash after remote branch creation or review creation but before local persistence.

The existing invariant remains: verified code must not be silently transformed after verification.

## Decision

### Review delivery is an active run phase

ProjectCTL adds the active run state:

\`\`\`text
AWAITING_REVIEW
\`\`\`

A run enters this state after a durable review request has been created/reconciled and the review
is still open.

While awaiting review:

- the canonical task is not complete;
- the exact execution claim remains held;
- the run remains active;
- the verified candidate and evidence remain durable;
- autonomous execution stops with \`REVIEW_PENDING\` rather than starting another task.

This is waiting on an external dependency, not a passed or failed run.

### Durable contracts

M3.2c3 adds:

- \`ReviewRequest v1\`
- \`ReviewReceipt v1\`
- \`CodeDeliveryPolicy v2\`
- \`IntegrationManifest v3\`

A ReviewRequest binds:

- task id and task provider;
- run id;
- review provider;
- pinned remote identity;
- deterministic source branch;
- target branch;
- verified base;
- exact candidate commit;
- evidence path and digest;
- deterministic title/body.

A ReviewReceipt binds the provider observation back to the request digest and records review
identity, URL, source/target refs, exact candidate, observed head, merge identity, target identity,
state, and whether delivery has been independently proven complete.

### Deterministic candidate branch

The remote review branch is derived from run id plus candidate prefix:

\`\`\`text
projectctl/review/<sanitized-run-id>-<candidate-prefix>
\`\`\`

ProjectCTL publishes exactly the verified candidate.

If the deterministic branch already exists:

- same candidate -> idempotent reuse;
- different commit -> fail closed.

ProjectCTL does not force-replace a different remote review branch.

### Request-before-review durability

The ReviewRequest is persisted and anchored in run events before ProjectCTL attempts review
creation.

Review creation is then reconcile-first:

1. publish/prove exact candidate source branch;
2. search for an existing review matching the deterministic source and target;
3. create only when absent;
4. if create reports an error, reconcile once because the remote create may have succeeded.

This makes retries deterministic across the important create/persist crash window.

### Built-in providers

M3.2c3 implements review adapters for canonical hosted identities:

- \`github.com/<owner>/<repository>\` -> GitHub pull request via authenticated \`gh api\`;
- \`gitlab.com/<group>/<repository>\` -> GitLab merge request via REST API.

Credentials remain runtime-only.

GitHub uses the existing authenticated \`gh\` CLI.

GitLab accepts exactly one of:

\`\`\`text
GITLAB_TOKEN
GITLAB_ACCESS_TOKEN
\`\`\`

Self-hosted GitHub Enterprise, self-hosted GitLab, and other Git hosts are not inferred from host
names in this milestone. \`review_required\` on an unsupported host fails closed before claim.

### ProjectCTL never auto-merges

The review adapters may:

- publish the exact source branch;
- create a PR/MR;
- reconcile its current state.

They do not approve or merge it.

The merge is an external human/provider action.

### Open review semantics

An open PR/MR produces a durable ReviewReceipt but not completion evidence.

The run transitions to \`AWAITING_REVIEW\`.

Recovery can be invoked repeatedly and remains idempotent while the review is open.

### Closed without merge

A review that is closed without merge is not successful delivery.

ProjectCTL transitions the run to \`NEEDS_DECISION\`, marks the canonical task for human review
through the configured task authority, and applies normal independent ownership-release semantics.

### Merged is necessary but not sufficient

A provider reporting \`merged\` does not by itself prove that the verified candidate reached the
target without transformation.

ProjectCTL requires:

1. review head equals the exact verified candidate;
2. the current remote target is fetched and stable during reconciliation;
3. one of these Git proofs succeeds:
   - fast-forward result: remote target equals candidate;
   - merge-commit result: the reported merge commit has exactly two parents,
     \`{verified_base, verified_candidate}\`;
4. the proven merge commit is reachable from the current remote target;
5. the local integration target can fast-forward to that current remote target.

Only after these checks does ReviewReceipt set \`delivery_complete=true\`.

### Squash, rebase, and stale-base review merges

The following are not automatically accepted using the old verification evidence:

- squash merge;
- rebase merge;
- merge commit whose parents are not exactly the verified base and candidate;
- review whose head no longer equals the verified candidate;
- target movement that cannot be reconciled to the proven review merge.

These cases require human decision / re-verification.

This is intentionally stricter than ordinary provider merge success.

### Local integration while review is pending

The existing execution pipeline performs its exact local fast-forward integration before entering
the delivery phase.

Therefore while a review is open, the ProjectCTL local target may already point to the verified
candidate even though the remote protected target has not yet accepted it.

This local state is not canonical delivery proof.

The run remains active and the task remains incomplete until the external review is merged and
reconciled.

After an accepted merge, the local target may fast-forward from candidate to the provider's proven
merge result.

### Completion evidence

For \`review_required\`, canonical task completion receives the final
\`ReviewReceipt(delivery_complete=true)\` as its EvidenceReference.

GitHub and Linear lifecycle writers accept this proof in addition to their existing direct/local
delivery evidence.

Task completion happens only after review delivery proof succeeds.

### Claim lifetime

Independent ownership is retained while the review is open.

It is released only after:

- successful merged-review reconciliation and canonical task completion; or
- fail-closed terminal reconciliation such as closed-without-merge.

A pending review therefore prevents another ProjectCTL executor from concurrently owning the same
task.

### Recovery

\`projectctl run recover\` handles \`AWAITING_REVIEW\`:

- open -> remain AWAITING_REVIEW;
- merged and exact/proven -> synchronize target, complete task, release claim, PASSED;
- closed unmerged -> NEEDS_DECISION;
- transformed/ambiguous merge -> NEEDS_DECISION;
- provider outage -> no stale-success fallback; retry later.

Recovery never invents merge success from local artifacts alone.

## Consequences

Positive:

- protected branches can use ProjectCTL without bypassing review policy;
- review creation is idempotent across crash windows;
- GitHub PR and GitLab MR delivery share one provider-neutral application contract;
- task-provider identity remains independent from code-review host;
- externally merged code is accepted only when old verification still proves the delivered history;
- pending review is visible as an explicit active lifecycle state.

Tradeoffs:

- an open review keeps task ownership for potentially long periods;
- squash/rebase merge workflows require re-verification or a future transformation-aware
  verification contract;
- self-hosted review providers are not yet supported;
- ProjectCTL deliberately does not automate approval/merge.

## Rejected alternatives

### Mark the task complete when PR/MR is opened

Rejected because review request creation is not delivery.

### Auto-merge after creating the review

Rejected because merge/approval policy is human/provider authority and ProjectCTL must not bypass
it.

### Trust provider \`merged\` state without Git proof

Rejected because squash/rebase/stale-base merges can transform or relocate the verified candidate.

### Rewrite the deterministic review branch on retry

Rejected because that could change the reviewed code under an existing review.

### Release the claim while review is pending

Rejected because another executor could then create conflicting work for the same canonical task.

## Follow-up

With read, lifecycle, ownership, direct delivery, and review delivery boundaries now proven across
multiple providers, the next provider evaluation should reuse this sequence instead of introducing
provider-specific application logic.

The next provider candidate in the roadmap is Jira. Its milestone identifier should be frozen only
after reviewing Jira's current API and concurrency/lifecycle primitives.
