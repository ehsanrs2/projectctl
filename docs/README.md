# ProjectCTL documentation

This directory separates **current status**, **canonical architecture**, **accepted decisions**, **implementation guides** and **historical evidence**. Do not infer operational permission from a green synthetic test or an older document's stage-local wording.

## Start here

| Goal | Document | Role |
| --- | --- | --- |
| What ProjectCTL is and how to get started | [Root README](../README.md) | Concise public landing page |
| Current merged features, blockers and dependencies | [Implementation status — 2026-11-04](IMPLEMENTATION_STATUS.md) | Dated evidence ledger, **not** a second roadmap |
| Project vision, authority map, invariants and roadmap direction | [ProjectCTL Blueprint](PROJECTCTL_BLUEPRINT.md) | **Canonical** human-managed architecture and roadmap shape |
| Active goal/milestone | [PROJECT_STATE.yaml](PROJECT_STATE.yaml) | **Sole** structured active-milestone authority |
| Detailed previous milestone commands and explanations | [Feature history](FEATURE_HISTORY.md) | Preserved historical root README; may be stale |
| M6 document topics and gating | [M6 architecture index](architecture/INDEX.md) | Curated navigation |
| Branch/document cleanup | [Git hygiene](GIT_HYGIENE.md) | Protected refs, merge ancestry, operator-only guarded deletion |
| Decisions | [ADRs](decisions/) | Versioned architecture decisions with their original context |

## Implemented Post-D2 capability vs M6 research

The [Post-D2 Lifecycle Observability guide](architecture/POST_D2_LIFECYCLE_OBSERVABILITY.md) and [ADR-041](decisions/ADR-041-offline-lifecycle-audit-and-measurements.md) describe merged [PR #126](https://github.com/ehsanrs2/projectctl/pull/126). Its derived, read-only lifecycle audit and optional measurements do not authorize stages or guarantee an atomic, authenticated Trace snapshot. Earlier ADR-041 “PR pending” wording records **the original design review stage**; the current merged state is recorded in the [status ledger](IMPLEMENTATION_STATUS.md).

The separate M6 Trace Export design is governed by [ADR-039](decisions/ADR-039-read-only-execution-trace-export.md), [ADR-040](decisions/ADR-040-trace-snapshot-publication-consistency.md) and the [M6 architecture index](architecture/INDEX.md). R0b active-WAL read remains fail-closed; P0–P4 real-source operational gates remain NO-GO.

## Document maintenance rules

- Do **not** recreate a second authoritative roadmap, project-state source or task tracker here. A status ledger may summarize dated GitHub evidence, not reauthorize execution.
- Do not rewrite historical results (D2 experiments, older PR acceptance, synthetic P3i–P3n) as if their original dates and gate states were different. Use a current addendum with merge SHA and evidence.
- A **new** architecture policy requires an ADR and corresponding Blueprint change; a docs index or rebaseline does not amend ADR-039/040/041.
- No generated schemas, dashboards or self-recomputed hashes are sources of independent authority.
- Before moving or removing files, audit repo-relative references and do not destroy source/decision history merely for aesthetics. Prefer curated indexes to destructive bulk moves.
