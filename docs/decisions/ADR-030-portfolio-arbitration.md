# ADR-030: Portfolio Arbitration Preserves Project-Local Task Authority

Status: Accepted

## Context

M4.0a established account-global execution admission. Independent projects sharing one quota
account can no longer start quota-consuming worker turns concurrently.

The next problem is not mutual exclusion but **which registered project should receive the next
worker-turn opportunity**.

ProjectCTL already has:

- a global project registry in `$PROJECTCTL_HOME/state.sqlite`;
- an account-global admission history;
- one deterministic scheduler inside each project;
- project-local task, project-state and quota policy;
- durable unfinished runs that may need another worker turn.

A naive global scheduler could compare each project's raw local scheduler score. That is unsafe:
local weights and policy may differ between projects, so raw scores are not globally comparable.

A global scheduler also must not replace the configured task authority or choose a task inside a
project independently from that project's local scheduler.

## Decision

M4.0b introduces **Portfolio Scheduling & Cross-Project Arbitration**.

### Portfolio authority

The portfolio layer chooses **a project / worker-turn action**, not a task ranking inside that
project.

For new work, the task id comes from that project's existing scheduler decision.

The hierarchy is:

```text
Portfolio arbitration
        ↓ chooses project
Project-local scheduler
        ↓ chooses task
Execution planner
        ↓ creates run
Account-global admission
        ↓ grants worker turn
Worker provider
```

### Candidate envelope

Each registered project is inspected into a provider-neutral portfolio candidate envelope.

The envelope may contain:

- project instance id;
- logical project id;
- registered root;
- quota account;
- pending worker-turn action;
- selected/pending task id;
- local task/project/quota digests;
- resource class;
- last successful account admission time;
- exclusion reasons.

It deliberately does **not** contain or compare raw project-local scheduler scores.

### Eligible worker-turn actions

M4.0b arbitrates three worker-turn actions:

1. `resume_run` — resume a durable quota checkpoint;
2. `start_run` — start an already claimed run;
3. `new_task` — ask the project-local scheduler for new work, prepare it, then start it.

Runs in verification, integration, publication or external-review phases do not need an account
worker-turn grant and are not portfolio candidates for this primitive.

Unsafe partial/recovery states fail closed.

### Continuation before new work

Durable unfinished worker turns have priority over creating additional new work:

```text
resume_run
   ↓
start_run
   ↓
new_task
```

This minimizes stranded claims/worktrees/checkpoints before expanding the work-in-progress set.

### Fairness between projects

Within the same action class, arbitration uses account-global admission history:

1. project with no prior admission;
2. otherwise least-recently admitted project;
3. older registration;
4. stable project-instance id tie-break.

This is deterministic and does not assume that scheduler scores from different projects share a
common utility scale.

### Project health / identity

A registry row is not trusted merely because it exists.

Before it can become eligible, ProjectCTL validates:

- registered root still exists and is the exact Git root;
- local project-instance id matches the global registry;
- logical project id matches;
- quota account matches the requested portfolio account;
- project state/run DB can be read;
- current task/quota snapshot can be collected;
- quota snapshot is not stale;
- at most one project-local active run exists;
- required worker-turn state is safe.

Broken/stale registrations are excluded rather than blocking healthy projects.

Successful inspection refreshes the registry `last_seen_at`.

### Stale arbitration protection

A portfolio decision for `new_task` records the project-local:

- selected task id;
- task snapshot digest;
- project state digest.

Run preparation must re-run the local scheduler and require those inputs to still match before a
task claim is created.

This prevents a stale portfolio decision from claiming a different task after local intent or task
authority changed.

Quota is intentionally not frozen at portfolio-decision time. M4.0a remains the final safety gate
and re-reads quota while account admission is held.

### Account busy semantics

If M4.0a reports a live admission for the requested quota account, M4.0b returns an account-busy
decision and selects no new project.

Expired admissions are not treated as live; the M4.0a acquisition path remains responsible for
auditable stale-lease reclamation.

### Audit artifact

Every normal portfolio decision can be materialized under:

```text
$PROJECTCTL_HOME/portfolio/decisions/<decision-id>.json
```

The artifact is an audit record, not a second task authority or a durable grant.

Actual worker-turn ownership remains the M4.0a account admission lease.

### CLI

M4.0b exposes:

```bash
projectctl portfolio next --account <ACCOUNT>
projectctl portfolio next --account <ACCOUNT> --json

projectctl portfolio run --account <ACCOUNT>
projectctl portfolio run --account <ACCOUNT> --json
```

`portfolio next` is inspection/arbitration only.

`portfolio run` executes exactly one selected quota-consuming worker turn. It does not silently
verify, integrate, publish or merge afterward.

### Direct project execution remains safe

Project-local `run start` / `run resume` remain valid interfaces.

M4.0b is the global orchestration path, while M4.0a remains the non-bypassable safety authority at
the worker-provider boundary.

Therefore a direct project command cannot create concurrent account usage even if it bypasses
portfolio fairness.

## Consequences

Positive:

- cross-project arbitration is deterministic and auditable;
- local task policy remains local;
- heterogeneous scheduler weights do not create invalid global comparisons;
- unfinished worker turns are drained before creating more work;
- fairness uses actual account admission history;
- stale project registry entries cannot silently win;
- portfolio execution reuses the existing M4.0a ownership primitive.

Tradeoffs:

- the first portfolio policy is fairness-oriented rather than business-priority-aware;
- portfolio decisions may inspect several projects and therefore perform several provider reads;
- non-worker phases are still advanced project-locally;
- one quota account still permits only one worker turn at a time.

## Rejected alternatives

### Compare raw local scheduler scores

Rejected because scheduler weights/policies are project-local and scores are not globally
comparable.

### Move task selection into the portfolio layer

Rejected because that would create a second task-ranking authority.

### Persist a separate portfolio grant lease

Rejected for M4.0b because M4.0a already owns actual worker-turn admission. A second grant would
duplicate mutable ownership state.

### Freeze quota at portfolio decision time

Rejected because quota can change after arbitration. The authoritative check remains after M4.0a
admission acquisition and before worker-provider contact.

### Enable same-project parallel runs now

Rejected. M4.1a must first define scoped planning/conflict contracts.

## Follow-up

The next milestone is:

> **M4.1a — Parallel Planning Safety Contract**

It must define when two runs can coexist without invalidating project/task/base/write-scope
evidence. M4.1b may only enable parallel execution after that contract is proven.
