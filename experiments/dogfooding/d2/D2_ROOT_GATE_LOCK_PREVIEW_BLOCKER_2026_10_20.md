# D2 adoption preview: root Beads gate-lock observed (2026-10-20)

**Operator result:** The 13 existing offline `test_gitignore_review` tests passed. Re-running `d2_adopt_projectctl_manual.sh --preview` then stopped before Commit or ProjectCTL initialization with:

```text
ValueError: Ignored paths outside Beads operational metadata: ['.beads.gate.lock']
```

The prior `.gitignore` snapshot mismatch is no longer observed. The new blocker arises because the pinned Beads 1.3.1 root-level file `.beads.gate.lock` is ignored by the Beads-added pattern `*.gate.lock*`, but the strict ignored-path classifier enumerated `.beads/`, `.dolt/`, and `.beads-credential-key` only. This is **a pre-adoption validator failure**, not evidence of a model/ProjectCTL runtime failure. The file contents, device ownership and task post-state are not independently observed from the user's output.

## Narrow research repair

The follow-up change in `experiments/dogfooding/d2/gitignore_review.py` allows **exactly the root-relative name** `.beads.gate.lock` and nothing matching variants or suffixes. It does not accept arbitrary `*.gate.lock*`, `*.db`, or unrelated ignored application files. A companion `validate_root_beads_gate_lock(root, ignored_paths)` enforces that the observed root lock is an existing regular non-symlink file, not a directory or symlink; if that path is not observed there is no requirement it exist.

The D2 adoption preview and adoption execution use this same validation before any Git write. Extra tests cover exact-name acceptance, suffix/prefix/nested lookalikes, unrelated gate locks, and real regular-file/absent/directory/symlink cases. The regression suite is now **21 tests defined**, not yet confirmed executed by the operator. The previous 13 passed before this new patch.

No change was made to the frozen 11-file D2 application baseline, pinned Beads task `d2ctl-g4q`, direct fixture, ProjectCTL runtime, D1 records, or main. No paid model call was made.

## Next operator gate

1. Fast-forward research branch and run `$HOME/.local/share/projectctl-dogfood-d0/venv/bin/python -B -m unittest -v experiments.dogfooding.d2.test_gitignore_review`. Require **21/21** passing.
2. Re-run `bash -n experiments/dogfooding/d2/d2_adopt_projectctl_manual.sh` and `bash experiments/dogfooding/d2/d2_adopt_projectctl_manual.sh --preview`. Require:
   - `D2_BEADS_GITIGNORE_REVIEW_PASS`
   - `root_beads_gate_lock_observed=true` when the lock still exists (may be `false` if a transient lock disappeared)
   - `ignored_application_paths_checked=true`
   - `D2_CANONICAL_TASK_OPEN_UNCLAIMED`, `D2_SOLE_TASK_READY`, `D2_PREVIEW_PASS`
   - `PREVIEW_ONLY__NO_GIT_COMMIT_NO_PROJECTCTL_INIT`.
3. Only after confirming a clean preview, the existing separately acknowledged `--adopt --ack-local-git-commit` may be executed once. Fail closed on new mismatches; do not rerun `bd init`/`bd create` or reset any D2 fixture.

**Recorded decision:** `D2_ADOPTION_PREVIEW_BLOCKED_ROOT_GATE_LOCK_CLASSIFICATION`; offline repair prepared for operator qualification. ProjectCTL adoption, three-file write-scope/verification freeze and both paid arms remain pending.
