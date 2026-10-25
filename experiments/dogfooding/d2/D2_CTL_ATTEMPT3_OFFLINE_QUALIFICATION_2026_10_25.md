# D2 Attempt 3 — offline qualification operator instructions

Scope: only an offline synthetic and read-only evidence/fixture preflight.
Owner approved implementation of offline checks; owner did NOT approve a
live quota query, Scheduler resample, task Claim, Prepare, Worker or Attempt-3
execution. No production module or frozen fixture is edited.

New modules:
- d2_ctl_attempt3_offline.py: pure ordered-admission simulation and
  --preview of retained attempts and current frozen CTL/Direct readiness.
- test_d2_ctl_attempt3_offline.py: synthetic safety/negative-path tests.

The module intentionally has NO --prepare or --execute option. Preview uses
Git/Beads/ProjectCTL read-only commands through the established readiness
audit, which can refresh local operational caches but never invokes a
provider, creates a Run, claims Beads, or starts an LLM.

The independent quota policy simulation does NOT claim to have consumed
a live provider snapshot. A future approved one-shot Prepare runner requires
separate code review, actual QuotaSnapshot/Pydantic validation, proof that
Scheduler time/config/tasks match the frozen target, and owner authorization.

The existing Attempt-1 and Attempt-2 evidence directories are permanent,
single-use and must never be overwritten. Attempt-3 Prepare evidence path
must remain absent. The new operator launcher (d2_ctl_attempt3_offline_manual.sh)
is single-use but writes only to a different offline qualification directory;
it checks historical hash preservation even on failure.

After syncing the research branch, review the full 40-char current SHA then:

    cd /home/ai/project/My/projectctl-advisory-lab
    PIN='<exact-reviewed-40-character-new-head>'
    bash experiments/dogfooding/d2/d2_ctl_attempt3_offline_manual.sh \
      --expected-head "$PIN"

The launcher performs AST syntax validation, the exact synthetic test suite,
then a real D2 read-only preview, and saves only sanitized JSON, test output,
source hashes and integrity reports in its 0700 offline evidence directory.
It does not run live quota or alter the CTL fixture.

Expected success:
D2_ATTEMPT3_OFFLINE_QUALIFIED__PREPARE_NOT_AUTHORIZED

On failure, preserve the new qualification identity and report its final
decision and failing step. Do not rerun the same identity. No Prepare and
no Worker are authorized by a green offline result.

Future separately approved live Attempt-3 code must stop before any second
quota/Scheduler sample when the first sample fails the frozen MEDIUM
thresholds, and must issue at most one Prepare dispatch if all gates pass.


## Owner-reported result and follow-on candidate (2026-10-25)

The owner ran the exact one-time offline launcher on research commit
`c9cafddd1b0973b3e6fbb83ca1caa760928edd38`. Reported terminal:

- `D2_ATTEMPT3_SYNTAX_PASS`
- synthetic suite step completed and its 36-test + `OK` checks passed
- `D2_ATTEMPT3_OFFLINE_PREVIEW_CONTRACT_VALIDATED`
- `D2_ATTEMPT3_OFFLINE_QUALIFIED__PREPARE_NOT_AUTHORIZED`
- evidence location: `observations/ctl-attempt3-offline-qualification`

These are owner-supplied outputs; the reviewer did not have direct access
to the private evidence directory. This one-time qualification must NOT
be rerun. A later source change does not relabel/recreate that evidence.

Subsequent research-only code staging produced
`d2_ctl_attempt3_prepare_once.py`, its 15 synthetic tests, and
`D2_CTL_ATTEMPT3_PREPARE_STAGING_2026_10_25.md`.
They intentionally bind to the historical qualification SHA, independently
recheck frozen D2 readiness, require an exact new research HEAD, and
check official first quota BEFORE calling Scheduler in a future,
separately-authorized Prepare. The Scheduler must select the frozen sole
task, and its task/config identity must match current canonical authority.
No live Prepare was authorized or executed here. New candidate tests and
Preview still require the owner's real D0 environment qualification.
Status: OFFLINE_QUALIFIED_BY_OPERATOR; PREPARE_CANDIDATE_STAGED;
PREPARE_NOT_AUTHORIZED; WORKER_NOT_STARTED.
