# D1-R3 — independent candidate adjudication and integration approval (2026-10-19)

**Decision:** `D1_R3_CANDIDATE_APPROVED_FOR_LOCAL_INTEGRATION`. The **human/operator must still invoke the separate integration command**; neither integration nor a direct-arm turn has yet been observed.

## Operator read-only candidate audit

- Audit script `experiments/dogfooding/d1_r3_candidate_audit.sh --read-only` returned `D1_R3_AUDIT_READ_ONLY_PASS__NO_INTEGRATION`.
- Run `run-e467c1fa8f0f448b8497c9530c49b326` remains `ready_to_integrate` with candidate `2089c04c5fc679cfb4353a2cef2c2f25c83fa40d`.
- Candidate is single-parent on `7388896be4a7ba46770ae76c7cd5480f0cd9e27b`, with only `user_id.py` modified; `ctl` root still at setup HEAD, `direct` still at frozen baseline `da9379c70571c9366f5adfccecdfab148c814fc2`.
- `SPEC.md` SHA-256 `aac3d5e847cd24849e92860553459bae9f7cbf70cbf00073eba140270160253d`, `POLICY.md` SHA-256 `ce2d1fa410a7ea3ba5eeb62d6e48610de44bcd84cadbc98f537b564918ed6e6d`, and `test_user_id.py` SHA-256 `ba12648bfa7357c501925b5fa1dd4f9685efaf9f44e748285716dd8579aa5a0f` match across `ctl`, `direct` and candidate.
- ProjectCTL verification manifest `overall_pass=true`, no policy violations; `diff-policy`, `execution-write-scope`, `fixed-unittest`, `workspace-stability` all passed. `fixed-unittest` invoked `python3 -B -m unittest -v test_user_id.py`, exit 0, six tests passed in frozen output.
- Candidate patch digest recorded as `sha256:bf6f65a2b89b1b67c7bf47207e32f1fc453ccbff8eebf6a6e44d11bc09218b06`. The candidate did not mutate Git history prior to Verification.

## Independent semantic review

The exact candidate implementation is:

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

The reviewer checked each frozen requirement: strings only and `ValueError` for others; trim surrounding whitespace; map **ASCII A-Z only** to lowercase (rather than using Unicode-aware `str.lower`); preserve non-ASCII glyphs and internal whitespace; `ValueError` on blank-after-trim, and no edits to policy, spec or protected tests. The source satisfies the requested narrow behavior. The six frozen tests also passed. The approval is for this **single candidate and disposable local D1 fixture**, not a broad claim of formal correctness across all string inputs or untested products.

## Integration behavior (checked against source)

`projectctl run integrate` with `code_transport.mode=local` and `code_delivery.mode=local` fast-forwards the **local `ctl` integration target** to the pinned candidate commit, completes the Beads task using the persisted evidence, changes Run status to `passed`, and attempts candidate Worktree cleanup. No network publication or push is required. In Beads' task-native claim model, `claim_released=false` in the final manifest may be expected after task closure; it is not proof of a leaked active claim. Validate the completed task and manifest separately.

An operator-invoked guarded script `experiments/dogfooding/d1_r3_integrate_manual.sh` is prepared for at most one integration. It checks pinned run/base/candidate, worktree and protected paths, Beads in-progress task, prior verification, and root/direct fixtures, then integrates exactly once. It does not call the worker, re-verify, reset Git, launch the direct arm, or retry on failure. Observe and preserve any partial integration failure without destructive recovery.

## Scientific record

Original-runtime ProjectCTL attempt blocked on resource-class mismatch, D1-R1 on false capability-version banner mismatch, D1-R2 on strict JSON-schema HTTP 400. D1-R3 passed worker, all independent fixed tests and human source review after research patches. These failures, manual interventions, setup/engineering time, and unmeasured token usage must remain in the D1 comparative worksheet. The **direct Codex CLI arm remains unrun**; no full paired comparison or productivity superiority claim is yet possible.
