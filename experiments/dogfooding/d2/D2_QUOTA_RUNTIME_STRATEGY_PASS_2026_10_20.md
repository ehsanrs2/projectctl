# D2 quota admission + version-only Codex capability and direct strategy — observation (2026-10-20)

**Observed:** `D2_QUOTA_AND_STRATEGY_GATE_PASS` at the operator's `2026-10-20T12:19Z` observation, but **no paid turn, no run prepare, no Beads claim**. This is a point-in-time observation, not perpetual permission to execute.

## Operator evidence

The operator fast-forwarded `research/advisory-skills-eval` from `6090356` to `ef26192`, retained the isolated `PROJECTCTL_HOME=$HOME/.local/state/projectctl-dogfood-d2/ctl-home`, and called official `projectctl quota` and `next`, followed by version-only `worker capabilities`, `worker strategy d2ctl-g4q --requested direct`, and `codex --version`.

| Gate | Observed result |
|---|---|
| Quota source | `codex_app_server`, `official`, `high`, canonical bucket `codex`, `stale=false` |
| Snapshot time | `2026-10-20T12:19:21.059514Z` |
| Five-hour ratio | raw `1.0`, effective `0.9`; next reported reset `2026-10-20T17:19:20Z` |
| Weekly ratio | raw `0.85`, effective `0.75`; next reported reset `2026-10-27T06:34:16Z` |
| Ordinary use | `true`; scheduler quota mode `normal` |
| Scheduler decision | sole `d2ctl-g4q`: `eligible=true`, `reasons=[]`, `selected_task_id=d2ctl-g4q` |
| Selected model policy | profile `balanced`, reasoning `medium`, reason `task_complexity` (the already frozen ProjectCTL profile catalog pins balanced to `gpt-6-luna`) |
| Strategy | `compatible=true`, requested/resolved `direct`, `fallback_used=false`, `unsupported=[]` |
| Worker execution contract | `mode=default`, `sandbox=workspace_write`, `approval=deny_all`, `network=disabled` |
| Version-only SDK | `openai-codex==0.160.0` |
| Bundled Codex runtime | `openai-codex-cli-bin 0.160.0` |
| ProjectCTL adapter | `projectctl.codex 0.41.0` |
| Independent direct CLI | `codex-cli 0.163.0` |
| Capability snapshot digest | `canonical-json-sha256-v1:c5b9b80e55f0419159abd111d7a29a950c63221464c100483281c0acb9c2268b` |
| Quota snapshot digest | `canonical-json-sha256-v1:d5fb50b36f867527e7e4eb4c0d5ae544503eadafa58bd8626fa00f9ffb41f0c2` |

## What this does and does not establish

The SDK and independent CLI are **not the same runtime version** (`0.160.0` vs `0.163.0`) and have different transport/prompt wrappers. Therefore model-family identity and requested reasoning can be pinned in both arms, but a perfectly matched execution environment or same-token-budget inference **cannot** be claimed.

The version-only probe establishes a declared supported default mode, `workspace_write` and `deny_all` adapter compatibility. It does not attest that paid model service calls will work or prove identical actual tool/plugin exposure. The direct CLI's required isolation flags and model-help support must be checked separately and logged. Only SDK output explicitly showing usage can support any token comparison, otherwise ProjectCTL usage remains `unknown`.

The 26 independent acceptance test cases remain frozen and are not yet passing on either stub implementation. The presence of ready quota is **not** a reason to run the direct arm prematurely.

## Prepared research-only next step

The contract for the D2 first paired trial is **direct CLI first, then ProjectCTL**, opposite the order in D1. No code, prompt history or result is copied between arms; `direct` uses a fresh ephemeral Codex CLI execution and `ctl` its own independent SDK session with all verified policy controls. Both shall target `gpt-6-luna` and `medium` with workspace-write, denied approvals and disabled network. Direct and ProjectCTL differ in wrappers; the comparison report must disclose this.

`experiments/dogfooding/d2/d2_no_inference_preflight.py` is a new guarded read-only tool that runs the existing D2 frozen-file policy audit, pins the D0 venv, independently checks SDK 0.160 / adapter 0.41 / independent CLI 0.163, verifies direct CLI required isolation flags, tests worker strategy compatibility and derives the direct-arm prompt **only from the pristine direct fixture SPEC/POLICY**. It prints its SHA-256 (rather than immediately running Codex), preserving a prompt-envelope fingerprint for the future one-turn harness. `test_d2_no_inference_preflight.py` adds **13 defined pure offline tests**; these have **not** yet been executed in the owner's local environment.

The preflight intentionally does **not** read/write a fresh quota sample or create an attempt evidence directory. Quota freshness/admission must be checked immediately before *each* paid dispatch, especially since 15-minute snapshot age and concurrent account use can invalidate this observed selection. After qualification, separately implement/review an exact evidence harness (stdout/stderr/usage UTC/monotonic timing, frozen files, protected hashes, Git path inventories), and use **separate owner authorization** before any paid turn. On any mismatch or failure: stop and preserve evidence; do not hotfix within the same D2 pair.

**State:** `D2_POLICY_VERIFIED / QUOTA_AND_VERSION_ONLY_STRATEGY_PASS / NO_INFERENCE_PREFLIGHT_PENDING / PAID_EXECUTION_NOT_AUTHORIZED`.
