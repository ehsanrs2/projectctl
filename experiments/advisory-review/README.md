# Advisory Skills & Review Evaluation (research-only)

**Status:** experimental; NOT an accepted ProjectCTL architecture decision, milestone, or production feature.

This folder holds the independent, offline-first review-comparison pilot. It is deliberately segregated from `projectctl/`, `docs/PROJECT_STATE.yaml`, the verification policy, and the active M6.0 implementation.

## Ownership and guardrails

- ProjectCTL's canonical task, scope, execution, evidence, quota, verification and integration authorities are unchanged.
- No ProjectCTL runtime hooks, worker adapters, task writes, migrations, releases, automatic merges, or changes to accepted ADRs in this research branch.
- Evaluation arms: baseline, *gstack-inspired rubric*, *Superpowers-inspired rubric*. These are NOT executions of the original gstack or Superpowers skills.
- Keep the original Codex failure outputs as local audit evidence; do not commit their raw logs.
- **Never commit `source_bundle/oracle/gold.json`** (blind evaluator answer key), `output/`, `prepared_prompts/`, `.env`, provider responses, personal paths, credentials, or ChatGPT/Codex session logs.
- Run the real-model batch manually, with the same authorized model and reasoning effort for all arms. No silent fallback or model substitution.
- Publish only sanitized aggregate results after independent adjudication.
- After a positive pilot, propose an ADR for owner review. This directory must never become a parallel task tracker.

## Local isolated worktree

From an existing clone of `ehsanrs2/projectctl`:

```bash
git fetch origin research/advisory-skills-eval
git worktree add -b research/advisory-skills-eval ../projectctl-advisory-lab origin/research/advisory-skills-eval
cd ../projectctl-advisory-lab
```

Import the existing local **phase2 v3** experiment sources under `experiments/advisory-review/`, excluding generated outputs and the answer key. Keep the answer key in a private location, inaccessible to the reviewer process; materialize locally only for separate, post-run scoring. Python/uv should be operated inside this experiment directory, not in the ProjectCTL package root.

The stable research branch is a collaboration workspace, **not** a PR that should be merged into `main` by default. Accepted ideas require separate versioned design and implementation changes under the project's architecture rules.
