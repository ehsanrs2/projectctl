# Phase 2 pilot — v5 diagnostic checkpoint (research-only)

Date: 2026-10-18. Source: user-supplied local `pctl-review-real-batch1-v5.zip`. This document intentionally excludes raw prompts, transcript payloads, event thread IDs, user paths, and any hidden oracle.

## Confirmed observations

| Attribute | Run 01 | Run 02 |
|---|---|---|
| Case | case-01 | case-01 |
| Arm | A-baseline | B-gstack-inspired |
| Model | gpt-6-luna | gpt-6-luna |
| Reasoning | medium | medium |
| Codex CLI | 0.163.0 | 0.163.0 |
| Exit code | 0 | 0 |
| Wall clock (seconds) | 11.967 | 8.933 |
| Observed input tokens | 18021 | 18023 |
| Observed output tokens | 193 | 178 |
| Observed unexpected tool events | 0 | 0 |
| Canonical report valid | yes | **no** |
| Reason | — | `run_id` was empty (`minLength: 1` failure) |

Batch: `attempted=2`, `completed_valid=1`, `qualified_tool_free=1`, third run not attempted. Neither Codex invocation had a transport, model-access, timeout, or nonzero-exit failure.

Both reports contained a plausible advisory finding related to a string-prefix path-boundary check. That is **not an adjudicated true-positive count**; run 02 fails the output contract, and the blind test answer was not consulted to score either finding.

## Root cause

The derived Codex Strict JSON Schema stripped locally enforced `minLength` constraints, so Codex could produce `run_id=""` while satisfying its wire schema. The canonical local validator correctly rejected that value. V5 therefore never produced a complete matched triplet.

## Repair and preservation

- Pin `run_id`, `case_id`, `arm` to per-job `const` values in nine separate, hashed wire schemas prepared before inference.
- Explicitly repeat the expected run ID in each prompt.
- Validate again with the unchanged canonical schema and require exact expected job identity.
- Do not manufacture post-hoc run IDs, loosen validation, hide an invalid attempt, or promote unqualified results into scoring.
- Retain v5 raw logs only in the ignored local `output/` tree.
- v6 starts a **new** nine-run pilot due to changed prompts; do not pool qualified v5 results with v6 as a primary preregistered comparison.
- The public Git-history exposure of oracle-derived diagnostic material from the initial import remains a separate blinding limitation; use a new private holdout for high-assurance comparative evaluation.

## Evidence status

Fix and unit tests are committed to the research branch. No real v6 Codex run has been observed at the time of this note. This note is not a ProjectCTL production artifact, ADR, milestone progress claim, or independent QA acceptance.
