# D2 Attempt-2 admission: retained-evidence-only postmortem

The operator reported D2_CTL_ATTEMPT2_PRECLAIM_BLOCKED__NO_RETRY at
failure_stage=admission; no Prepare dispatch, run or Worker. The permanent
Attempt-2 evidence directory must not be deleted or reused.

This R&D-only script reads saved JSON from the existing Attempt-2 attempt;
it does not call Provider, Scheduler, Git, Beads or Codex, and writes nothing.
It distinguishes first official quota predicates from the independently sampled
Scheduler decision, and compares the scheduler digest with the canonical
unknown fallback digest without printing account credentials or raw payloads.
The original Provider exception type may remain unknown. The calculated
quota age at attempt finish is approximate, not the admission instant.

After a separate ordinary git pull, operator should run ten synthetic tests:

    cd /home/ai/project/My/projectctl-advisory-lab
    /home/ai/.local/share/projectctl-dogfood-d0/venv/bin/python -B -m unittest -v \
      experiments.dogfooding.d2.test_d2_ctl_attempt2_admission_forensics

If tests pass, execute read-only historical inspection only:

    /home/ai/.local/share/projectctl-dogfood-d0/venv/bin/python -B -m \
      experiments.dogfooding.d2.d2_ctl_attempt2_admission_forensics --inspect

Do NOT run Attempt 2 Prepare again, refresh Provider for historical diagnosis,
reset frozen fixtures, or initiate Attempt 3 without separate owner authorization.

Status: POSTMORTEM_CONFIRMED_BY_OPERATOR; ATTEMPT2_NO_DISPATCH; NO_RETRY.

## Operator-observed historical result (2026-10-21)

The owner ran the read-only diagnostics on pinned research HEAD
`1ae6ab25c727d0b40117f3058b5a94a66ab53b54` and reported:
`SYNTAX_PASS`, `Ran 10 tests ... OK`, followed by
`D2_CTL_ATTEMPT2_ADMISSION_FORENSICS_COMPLETE__READ_ONLY`.
These are operator-supplied terminal observations, not a direct read of
the owner's local private artifacts by the repository reviewer.

Sanitized findings:

| Saved predicate | Observed |
| --- | --- |
| Attempt | 2 |
| Failure stage | admission |
| First quota mode | conservation |
| Scheduler quota mode | conservation |
| Candidate eligibility rejection | quota_insufficient |
| Five-hour MEDIUM effective-floor check | false |
| Weekly MEDIUM effective-floor check | true |
| First-quota *combined* official/normal predicate | false |
| Scheduler selected the frozen task | false |
| Scheduler digest relative to first quota | different_snapshot_or_unclassified |
| Sample age at attempt finish (not admission instant) | approximately 4.39 seconds |
| Prepare dispatched / Run ID / Worker | false / null / false |

**Interpretation:** Attempt 2 was blocked by the admission policy before any
Prepare dispatch. The evidence specifically identifies an insufficient
five-hour MEDIUM admission condition and a Scheduler `quota_insufficient`
reason. The combined official/normal predicate failing does **not** alone
prove provider failure, stale data or non-official provenance. Likewise,
the floor predicate being false does not distinguish an unavailable ratio
from one below the minimum without examining additional retained evidence.
The independent Scheduler digest being neither the first official digest
nor its derived canonical unknown digest does **not** establish a
particular provider fault: independently sampled snapshots may differ.
The absent model selection is downstream of task ineligibility, not
independent proof of a model-profile mismatch.

**Comparison:** Attempt 1 ended with Scheduler `quota_unknown` and a
canonical synthetic unknown quota digest. Attempt 2 ended with
`quota_insufficient` and a five-hour floor failure. These are two distinct
observed exclusion mechanisms; they must not be merged into a single claimed
root cause. Neither CTL attempt reached model execution, so D2 currently
has no paired CTL worker-quality, token-use, or wall-time evidence.

**Decision: NO-GO for any reuse or automatic retry.** Treat both historical
attempts as immutable censored/pre-dispatch observations. Do not relax quota
thresholds, override Scheduler selection, reset the evidence directory,
replay old approvals or run Attempt 3 without an independently defined and
authorized contract. If continued paired evaluation is still desired,
perform a separate offline design review for the next *new* attempt,
with new evidence identity and fresh admission checks; do not use a live
quota probe retroactively to change this historical diagnosis.

