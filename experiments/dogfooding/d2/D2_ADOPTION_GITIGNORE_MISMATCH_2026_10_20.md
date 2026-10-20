# D2 ProjectCTL adoption preview — Beads 1.3.1 ignore policy mismatch (2026-10-20)

**Observed:** `bash -n` passed. `d2_adopt_projectctl_manual.sh --preview` exited at read-only Python assert `Unexpected Beads .gitignore entries` before either `git add/commit` or `projectctl init`. **No integration, no Codex call, no Beads task recreation.** The D2 local Task `d2ctl-g4q` and frozen `ctl/direct` application baseline are preserved pending operator revalidation; Task status after the failed preview has not been separately read, so do not invent post-failure task state.

## Exact operator-observed additions

```gitignore
.dolt/
*.db
.beads-credential-key
.beads/proxieddb/
*.gate.lock*
```

The original research helper only permitted `.dolt/`, `.beads/proxieddb/` and a few other path-specific patterns; it was too narrow for the actual pinned local `bd 1.3.1` init output. This is a **fixture-validation mismatch**, not evidence that task source, Beads initialization or ProjectCTL runtime failed.

Two root-level glob patterns (`*.db`, `*.gate.lock*`) can also hide unrelated application-generated files from normal `git status` and diff-policy inspection. We accept their presence only as part of the immutable **observed Beads setup snapshot**, and require an additional ignored-file inventory before committing and again before authorizing paid worker dispatch; any ignored source/artifact outside `.beads/`, `.dolt/`, or the local Beads credential key must be explicitly adjudicated. We do not silently delete Beads patterns or globally allow arbitrary ignores.

## Scoped research-only repair

- `experiments/dogfooding/d2/gitignore_review.py` compares baseline `.gitignore`, current `.gitignore`, and immutable `observations/beads-setup-v1/gitignore-after.txt` byte-for-byte, preserving original tracked rules and requiring **exactly** the five observed noncomment Beads patterns (no extras or duplicates).
- `d2_adopt_projectctl_manual.sh` now validates the initial `.gitignore` SHA against the frozen 11-file manifest and calls the new helper; it also inspects ignored untracked files with `git ls-files --others --ignored --exclude-standard -z` and fails closed if unrelated application paths are hidden.
- `experiments/dogfooding/d2/test_gitignore_review.py`: **13** offline regression cases covering exact five-pattern acceptance, captured-snapshot drift, unknown rules, blanket ignores, baseline tampering, duplicate rules, and hidden `*.db`/`*.gate.lock*` files.
- The fix changes **only** the research helper and its tests, not the frozen D2 SPEC, the 26 acceptance tests, ProjectCTL runtime, direct arm, or source application code. No paid invocation was made.

## Operator next gates

1. Fast-forward research branch; run offline tests with the existing D0 VENV: `$HOME/.local/share/projectctl-dogfood-d0/venv/bin/python -B -m unittest -v experiments.dogfooding.d2.test_gitignore_review`. Require **13/13** pass.
2. Re-run the read-only `d2_adopt_projectctl_manual.sh --preview` **without** re-running Beads initialization or recreating fixtures. Require `D2_BEADS_GITIGNORE_REVIEW_PASS`, `snapshot_exact_match=true`, `ignored_application_paths_checked=true`, single unclaimed Task, and `D2_PREVIEW_PASS`.
3. Only then, with operator acknowledgement, invoke `--adopt --ack-local-git-commit`. This performs a ctl-local Git commit of `.gitignore` and isolated `projectctl init`, not any worker run.
4. If any new mismatch or hidden application file appears, stop and review actual evidence. Do not reset/rebuild, disable the safety check, or broaden the acceptance silently.

**Decision at recording:** `D2_ADOPTION_PREVIEW_BLOCKED_VALIDATOR_ONLY` with **offline patch prepared but not yet operator-tested**; inference, claim and control-plane policy setup remain pending.
