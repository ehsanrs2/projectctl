# Advisory Skills & Review Evaluation — independent research

**Status:** Research-only; no ProjectCTL production integration, approved ADR, or change to the active M6.0 milestone.

Branch: `research/advisory-skills-eval`.

This pilot compares three review **rubrics** on the same synthetic cases: A baseline, B gstack-inspired, C Superpowers-inspired. It does **not** execute original gstack or Superpowers skills. Model outputs are unverified advisory claims until independent adjudication.

## Authority and privacy

- Do not modify `projectctl/`, `docs/PROJECT_STATE.yaml`, `docs/PROJECTCTL_BLUEPRINT.md`, ADRs, `projectctl.scope.yaml`, `projectctl.verification.yaml`, project state, or any M6.0 branch.
- Keep the blind answer key `source_bundle/oracle/gold.json` outside this public repo and outside model-accessible paths; it is intentionally absent here. The legacy `source_bundle/scripts/validate_bundle.py` requires that private oracle, so **do not** run it from this public checkout or copy the oracle into the repository.
- **Pilot blinding limitation:** two adjudicator-only test scripts were inadvertently present in an earlier public branch commit and have been removed from its current tree. Their descriptions of seeded defects remain accessible in Git history. These fixtures therefore support engineering smoke comparisons only, not high-assurance blinded estimates. Rebuild independent private holdout fixtures before drawing strong comparative conclusions. Do not force-push/rewrite history without separate approval.
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

The Runner also converts both `--output-schema` and `--output-last-message` paths to **absolute paths** before starting Codex in an isolated temporary working directory. This fixes a failure when the pilot used a relative `--out` path. An end-to-end mock regression tests this exact shape.

**v6 identity contract:** the general Strict wire schema intentionally omits `minLength`, which allowed a valid Codex response with `run_id=""` in v5 to fail the canonical validator. For every job, preparation now creates a separate immutable, SHA-256-bound `wire_schemas/NN.json` with `const` for `run_id`, `case_id`, and `arm`. The prompt specifies the same expected `run_id`; canonical validation additionally checks identity. No report is silently repaired after inference and no original `source_bundle` schema is modified.

Treat v5 as diagnostic only: its A report was qualified but its B report was invalid, so **no complete paired v5 comparison exists**. The v6 pilot uses the same nine case-arm assignments but a slightly changed identity instruction. Do not combine v5 and v6 runs into one preregistered matched comparison. Tests must pass before any real execution.

## Pilot batch one

First make sure the tests above pass and the model `gpt-6-luna` is available with `codex exec`. Then, **only if you intend to make up to three real Codex invocations**:

```bash
uv run python scripts/codex_pilot_runner.py \
  --bundle source_bundle \
  --out ./output/pctl-review-real-batch1-v6 \
  --model gpt-6-luna \
  --reasoning medium \
  --execute --ack-paid --ack-host-read-risk
```

Use a new `--out` directory for every attempt. Do not delete historic failed runs. Stop after this batch and inspect `output/pctl-review-real-batch1-v6/execution_summary.json`: require `attempted=3`, `completed_valid=3`, `qualified_tool_free=3`, and `halt_reason=null` before considering the next batch.

If a run fails, inspect the local private `results/NN/stderr.txt`, `events.jsonl`, and `run_metadata.json` for the failed ordinal; redact secrets before sharing, and do not auto-retry or switch models in the same study. A `HALTED` event is not an evaluation-quality result.

For scoring and future architecture decisions, first independently adjudicate all qualified findings on the private oracle and report TP/FP/FN, time and token usage. Do not infer outcomes from mocked end-to-end tests.

## Failed v4 diagnosis (no model calls)

If your earlier v4 batch halted, inspect its **local** metadata first; do not publish raw stderr or event streams without redaction:

```bash
uv run python - <<'PY'
import json
from pathlib import Path
p = Path('output/pctl-review-real-batch1-v4/results/01/run_metadata.json')
r = json.loads(p.read_text())
print('exit_code:',r.get('exit_code'))
print('report_valid:',r.get('report_valid'))
print('protocol_violations:',r.get('protocol_violations'))
print('event_type_counts:',r.get('event_type_counts'))
print('usage:',r.get('usage'))
PY
```

Check `output/pctl-review-real-batch1-v4/results/01/stderr.txt` **locally** for a schema-file path or output path error. If it is a different error, stop and review that error before running v5. Do not retry v4 in place; the historical attempt remains evidence.

## v5 observed failure — historical evidence

The v5 batch made **two real Codex invocations**, both `exit_code=0` and both without observed tool events. Run 1 (case-01 / baseline) passed local validation; run 2 (case-01 / gstack-inspired) returned `run_id=""`, rejected by the frozen local JSON Schema (`minLength: 1`). `attempted=2`, `completed_valid=1`, `qualified_tool_free=1`. The other seven runs were not attempted. Keep local raw evidence private; the v5 result is not sufficient to compare reviewer quality. See `PILOT_V5_DIAGNOSIS.md` for the sanitized diagnosis.
