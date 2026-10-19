# D1-R3 verification result and pending independent candidate review (2026-10-19)

**Decision:** `D1_R3_VERIFICATION_PASS__PENDING_HUMAN_ADJUDICATION`. **NOT YET INTEGRATED.**

## Evidence reported by operator

The operator fast-forwarded the research branch to `40d11d0`, syntax-checked and executed the single-run `experiments/dogfooding/d1_r3_verify_manual.sh --verify` script against the frozen `ctl` fixture.

- Run: `run-e467c1fa8f0f448b8497c9530c49b326`.
- Pre-verification scope check: **PASS**, exactly one changed workspace path, `user_id.py`.
- One independent `projectctl run verify RUN_ID --project CTL --json` invoked at **2026-10-19T11:42:56Z**; verification returned `overall_pass=true`.
- All four required checks passed: `diff-policy`, `execution-write-scope`, `fixed-unittest` (fixed `python3 -B -m unittest -v test_user_id.py` exit 0), `workspace-stability`.
- Run transitioned to **`ready_to_integrate`**, candidate commit **`2089c04c5fc679cfb4353a2cef2c2f25c83fa40d`**.
- Candidate is a single-parent commit directly on `ctl` setup base **`7388896be4a7ba46770ae76c7cd5480f0cd9e27b`**; isolated candidate diff is only `user_id.py`.
- The root `ctl` integration-target HEAD remained unchanged at the setup base; `ctl` Git status clean and no remote. Integration has not occurred.
- Script status `D1_R3_VERIFICATION_EXIT=0`. Evidence: `$HOME/.local/state/projectctl-dogfood-d1/observations/ctl-attempt-4/verification/`, including `candidate.patch`, `worker-user_id-before.py`, `verify.json`, `verification-manifest.json`, `evidence-manifest.json` and `fixed-unittest.stderr.log`.

## Limitations and next gate

The user has reported structural correctness and passing frozen tests, **but has not yet supplied the actual candidate source/diff** to the assistant for independent code review. Do not assert that semantic edge cases pass beyond the frozen tests; do not independently conclude human adjudication or authorization for integration based solely on status.

The next step is a **read-only audit** that prints the actual isolated candidate source/patch, immutable protected-file SHA digests, and fixed-test results. Review it against frozen `SPEC.md`, `POLICY.md`, and test file, and then decide on one explicitly manual `projectctl run integrate`. Until that decision, leave the run at `ready_to_integrate` and do not mutate Beads or source Git history manually. `direct` arm remains untouched.

## Evaluation context

Original stock-runtime `prepare` was blocked by inconsistent unknown resource class; patched D1-R1 was blocked by a live-version banner; patched D1-R2 was blocked by invalid Codex strict-output schema. D1-R3 worker completed and passed verification. All earlier failures/diagnostic time and engineering interventions must remain part of the orchestration comparison. This is a one-pair feasibility dogfood result, not statistically generalizable.
