# D2 paired dogfooding: offline JSONL event aggregator

**Status:** D2_CONTRACT_PROPOSED / NO LIVE OR PAID EXECUTION AUTHORIZED.
**Isolation:** research/advisory-skills-eval only. Neither D1 fixture, production M6.0/main, user home ProjectCTL state, nor any shared Codex session is a D2 fixture.

## Why this task

D1 proved the corrected ProjectCTL lifecycle was feasible, but its one-function task was too small to quantify benefit. D2 uses a realistic *three-source-file* Python change with validation, aggregation, CLI, protected independent tests, and explicit negative paths. We ask whether control-plane governance improves traceability, scope and safety, and measure its effort/cost relative to direct Codex CLI. The task is not designed to artificially favor either arm.

## D2 feature contract

Implement an offline activity summary for line-delimited JSON events, using **Python standard library only**. Input is a sequence of lines, one JSON object per nonblank line with exactly these keys: event_id, timestamp, user_id, action (all strings). Unknown or missing keys fail. Reject duplicate JSON keys, duplicate event IDs across lines, malformed JSON, wrong types, invalid IDs, impossible dates, unexpected actions and invalid timestamps. Ignore whitespace-only lines.

- event_id: ASCII 1..32 characters [A-Za-z0-9-], unique case-sensitively.
- user_id: strip leading/trailing whitespace, must match ASCII [A-Za-z0-9_-]{1,32}; canonicalize letters A-Z to lowercase; preserve distinct other valid symbols. Reject whitespace inside.
- timestamp: exact UTC seconds format YYYY-MM-DDTHH:MM:SSZ; reject offsets, fractions, leap seconds, invalid calendar dates; validated and normalized to the same exact representation.
- action: exactly one of login, logout, purchase; case-sensitive.
- parse_events(lines): in d2events/parse.py, returns a list of dictionaries with the four typed canonical fields; errors raise ValueError mentioning the original 1-based physical line number (no raw input echoed).
- build_report(events): in d2events/report.py, consumes the canonical parser result, returns {total_events:int,users:list[object]}. Each user object has user_id, login, logout, purchase, first_seen, last_seen. Unique users sorted by canonical user_id ascending. Min/max timestamps are chronological UTC (lexicographic works for fixed format). Empty input returns {total_events:0,users:[]}.
- CLI: python3 -B -m d2events.cli PATH. Read UTF-8 text from PATH; output exactly one compact JSON line with keys sorted and no whitespace padding, followed by newline; no stdout on error; malformed events, missing files or decoding errors: exit 1 and a concise diagnostic on stderr (no raw line data). Argument errors: argparse exit 2. No network, no writes except allowed stdout/stderr.

Only these three source paths may change: d2events/parse.py, d2events/report.py, d2events/cli.py. Protected paths: SPEC.md, POLICY.md, d2events/__init__.py, tests/** and all ProjectCTL control-plane files. The starter functions deliberately raise NotImplementedError. Tests are frozen by the builder before coding.

## Frozen verification and acceptance

From the fixture repository root:

    python3 -B -m unittest discover -s tests -p 'test_*.py' -v

Pass criteria: all independent tests exit zero; no out-of-scope file modifications; no git history changes caused by worker; valid result at permitted paths; source semantic review against frozen contract; protected digests identical to initial baseline. Negative tests are as important as happy path. On ProjectCTL, its *independent* verification owns the candidate commit and subsequent human-approved integration. Direct arm never auto-commits.

## Experimental methodology

1. **Offline qualification and freeze (now):** Review builder, contract and test corpus for internal consistency, run offline builder on two **new** external directories in an operator-selected D2-only root, confirm identical base commits, spec/test SHA-256 and clean status; static check all fixture stubs and tests. Do not use preexisting D1 fixtures. Review actual locally installed CLI and SDK versions before pinning exact D2 execution parameters. Do not manufacture test-pass on stubs.
2. **Setup, frozen control-plane:** Configure isolated D2 ProjectCTL home, local-only Beads task authority in the ctl arm, required scope allowing exactly 3 source files, verification profile using fixed command. Freeze task snapshot/source hashes, project config, model and reasoning. Validate scheduler, quota (actual fresh official observations), capability and code-delivery policy. Source control-plane fixes from D1 may be used *as is*; **no fixes during either arm**.
3. **Paired execution:** One arm at a time. Use a fresh Codex session per arm. Same task definition and frozen files, explicit gpt-6-luna / medium, workspace-write, network disabled, approval denied, same tool/plugin-disabled assumptions insofar as supported. Direct arm prompt uses SPEC verbatim; ProjectCTL task description uses SPEC verbatim, with recorded system-policy wrapper differences. Do not copy source solution or context across arms. Ordering must be predetermined and recorded before starting (recommended alternate D1 order, direct then ctl for first D2 pair).
4. **No-hotfix window:** If either arm fails due to CLI/SDK/config, code defect, unexpected edits, policy, quota or timeout, capture evidence and **stop**. Do not fix ProjectCTL or change the task mid-pair and treat a retry as the same sample. Any subsequent D2-R1 design needs a fresh frozen pair, explicit owner authorization and labeled deviations.
5. **Metrics:** UTC start/end at prepare/start/verify/integrate and direct exec/tests; monotonic elapsed seconds for each command; optional end-to-end wall (from preflight to acceptance, excluding operator wait only if both arms use equivalent clock boundaries); total manual interventions and failed starts; number of model turns/retries; changed paths and line count; frozen tests, semantic quality; quota/admission failure and policy issues; token usage including input, cached-input subset, output and reasoning subset *per arm*. If Python SDK usage is not available in ProjectCTL durable artifacts, mark unknown; do not infer parity with direct. Preserve sanitized raw evidence in separate D2-only directories.
6. **Evidence and adjudication:** Do not adjudicate solely from tests; independently review actual source/diff and manifests, including protected files and disabled network. ProjectCTL controls integration and closes Beads only after independent verification and owner approval; direct source remains uncommitted during paired measurement. Keep run failures in report, not just final success. No remote publication.
7. **Interpretation:** Single pair is a feasibility signal; D2 should plan at least three independent task/seed replications for any directional latency/reliability inference, frozen *before* measurement. Without replicates, report descriptive differences only. Metrics must distinguish model processing from orchestration, test and human gates.

## Acceptance gates for starting live D2

- Two newly built D2 fixtures, equal baseline content and protected hashes.
- 100% offline builder smoke; test suite plausibly fails against explicit stubs (do not claim acceptance test passes before work).
- Exact supported runtime flags, SDK/Codex versions verified locally, model/reasoning identity and network/sandbox permissions pinned.
- One ProjectCTL candidate task, exactly scoped local authority, no dirty repositories, correct verification profile.
- Sufficient fresh quota and no concurrent claims; deterministic timing/evidence harness.
- Manual owner approval for any paid execution; this D2 document is not paid authorization.

**State at creation:** PLAN_AND_FIXTURE_ENGINEERING. No D2 fixture has been created on owner's workstation; no paid Codex turns.
