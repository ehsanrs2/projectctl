# ADR-035: Context Discovery Is Derived Evidence, Never Execution Authority

Status: Accepted

## Context

M4.2a established a single execution-input authority and M4.2b unified automated worker-turn
orchestration. The next product need is better context discovery: users should not need to manually
guess every relevant code path before authoring execution input/write scope.

Repository structure, AST relationships, task references and tools such as Graphify can provide
useful evidence, but automatically promoting derived relationships into execution authority would
re-introduce the authority ambiguity that M4.2 removed.

## Decision

M5.0 adds a **derived context discovery layer** with two public artifacts:

- `ContextDiscoveryReport v1`
- `ContextScopeSuggestion v1`

Both explicitly declare:

- `authoritative = false`
- scope suggestions require human review

ProjectCTL does not mutate `projectctl.parallel.yaml` from discovery output.

### Built-in deterministic discovery

The built-in provider reads the exact recorded Git base and derives evidence from:

- explicit task reference files
- explicit tracked path mentions in task/reference text
- Python AST symbol definitions
- Python import/imported-by edges
- filename token overlap
- conventional test-companion naming

The built-in provider does not use embeddings, an LLM, network access, or the dirty working tree.

Source/reference files above bounded size limits are skipped rather than read without bound.

### Conservative write suggestions

Read/navigation context may be suggested from weaker structural relationships.

Write scope is more restrictive.

A path becomes a write candidate only from stronger evidence such as:

- explicit path mention in an action-bearing task/reference sentence
- a task-title symbol that maps to a concrete Python definition
- a conventional test companion of a primary target

Graph-only inferred relationships cannot create write authority.

Suggestions are emitted as exact paths, not broad tree writes.

### Optional Graphify evidence

When `features.graphify=true`, ProjectCTL may read an existing:

```text
graphify-out/graph.json
```

ProjectCTL does not invoke Graphify, an LLM, or any Graphify network/service as part of discovery.

The graph is consumed as derived evidence only.

Supported node-link data preserves:

- node `source_file`
- edge `relation`
- edge `confidence`
- edge `confidence_score` when present

`EXTRACTED`, `INFERRED` and `AMBIGUOUS` provenance remain distinguishable.

Graph paths are normalized and must resolve inside the current repository. Foreign/out-of-repository
paths are ignored.

The exact graph file digest is recorded, but Graphify evidence is not treated as Git-base authority
because graph freshness may differ from the selected base.

### Git-base binding

Built-in discovery reads tracked source/reference content using Git object access at the selected
base commit.

Uncommitted working-tree changes therefore do not alter built-in discovery evidence for that base.

This is a reproducibility property, not an execution authorization property.

### Scope comparison

`ContextScopeSuggestion v1` can compare derived suggestions with the current human-managed
`projectctl.parallel.yaml` task scope.

It reports:

- suggested inputs not declared
- suggested writes not declared
- declared inputs not suggested
- declared writes not suggested

Differences are advisory.

The declared policy remains authoritative even when discovery disagrees.

### CLI

M5.0 exposes:

```bash
projectctl context discover TASK_ID --project /path/to/repo
projectctl context discover TASK_ID --project /path/to/repo --json

projectctl context suggest-scope TASK_ID --project /path/to/repo
projectctl context suggest-scope TASK_ID --project /path/to/repo --yaml
projectctl context suggest-scope TASK_ID --project /path/to/repo --json
```

The YAML form is a review-only task-scope snippet. It never writes the catalog.

### Persistence

Derived artifacts are stored only under ProjectCTL operational state:

```text
.projectctl/context/discovery/<task-id>/
.projectctl/context/suggestions/<task-id>/
```

They do not become human-managed repository policy automatically.

## Consequences

Positive:

- users receive explainable scope/navigation assistance;
- suggestions are reproducible against a Git base;
- Graphify can enrich discovery without becoming required infrastructure;
- inferred graph edges cannot silently widen write permission;
- declared scope and derived evidence can be compared explicitly;
- M4.2 execution authority remains intact.

Tradeoffs:

- built-in language-semantic depth is strongest for Python in M5.0;
- other languages receive path/reference/filename evidence unless Graphify supplies richer structure;
- Graphify freshness is not proven against the selected Git base and is therefore advisory only;
- no automatic scope application is provided in M5.0.

## Rejected alternatives

### Automatically write `projectctl.parallel.yaml`

Rejected because derived evidence would become execution authority without deliberate human review.

### Automatically feed all discovered paths into ExecutionInputManifest

Rejected because this would make discovery heuristics an implicit execution-invalidating authority.

### Run Graphify automatically during task preparation

Rejected because it would add a heavyweight/possibly model-backed dependency to the critical
execution path and make reproducibility dependent on external tooling state.

### Trust only Graphify EXTRACTED edges as authority

Rejected. "Extracted" describes Graphify provenance, not ProjectCTL authorization.

### Use an LLM to rank or approve write scope

Rejected for M5.0. LLM reasoning may assist humans later but cannot be the sole safety authority.

## Implementation record

Implemented in M5.0.

Public contracts:

- `ContextDiscoveryReport v1`
- `ContextScopeSuggestion v1`

No ProjectConfig schema bump is required. Existing `features.graphify` controls optional graph
consumption.

## Follow-up

The next milestone is:

> **M5.1 — Context Review & Adoption Workflow**

M5.1 may add an explicit, reviewable workflow for turning accepted discovery evidence into
human-managed scope policy. It must preserve a visible approval boundary and must not silently
mutate authority.
