# ADR-028: Jira CAS Lifecycle via Issue Properties

Status: Accepted

## Context

M3.3a established Jira Cloud read authority. M3.3b established explicit READY and
dependency semantics, but Jira remained non-executable because ProjectCTL could not safely
express canonical completion or needs-decision state.

Native Jira workflow transitions are not used for ProjectCTL lifecycle authority. A transition
changes human-visible workflow state and the REST transition endpoint does not provide the
ProjectCTL compare-and-swap boundary needed to prove that a concurrent human workflow decision
was not overwritten.

Jira issue entity properties are additive metadata, but ordinary per-issue PUT is also unsafe as a
lifecycle primitive. Atlassian documents entity properties as globally visible/editable metadata
where concurrent edits are last-write-wins and no general concurrent-edit mechanism is provided.

Jira also exposes a different bulk issue-property operation with filter predicates:

- `entityIds`
- `currentValue`
- `hasProperty`

The filtered bulk update is transactional over eligible issues and asynchronous. This gives
ProjectCTL a usable compare-and-set primitive when restricted to one stable Jira issue id and one
dedicated property key.

## Decision

### Dedicated lifecycle namespace

ProjectCTL reserves exactly one Jira issue property key:

```text
projectctl.lifecycle.v1
```

The value uses public schema `JiraLifecycleMarker v1`.

States are:

- `completion_pending`
- `completed`
- `needs_decision`

The marker binds:

- normalized ProjectCTL task id;
- stable Jira issue id;
- monotonic marker generation;
- durable evidence path/digest and run id for completion states;
- observation/update timestamp.

No secret, token, personal data, or sensitive configuration is stored in the property.

### Native Jira workflow remains human-owned

ProjectCTL does not:

- invoke Jira workflow transitions;
- alter Jira resolution;
- alter assignee;
- replace labels;
- change summary/description;
- claim Jira issues through native workflow state.

Native Jira terminal state remains authoritative over ProjectCTL markers.

### CAS only; ordinary property PUT is forbidden

Lifecycle mutation uses only:

```text
PUT /rest/api/3/issue/properties/{propertyKey}
```

with a filter restricted to the one stable Jira issue id.

Creation uses:

```json
{
  "filter": {
    "entityIds": [101],
    "hasProperty": false
  },
  "value": { "...": "..." }
}
```

Update uses:

```json
{
  "filter": {
    "entityIds": [101],
    "hasProperty": true,
    "currentValue": { "...exact previous marker...": "..." }
  },
  "value": { "...next marker...": "..." }
}
```

ProjectCTL never uses the simple last-write-wins per-issue property PUT for lifecycle state.

After the async mutation task reaches COMPLETE, ProjectCTL reads the property again and requires
exact equality with the desired marker.

If the value remains the expected old value, the CAS did not match and ProjectCTL fails closed.

If the value becomes any third/unknown value, ProjectCTL treats that as concurrent human/app
modification and refuses to overwrite it.

### Async ordering

Filtered property mutation is asynchronous.

ProjectCTL waits for the returned Jira task to finish before:

- reading the property back;
- issuing another lifecycle mutation;
- claiming success.

This is required because Jira asynchronous tasks are not guaranteed to execute in submission order.

### Crash-safe completion protocol

Completion is two phase:

1. validate durable EvidenceManifest, PublicationManifest, or ReviewReceipt;
2. read current Jira task truth with lifecycle markers ignored;
3. require no cancellation, unresolved dependency, or fail-closed ambiguity;
4. CAS property from absent to `completion_pending`;
5. re-read current Jira task truth after the durable guard exists;
6. CAS the exact `completion_pending` value to `completed`;
7. read the marker back and require exact equality.

Crash behavior:

- crash before step 4: no remote lifecycle state exists;
- crash after step 4: `completion_pending` remains and normalizes to NEEDS_DECISION;
- retry with the same evidence resumes from the existing pending marker;
- crash after step 6: retry observes the matching completed marker and is idempotent;
- a marker bound to different evidence is never overwritten.

### Snapshot normalization

For non-terminal native Jira workflow state:

- no ProjectCTL marker -> use M3.3b scheduler normalization;
- `needs_decision` -> NEEDS_DECISION;
- `completion_pending` -> NEEDS_DECISION;
- `completed` -> DONE only when current dependency/provider safety remains valid.

A completed marker that currently conflicts with unresolved blockers, malformed relationships,
cycle ambiguity, or other fail-closed conditions normalizes to NEEDS_DECISION rather than DONE.

Native Jira DONE/CANCELLED state takes precedence.

### External modification boundary

Jira entity properties are not private storage. Users/apps with sufficient issue permissions can
modify them.

ProjectCTL therefore treats an unexpected, malformed, foreign, or identity-mismatched lifecycle
property as explicit external state and fails closed. It does not repair or replace that property
automatically.

The filtered `currentValue` CAS ensures a value that changed after ProjectCTL's observation is not
silently overwritten.

### Needs-decision

`mark_needs_decision` uses the same CAS transport.

- absent -> CAS-create needs-decision;
- completion-pending -> CAS-update to needs-decision;
- existing needs-decision -> idempotent;
- existing completed -> preserved;
- malformed/foreign marker -> fail closed without overwrite.

### Completion evidence

Completion accepts the same durable delivery boundary already used by provider-neutral integration:

- local delivery -> passing EvidenceManifest;
- direct Git delivery -> successful PublicationManifest;
- review delivery -> completed merged ReviewReceipt bound to the exact candidate.

The evidence task id and digest must match before any Jira lifecycle mutation occurs.

### Execution ownership

Jira provider-native claim/release remain unsupported.

Execution ownership continues to be resolved independently:

- local code transport -> ProjectCTL local lock;
- generic remote transport -> exact Git ref lease.

With read + block_for_decision + complete now supported, Jira can become execution-ready through
the independent ownership and delivery axes without pretending Jira offers a native claim CAS.

### Doctor

Doctor validates Jira authority and scheduler policy as before.

It reports that lifecycle uses filtered issue-property CAS and that write permission is proven only
by the first real lifecycle mutation. Doctor does not perform a destructive probe write.

## Consequences

Positive:

- Jira can participate in autonomous ProjectCTL execution without workflow-state takeover;
- human Jira workflow state remains untouched;
- lifecycle state is additive and namespaced;
- concurrent property modification is detected instead of overwritten;
- completion is crash-recoverable and idempotent;
- local, direct-Git, and review-required code delivery remain independent from Jira task authority.

Tradeoffs:

- Jira users/apps with Edit Issues permission can modify entity properties, so lifecycle property
  integrity is defensive rather than private;
- Jira lifecycle write permission is not proven until a real mutation;
- filtered property updates are asynchronous and add latency;
- ProjectCTL lifecycle DONE is distinct from native Jira workflow completion unless a human/workflow
  separately transitions the issue.

## Rejected alternatives

### Native Jira workflow transitions

Rejected because ProjectCTL must not overwrite concurrent human workflow intent and the transition
endpoint is not used as a lifecycle CAS primitive.

### Ordinary per-issue property PUT

Rejected because entity properties are last-write-wins under concurrent edits.

### Jira labels

Rejected because additive labels do not provide an atomic compare-and-set value and are a more
visible shared human namespace.

### Blindly repair malformed lifecycle properties

Rejected because an unexpected property value is external state and may represent human/app intent.

## Follow-up

M3.3c completes the minimum Jira execution proof sequence:

- read authority;
- scheduler eligibility;
- dependency semantics;
- additive lifecycle mutation;
- independent execution ownership;
- provider-neutral delivery.

After this milestone, the next roadmap step should be selected from the broader post-M3 directions
only after a new architecture review rather than automatically extending Jira-specific work.
