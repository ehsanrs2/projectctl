# Advisory Review Pilot — v6 Batch 1 (execution-only snapshot)

**Status:** 3/3 technically qualified. **Review accuracy NOT adjudicated.**
**Source:** Operator-provided `execution_summary.json`, observed 2026-10-18.
**ProjectCTL milestone:** This research is independent of M6.0; no production/runtime changes.

## Fixed run environment

- `codex-cli 0.163.0`, `gpt-6-luna`, `reasoning=medium`
- Synthetic `case-01`, three preregistered review *rubrics*, not direct executions of the underlying third-party skills
- Batch starts at job 1, batch size 3; no runs 4–9 included in this source.

| Job | Review arm | Exit | Seconds | Input tokens | Output tokens | Report valid | Tool-free | Claimed findings |
|---:|---|---:|---:|---:|---:|---|---|---:|
| 1 | A-baseline | 0 | 15.066 | 18049 | 308 | yes | yes | 1 |
| 2 | B-gstack-inspired | 0 | 11.140 | 14629 | 228 | yes | yes | 1 |
| 3 | C-superpowers-inspired | 0 | 11.431 | 14617 | 238 | yes | yes | 1 |
| **Total** | | | **37.637** | **47295** | **774** | **3/3** | **3/3** | **3** |

Totals: 48,069 observed input+output tokens; `attempted=3`; `completed_valid=3`; `qualified_tool_free=3`; `halt_reason=null`. No protocol violations are reported for any of the three executions. Event type counts per run: `thread.started=1`, `turn.started=1`, `item.completed=1`, `turn.completed=1`.

## Evidence boundaries

- **Not scored:** report text/reproduction steps, ground-truth matches, TP/FP/FN, severity calibration, false positives, and model-level accuracy are not contained in this execution summary.
- Count of three candidate findings does not establish three distinct defects or show any rubric outperforming another.
- Token totals are consumption metrics, not invoiceable price; caching/billing details are not present.
- Synthetic cases and earlier inadvertent Git-history exposure of oracle-derived tests limit rigorous blinding. This is an exploratory engineering pilot only.
- User reports that all **12 Runner tests** and all **6 public fixture tests** passed after `e33e393`. These were operator-executed tests; they are not CI attestation.
- Never commit raw Codex transcripts, `output/`, model responses, private oracle, or session identifiers.
- No automatic endorsement, architecture milestone transition, or M6.0 acceptance follows.

## Next steps

1. Generate a human adjudication queue from private local `output/pctl-review-real-batch1-v6/` and independently verify findings with reproduction steps. Share sanitized queue only; keep oracle local and reviewer-inaccessible.
2. Proceed with preregistered jobs 4–6 (case-04) and 7–9 (case-05) in **fresh local ignored output directories**, keeping the same model and reasoning effort. No implicit reruns on HALTED.
3. Aggregate only **qualified**, independently adjudicated paired case×arm results. Three cases are exploratory and cannot support strong general claims.
