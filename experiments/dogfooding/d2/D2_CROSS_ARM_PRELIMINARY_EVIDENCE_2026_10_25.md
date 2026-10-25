# D2 paired dogfood — cross-arm preliminary evidence (2026-10-25)

Status: **BOTH_ARMS_VERIFIED / CTL_CANDIDATE_VALID / SEMANTIC_PARITY_UNREVIEWED / INTEGRATION_NOT_AUTHORIZED**.

This is a descriptive **single-pair** observation, not evidence of a
population-level speed, quality, cost or reliability advantage. Results below
are copied from the owner's sanitized output and previously verified
frozen-D2 research evidence. Private fixture files, prompts, raw model output,
quota and session logs remain only on the operator's machine.

## Common frozen contract and provenance

- Task: offline strict UTF-8 JSONL event parser, per-user activity
  aggregation and CLI. Source authority: `build_fixture.py` frozen SPEC
  and POLICY. Three allowed writes only: `d2events/cli.py`,
  `d2events/parse.py`, `d2events/report.py`.
- Same requested model `gpt-6-luna` / reasoning `medium`,
  `direct` strategy on CTL, network disabled, deny-all approvals, and 26
  protected tests. Distinct interfaces: Direct Codex CLI 0.163.0 vs
  CTL openai-codex SDK 0.160.0 and adapter 0.41.0.
- Direct base: `32836ea5633230e50fb9d907dcdba83e357bcfc6`.
  CTL policy base: `3c69dd42497acadadc5d64e7b4abe5d412b309f5`.
  CTL candidate: `fedc609d4d247f38e883fb72d72e6d8c9eb38376`,
  verified to be a single-parent descendant of policy base, with exact
  three allowed changed paths, matching durable RunStore/Evidence identity,
  a clean worktree, and unchanged `main`.
- Both completed exactly one paid coding Worker turn. CTL had two earlier
  admission-stage blocked Prepare attempts, with no Worker dispatch; Attempt 3
  passed Prepare, paid Worker and independent Verification. Do not merge the
  admission blocks into a purported paid-model retry count.

## Measured / reported values

| Metric | Direct CLI arm | ProjectCTL arm |
| --- | ---: | ---: |
| Coding Worker outcome | completed | implemented |
| Frozen unit tests | 26/26 | 26/26 |
| Scope violations | 0 | 0 |
| Changed files | 3 | 3 |
| Source lines in 3 files | 142 | 108 |
| Python AST nodes | 803 | 738 |
| Worker interval (s) | 32.809408731 monotonic | 33.908 event timestamp difference |
| Verification interval (s) | 0.165026099 independent tests | 1.084364 policy + verification |
| Input tokens | 196,969 | unavailable from canonical evidence |
| Cached input tokens (subset) | 185,088 | unavailable |
| Uncached input tokens (derived) | 11,881 | unavailable |
| Output tokens | 2,335 | unavailable |
| Reasoning output tokens (subset) | 243 | unavailable |
| Integration | not performed | not performed |

CTL uses 34 fewer source lines (`34/142 = 23.94%`) and 65 fewer
AST nodes (`65/803 = 8.09%`). This is **not** proof of better code:
parsing validation, exception safety and adversarial behavior must be
reviewed against the frozen SPEC. Different source hashes in all three
modules likewise do not prove semantic difference or superiority.

Difference between dissimilar Worker timing signals is 1.098591269
seconds, approximately 3.35% of the Direct measurement. These signals do
**not** share the same clock boundary: the Direct harness stored the
monotonic coding subprocess duration; CTL reported the interval between
`worker.started` and `worker.result` event timestamps. Both samples
number one; measurement uncertainty, caching and differing CLI/SDK
versions prevent a credible relative-performance claim.

Similarly, the Direct number reflects the independent test command,
whereas CTL's Verification duration includes scope/policy checks and
Candidate creation. The four ProjectCTL Verification checks represent
three internal controls plus the one required test command. The owner
independently confirmed the latter's bounded stdout/stderr SHA-256
digests and literal `Ran 26 tests` / `OK`, not merely exit code zero.

Direct source was previously reviewed against SPEC:
`D2_DIRECT_SEMANTIC_REVIEW_PASS_WITH_EDGE_RISK`, including an untested
deep-nesting `RecursionError` edge. Actual CTL source has **not** been
provided for equivalent semantic review. A paired functional and
security-oriented review must therefore remain pending, rather than
assigning a quality winner using line count or AST size alone.

## CTL source identities reported by owner

- `d2events/cli.py`: `9335cb9ee2f1068b2524717e7227d1bb11150475004be45802f893764f7e09a7`
- `d2events/parse.py`: `a148bcf3f469828ac0978791d127896c5625d91ce7d6c0b291912cf00c333a52`
- `d2events/report.py`: `c4f946c852d374b28a4e26b4ee97edfeaac5f41b005d9c72c64f3cd703c5e9c6`

## Next evidence gate

1. Read both three-file implementations directly from the preserved
   fixtures/candidate, verifying recorded source hashes. Obtain an
   independent **read-only** semantic review against frozen SPEC, including
   duplicate nested JSON keys, physical line-number/error sanitization,
   precise ASCII identifier rules and UTC calendar validity, order-insensitive
   report boundaries, deterministic CLI output and no network/extra writes.
2. Record any CTL timing/usage **only if grounded in durable artifacts**
   with matching identity and clocks. SDK WorkerResult has no token
   counters; do not infer or invent usage from the Direct arm.
3. Distinguish ProjectCTL audit/traceability benefit from project-wide
   latency/effort. Treat early failed admission and manual review gates as
   nonzero operational friction, without combining incomparable boundaries.
4. Owner adjudication of final candidate and any `run integrate` must
   remain separately authorized. No reruns/retries/re-verify/merge/publish.
