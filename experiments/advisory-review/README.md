# Advisory Skills & Review Evaluation — independent research

**Status:** Research-only; no ProjectCTL production integration, approved ADR, or change to the active M6.0 milestone.

Branch: `research/advisory-skills-eval`.

This pilot compares three review **rubrics** on the same synthetic cases: A baseline, B gstack-inspired, C Superpowers-inspired. It does **not** execute original gstack or Superpowers skills. Model outputs are unverified advisory claims until independent adjudication.

## Authority and privacy

- Do not modify `projectctl/`, `docs/PROJECT_STATE.yaml`, `docs/PROJECTCTL_BLUEPRINT.md`, ADRs, `projectctl.scope.yaml`, `projectctl.verification.yaml`, project state, or any M6.0 branch.
- Keep the blind answer key `source_bundle/oracle/gold.json` outside this public repo and outside model-accessible paths; it is intentionally absent here. The legacy `source_bundle/scripts/validate_bundle.py` requires that private oracle, so **do not** run it from this public checkout or copy the oracle into the repository.
- Do not commit `output/`, run logs, local prompts, credentials, `.env`, provider transcripts, personal paths, or raw model outputs. The local `.gitignore` excludes these.
- Use only human-reviewed, sanitized summaries in Git. Research output cannot decide task completion or override independent verification.
- Model execution is explicit, incurs quota, and is serial. Use the same model and reasoning effort across all arms. A model preflight is distinct from a 9-run trial.
- Codex CLI read-only mode does not guarantee that host files are confidential; run in a dedicated isolated environment for stronger data isolation.

## Local worktree setup

From the main repo clone (use a clean worktree):

```bash
git fetch origin research/advisory-skills-eval
git worktree add -b research/advisory-skills-eval ../projectctl-advisory-lab origin/research/advisory-skills-eval
```

If already created, keep using that existing worktree. Pull updates from its root:

```bash
git status --short
git pull --ff-only origin research/advisory-skills-eval
cd experiments/advisory-review
uv sync
uv run python -m unittest discover -s tests -p 'test_*.py' -v
uv run python scripts/validate_public_fixtures.py
```

Stop if `git status --short` shows unexpected changes; do not discard them.

## Strict schema compatibility fix

The canonical `source_bundle/schemas/advisory_report.v0.schema.json` is unchanged. `scripts/codex_pilot_runner.py` derives a **closed, fully-required** strict Codex wire schema in the new run directory and validates the output using the original canonical schema. Do not edit the frozen input bundle to fix wire-format incompatibilities.

## Pilot batch one

First make sure the tests above pass and the model `gpt-6-luna` is available with `codex exec`. Then, **only if you intend to make up to three real Codex invocations**:

```bash
uv run python scripts/codex_pilot_runner.py \
  --bundle source_bundle \
  --out ./output/pctl-review-real-batch1-v4 \
  --model gpt-6-luna \
  --reasoning medium \
  --execute --ack-paid --ack-host-read-risk
```

Use a new `--out` directory for every attempt. Do not delete historic failed runs. Stop after this batch and inspect `output/pctl-review-real-batch1-v4/execution_summary.json`: require `attempted=3`, `completed_valid=3`, `qualified_tool_free=3`, and `halt_reason=null` before considering the next batch.

If a run fails, inspect the local private `results/01/stderr.txt`, `events.jsonl`, and `run_metadata.json`, redact secrets before sharing, and do not auto-retry or switch models in the same study. A `HALTED` event is not an evaluation-quality result.

For scoring and future architecture decisions, first independently adjudicate all qualified findings on the private oracle and report TP/FP/FN, time and token usage. Do not infer outcomes from mocked end-to-end tests.
