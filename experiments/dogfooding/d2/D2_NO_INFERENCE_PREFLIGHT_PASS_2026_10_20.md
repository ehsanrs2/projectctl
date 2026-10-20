# D2 no-inference paired execution preflight — operator PASS (2026-10-20)

**Observed decision:** `D2_NO_INFERENCE_PREFLIGHT_PASS`. The operator pulled the research branch `ef26192..7cde6fc` and executed the 13 offline tests in `experiments.dogfooding.d2.test_d2_no_inference_preflight`: **13/13 PASS**. The bounded preflight then returned the JSON decision above. Neither command started a coding worker, performed `projectctl run prepare`, claimed a Beads task, or requested paid model inference.

## Pinned operator evidence

| Contract | Observation |
|---|---|
| Frozen direct source baseline | `32836ea5633230e50fb9d907dcdba83e357bcfc6` |
| Local ctl policy commit | `3c69dd42497acadadc5d64e7b4abe5d412b309f5` |
| Canonical task | `d2ctl-g4q` |
| Direct-arm prompt SHA-256 | `b4aa6e48872f07d1d608bf24a5beeed45ac9e68656defc52aa8c632b63c50f65` |
| Declared paid arm order | `direct_cli` → `projectctl` |
| Model / reasoning | `gpt-6-luna` / `medium` |
| ProjectCTL Python SDK | `openai-codex 0.160.0` |
| ProjectCTL adapter | `projectctl.codex 0.41.0` |
| Independent Codex CLI | `codex-cli 0.163.0` |
| Worker strategy | `direct`, `version_only` probe |
| Security envelope | `workspace_write`, `deny_all`, `network=disabled`, default mode |
| Write scope | `d2events/cli.py`, `d2events/parse.py`, `d2events/report.py` |
| Frozen test definitions | 26 |
| Paid state | `NOT_AUTHORIZED_OR_STARTED` |

The read-only preflight also re-executed the frozen D2 local policy/source audit: the two fixtures remain suitable for the pre-run stage with the ctl Beads task unclaimed. It checks the independent CLI help flags, SDK and adapter versions, and the explicit direct strategy without starting an App Server coding turn.

## Scientific caveats and pending stages

- No first D2 pair has executed. All 26 acceptance test cases are frozen and were counted structurally, **not claimed passing on unimplemented stubs**.
- `version_only` capability evidence is not live runtime equivalence. SDK `0.160.0` and CLI `0.163.0` may have behavior, model/tool and prompt-envelope differences. Their requested model/effort identity remains to be observed when each arm actually runs.
- The fresh official quota from the **earlier** `2026-10-20T12:19:21Z` observation may age or change with unrelated account usage; both arms need new official quota/admission checks at the point of dispatch.
- Before any paid execution, construct and qualify a deterministic evidence harness that records UTC start/end, monotonic time, exit status, frozen-source hash checks, writes/ignored-files, independently frozen 26-test results, direct JSONL input/cache/output/reasoning usage (subsets not double counted), and SDK usage as *unknown* unless directly observed.
- Keep a frozen exact prompt SHA and predeclared arm ordering. The direct arm must not see ctl source/results and the ctl arm must not see direct output. Stop on any failure; no hotfix or retries in the same pair.
- Separate owner acknowledgement will be required for paid actions. No production/default branch change, fixture rewrite or remote publication.

**State:** `D2_NO_INFERENCE_PREFLIGHT_PASS / EVIDENCE_HARNESS_QUALIFICATION_PENDING / NO_INFERENCE`.
