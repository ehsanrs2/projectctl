# D1 paired-fixture starting-point freeze (operator evidence)

**Date:** 2026-10-18. **Status:** BASELINES_MATCH / NOT STARTED. Research-only; no ProjectCTL worker, direct Codex task or M6.0 changes.

The operator manually pulled branch `research/advisory-skills-eval` to `50100b3` and invoked the already-vetted fixture builder twice with an output root **outside the ProjectCTL source worktree**:

- `$HOME/.local/state/projectctl-dogfood-d1/fixtures/ctl`
- `$HOME/.local/state/projectctl-dogfood-d1/fixtures/direct`

Both calls succeeded, creating separate local Git repositories. Operator independently checked that:

| Evidence | ctl | direct |
| --- | --- | --- |
| Initial `git rev-parse HEAD` | `da9379c70571c9366f5adfccecdfab148c814fc2` | `da9379c70571c9366f5adfccecdfab148c814fc2` |
| `sha256sum SPEC.md` | `aac3d5e847cd24849e92860553459bae9f7cbf70cbf00073eba140270160253d` | `aac3d5e847cd24849e92860553459bae9f7cbf70cbf00073eba140270160253d` |
| `git status --short` | empty | empty |

These results establish identical **pre-setup source baselines**, not that the task has been executed or that the ProjectCTL metadata/Beads adoption commits will retain identical Git HEAD identities. Setup-specific commits in the `ctl` arm must be tracked separately from the actual application code baseline; compare immutable pre-setup source files and independent acceptance criteria across arms.

## Next gated step (Beads in ctl only)

Initialize a fresh local Beads 1.3.1 authority **only in** the new `ctl` fixture, create exactly one task containing the frozen SPEC, and inspect `bd ready --json` and `git status --short` before ProjectCTL adoption. Use `BD_DISABLE_METRICS=1`, `DOLT_DISABLE_EVENT_FLUSH=1`, `DO_NOT_TRACK=1` and a fixed `BD_ACTOR`; no second Beads task authority. Never run `bd init` inside the original ProjectCTL source worktree or the `direct` fixture.

At this gate, record any Beads-created tracked/untracked metadata. Do not automatically commit Beads database files, reset, clean or use `--allow-dirty` merely to force onboarding. The direct fixture must remain unchanged until its paired inference run.

Still outstanding: disposable ProjectCTL adoption, isolated `PROJECTCTL_HOME`, human-managed required task scope, independent verification catalog, consistent model/reasoning/sandbox, quota admission and single-owner/lease precautions. Do not invoke `projectctl run start` or `codex exec` as part of fixture preparation.

**Decision:** `D1_BASELINE_FROZEN`; `D1_INFERENCE_NOT_STARTED`.
