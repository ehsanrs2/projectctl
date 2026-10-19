# D1 paired dogfooding — final technical evaluation (2026-10-19)

**Decision:** `D1_PAIRED_EVALUATION_COMPLETE`. Both implementations are accepted against the frozen D1 contract. **No claim of ProjectCTL speed/quality superiority is supported** by this one-pair experiment. The research-patched ProjectCTL completed its full lifecycle after three pre-success orchestration failures. This document records an independent semantic review of the operator-supplied direct-arm source/diff; the direct fixture remains uncommitted.

**Scope:** ONLY isolated D1 `ctl` and `direct` fixtures, research branch `research/advisory-skills-eval`. Not M6.0 production/main; no production publication or merges.

## Frozen question and contract

Task: implement `normalize_user_id(value)` in `user_id.py`. Accept only `str`, strip surrounding whitespace, lowercase only ASCII A–Z (not Unicode casefold/lower), preserve non-ASCII characters and internal whitespace, raise `ValueError` for non-string or empty-after-trim. Never edit `SPEC.md`, `POLICY.md`, `test_user_id.py`, nor other source paths. Independent fixed test: `python3 -B -m unittest -v test_user_id.py`.

Common frozen `SPEC.md` SHA-256: `aac3d5e847cd24849e92860553459bae9f7cbf70cbf00073eba140270160253d`. `POLICY.md`: `ce2d1fa410a7ea3ba5eeb62d6e48610de44bcd84cadbc98f537b564918ed6e6d`. `test_user_id.py`: `ba12648bfa7357c501925b5fa1dd4f9685efaf9f44e748285716dd8579aa5a0f`.

Arms: `gpt-6-luna`, `medium` reasoning, workspace-write, tool network disabled; one arm executed at a time with independent repositories and control state. Actual request envelopes differ: ProjectCTL invokes pinned Python SDK with structured output; direct arm invokes Codex CLI 0.163.0 in a fresh one-turn session with a frozen direct-only prompt. Differences in interface/prompt prohibit treating timings as a controlled model-runtime benchmark.

## Final results

| Evidence | ProjectCTL (research-patched) | Direct Codex CLI |
| --- | --- | --- |
| Arm baseline Git source | `da9379c70571c9366f5adfccecdfab148c814fc2` pre-setup; project-scoped setup HEAD `7388896be4a7ba46770ae76c7cd5480f0cd9e27b` | `da9379c70571c9366f5adfccecdfab148c814fc2` |
| Model / reasoning | `gpt-6-luna / medium` | `gpt-6-luna / medium` |
| Attempts until success | **4** (3 failed / blocked first) | **1** |
| Completed accepted coding turn | **1**, D1-R3 | **1**, first attempt |
| Successful worker command wall time | **24 s**, `run start` | **15 s**, `codex exec` |
| Scope | only `user_id.py` | only `user_id.py` |
| Frozen tests | **6 / 6 pass** | **6 / 6 pass** |
| Independent semantic source review | pass | pass |
| Protected files | unchanged; SHA match | unchanged; SHA match |
| End state | `run=passed`, Beads `closed`, candidate integrated locally | `user_id.py` edited in direct working tree, no commit |
| Final target HEAD | `2089c04c5fc679cfb4353a2cef2c2f25c83fa40d` | `da9379c70571c9366f5adfccecdfab148c814fc2` |
| Remote delivery | none | none |
| Token usage | **unknown** in supplied operator evidence | 56,720 input (50,304 cached, 6,416 uncached), 438 output (64 reasoning output subset) |
| Retries | no automatic retries | zero retries |
| Human interventions | defect diagnosis, research fixes, task adjudication/reopen, repeated manual experiment gates | first-turn launch, result review |

### Direct-arm raw observation

Operator ran the pinned script `experiments/dogfooding/d1_direct_cli_manual.sh`. Preflight passed; single `codex exec` invocation from **2026-10-19T12:23:50Z** to **12:24:05Z**, wall **15 s**, exit 0. JSONL: `thread.started=1`, `turn.started=1`, `turn.completed=1`, no errors, no malformed lines. Recorded usage `input_tokens=56,720`, `cached_input_tokens=50,304`, `cache_write_input_tokens=0`, `output_tokens=438`, `reasoning_output_tokens=64`. Cached input is part of total input; reasoning is not an additional output category to be blindly added. Frozen test six cases passed, direct HEAD unchanged, only `M user_id.py`, no remote. This is **not** evidence of a commit on direct.

### ProjectCTL arm execution history (retain every attempt)

| Attempt | Run | Failure or success | Repair/gate |
| --- | --- | --- | --- |
| Original stock-research preclaim | `run-88361fe2431e4e299a0f4b9c506c50fa` | `failed/quota_exhausted` before worker, despite fresh sufficient official quota and Scheduler allowing the generic Task | Execution quota checked raw `UNKNOWN`; Scheduler normalized `UNKNOWN→MEDIUM`; fixed all execution quota revalidation sites via `effective_resource_class(task)` |
| D1-R1 patched | `run-10e606ca532c403487131ea092db232c` | `needs_decision/capability_changed` before `adapter.start`; Beads task reconciled `blocked` | `prepare` version `0.160.0` versus live `0.160.0 (Ubuntu 24.4.0; x86_64) Konsole/230805 (projectctl; 0.41.0)`; compare leading semver while retain raw evidence and sensitivity to actual SDK/runtime changes |
| D1-R2 patched | `run-b5785a14e0ab4961a970c43b0dc2b303` | `failed/worker_error` following provider HTTP 400 `invalid_json_schema`: `required` missing `blockers`; request rejected, no valid task response | Send dedicated strict wire-schema with all object properties required and `additionalProperties=false`, without changing semantic Pydantic validation |
| D1-R3 patched | `run-e467c1fa8f0f448b8497c9530c49b326` | worker `implemented`, `verifying`, all four ProjectCTL verification gates passed, candidate `2089c04c5fc679cfb4353a2cef2c2f25c83fa40d`, local integration `passed`, Beads closed | Success with all three research fixes, not a success attributable to unpatched M6.0 |

D1-R3 successful `run start` command ran **2026-10-19T11:32:46–11:33:10Z** and reported **24 s**; fixed verification invoked after independent worker completion and passed `diff-policy`, `execution-write-scope`, `fixed-unittest`, `workspace-stability`, with no policy violations. Integration invoked **11:59:12Z**; result `task_completed=true`, `worktree_cleaned=true`, `remote_publication=false`, `claim_released=false` (expected Beads task-native closure in this mode). Result `passed` confirmed, `ctl` HEAD matches candidate, `direct` source baseline unaffected.

## Independent review: exact code produced by each arm

ProjectCTL:
```python
def normalize_user_id(value):
    if not isinstance(value, str):
        raise ValueError("user ID must be a string")

    normalized = value.strip().translate(str.maketrans(
        "ABCDEFGHIJKLMNOPQRSTUVWXYZ",
        "abcdefghijklmnopqrstuvwxyz",
    ))
    if not normalized:
        raise ValueError("user ID must not be empty")
    return normalized
```

Direct:
```python
def normalize_user_id(value):
    if not isinstance(value, str):
        raise ValueError("user ID must be a string")

    normalized = value.strip().translate(str.maketrans(
        "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"
    ))
    if not normalized:
        raise ValueError("user ID must not be empty")
    return normalized
```

**Semantic adjudication:** equivalent code. The only difference is the wrapping of two constant string arguments to `str.maketrans`; no control flow, data, or API change. `isinstance(value, str)` enforces type; `strip()` trims surrounding whitespace; `str.maketrans(A..Z, a..z)` plus `translate()` maps only ASCII uppercase and preserves interior spaces and Unicode letters; empty-after-trim raises `ValueError`. No extraneous writes observed in either arm. Six frozen tests per arm passed. Output quality **ties at this task's acceptance boundary**; do not infer exact equivalence on all conceivable Unicode/edge behavior beyond code review and the frozen tests.

Direct operator's read-only audit concluded `D1_DIRECT_CANDIDATE_AUDIT_READ_ONLY_PASS__PENDING_SEMANTIC_ADJUDICATION`, which is closed by this source review. `source_equal=no` in the audit means **byte-for-byte format differs**, not behavior differs. Direct's `user_id.py` remains uncommitted deliberately.

## What D1 shows / does not show

1. **Feasibility:** A research-patched ProjectCTL can govern a Codex task from Beads readiness and quota admission through isolated worker, independent verification, candidate commit, local integration and task closure; its execution boundaries operated for this fixture.
2. **Observed reliability in this exercise:** Four ProjectCTL attempts were required because of three distinct implementation defects, compared with one direct CLI attempt. Do **not** reduce this to a universal per-task failure probability, or count research-driven reruns as typical end-user throughput.
3. **Value added:** ProjectCTL supplies traceable selection, quota policy, durable run/claim, scope governance, independent verification, evidence and controlled integration. For a tiny deterministic function, the direct CLI achieved the same acceptance criteria without those control-plane steps.
4. **Speed:** 24s vs 15s is only successful worker-command wall time, not an apples-to-apples end-to-end performance experiment. The ProjectCTL run additionally required preparation, separate verification/integration, bug diagnosis/patches and owner gates; these overheads were not comprehensively stopwatch-measured. The overhead observed here is **operationally substantial**, but a quantitative total speed ratio would be unsupported.
5. **Token/cost:** Direct reported usage; successful SDK ProjectCTL usage was not supplied in comparable form. A numerical token/cost ratio is unavailable, and cached tokens/reasoning must not be double-counted.
6. **External validity:** One small function, one pair, two differing prompt/orchestration surfaces, serial runs at different times. No statistical significance and no strong claim about harder tasks, multi-task scheduling or long-running recovery.

## Recommended follow-on decision

**Close D1 research experiment; do not run more paid turns for this fixture.** Preserve all artifacts, even failed/blocked Run history. Treat three source fixes as *research-qualified by this D1 evidence only*. Before proposing any production M6.0/main promotion, run full relevant offline regression/CI and design/security review on a separate promotion gate; no branch merge or default-branch write is authorized by D1.

A subsequent D2 should use a more realistic multi-file but still bounded task with several independent checks and a fully frozen evidence/metric contract. Pre-declare comparable model/runtime settings, independently equivalent prompt content, exact start-to-finish clock definitions, human-intervention counts, input/output/cache usage extraction for **both** paths, and a no-repair/no-hotfix qualification window. Separate ProjectCTL's intentional governance latency from inference latency; use more paired replicates before drawing a productivity claim.

## Source artifact pointers (operator-local)

- `experiments/dogfooding/D1_PLAN.md`
- `experiments/dogfooding/D1_R3_INTEGRATION_PASS_2026_10_19.md`
- `experiments/dogfooding/D1_DIRECT_CLI_FIRST_RUN_2026_10_19.md`
- `experiments/dogfooding/d1_direct_candidate_audit.sh`
- `$HOME/.local/state/projectctl-dogfood-d1/observations/ctl-attempt-4/` and `$HOME/.local/state/projectctl-dogfood-d1/observations/direct-attempt-1/`

**Research final status:** `D1_PAIRED_EVALUATION_COMPLETE` with no production deployment and no additional experiment execution authorized.
