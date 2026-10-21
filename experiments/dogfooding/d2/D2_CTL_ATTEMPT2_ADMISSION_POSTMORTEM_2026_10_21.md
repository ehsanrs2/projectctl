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

Status: POSTMORTEM_SOURCE_COMMITTED; OPERATOR_TESTS_PENDING; NO_RETRY.
