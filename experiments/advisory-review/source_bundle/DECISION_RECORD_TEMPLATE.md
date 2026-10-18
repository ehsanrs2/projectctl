# Research Decision Record — ProjectCTL External Advisory/Skills

**Research package version:** pctl-parallel-p0-2026-10-18  
**State:** DRAFT / NOT ACCEPTED  
**Authority:** Non-authoritative research; not an ADR

## Decision item

- ID: [P0-01 / P0-02 / P1-01 etc.]
- Proposed change: [one clear and bounded statement]
- Evidence source: [pinned repo commit and paths; case reports; independent review]
- Owner decision: [undecided | reject | defer | approve further research | approve ADR drafting]
- Date and rationale: [leave empty until owner chooses]

## Why now

[Expected product impact, measurable in developer time/quality/cost, not stars/popularity]

## Compatibility

- ProjectCTL SHA reviewed: `c24eecd7bf3c94e80d444399a85394c57bbf4b67`
- Target ProjectCTL milestone: **none while M6.0 remains active**
- Worker SDK/CLI compatibility proof: [none until tested]
- External Skill commit + source digest: [pin before native test]

## Evidence checklist

- [ ] Architecture invariants preserved (no new authority)
- [ ] All requested effects identified and enforceable
- [ ] Offline synthetic trials reproduced by independent operator
- [ ] Blind oracle handling audited
- [ ] Metrics / false positives / workload captured
- [ ] Real Skill execution safety separately qualified, if proposed
- [ ] No M6.0 schema/runtime/database changes
- [ ] No uncontrolled egress or second-model spend
- [ ] No incompatible Codex SDK assumptions

## Result

**Current default:** DEFER IMPLEMENTATION; retain as research candidate.

**If approved later:** prepare a dedicated ADR with alternate designs and acceptance criteria; update the canonical blueprint only after the ADR is accepted and a milestone is explicitly chosen. Approval to write an ADR is not approval to activate the runtime.
