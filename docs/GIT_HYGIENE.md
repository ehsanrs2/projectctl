# ProjectCTL Git / documentation hygiene — controlled cleanup (2026-11-04)

**Repository:** [ehsanrs2/projectctl](https://github.com/ehsanrs2/projectctl). This is a read-only audit and an **operator-run deletion protocol**, not an automatic branch deletion or an authority to rewrite old evidence. Main was verified at `82f576632f35b68adced2e529768d72f7017fd3b` and PR #126 was merged.

## Branch disposition at this check

| Remote branch | Git history vs main (at check) | Decision |
| --- | --- | --- |
| `main` | default | **Never delete** |
| `docs/m6.0-p03d1-source-witness-topology-decision` | 1 unique commit, open Draft PR #125 | **Preserve**, review against post-#126 main |
| `docs/20261104-main-rebaseline-readme-navigation` | Docs-only PR #128 | **Preserve** while open |
| `fix/post-d2-telemetry-duplicate-path-cli` | Issue #127 PR #129 | **Preserve** while open |
| `feature/m4.2a-execution-input-contract` | 53 commits not in main by ancestry (may include alternate history) | **Preserve** until independent diff/intent review |
| `research/advisory-skills-eval` | 183 commits not in main by ancestry; frozen research D2 provenance | **Preserve**, not a candidate for simple merged cleanup |
| `feature/post-d2-lifecycle-observability` | Branch commit `745d10f45fe834dfe7d1b58df61222f4eb9cceed` is a parent of merged main `82f5766...` | **Deletion candidate** only after fresh SHA/ancestry/PR verification |
| `experiment/m6.0-m0h-mount-namespace-access-pilot` | Commit `4c0b28ebe3b05a3c550b8ccd10b419ab4d3dd6fe` is ancestor of main | **Deletion candidate** only if no unfinished/unmerged review depends on the ref |

**Important:** Git ancestry is sufficient to show these branch tips are reachable from main; it is **not** evidence that every historical worktree, snapshot or external research witness can be deleted. Do not delete Git tags, merge commits, local worktrees, private evidence or pinned research paths.

## Read-only preflight on normal developer host (no root, no tmux)

```bash
cd "$HOME/projectctl-m0k-lab"
git fetch origin --prune
git status --short
git rev-parse refs/remotes/origin/main

for branch in \
  feature/post-d2-lifecycle-observability \
  experiment/m6.0-m0h-mount-namespace-access-pilot
do
  ref="refs/remotes/origin/$branch"
  if ! git show-ref --verify --quiet "$ref"; then
    echo "MISSING_REMOTE_BRANCH: $branch"
    continue
  fi
  sha="$(git rev-parse "$ref")"
  if git merge-base --is-ancestor "$sha" refs/remotes/origin/main; then
    echo "MERGED_CANDIDATE: $branch $sha"
  else
    echo "PRESERVE_UNMERGED: $branch $sha"
  fi
done
```

Before deleting, verify the name and HEAD against the GitHub branch/PR list and **operator-confirm** no ongoing work depends on the ref. Do not use unqualified wildcard matching, `git branch -D`, history rewrites or deletion of branches with unique commits. A branch that has advanced after this snapshot requires fresh review.

## Optional operator-approved remote deletion, one pinned ref at a time

The user performs these commands **only after** the read-only preflight and explicit decision. The force-with-lease option is used only as a compare-and-delete guard; it is **not** license to force-update history. Do not paste both deletions without first verifying each current SHA.

```bash
# Example only for the merged PR #126 feature ref, after its exact SHA matches:
git push --force-with-lease=refs/heads/feature/post-d2-lifecycle-observability:745d10f45fe834dfe7d1b58df61222f4eb9cceed \
  origin :refs/heads/feature/post-d2-lifecycle-observability

# Independent second candidate, only if its own review permits:
git push --force-with-lease=refs/heads/experiment/m6.0-m0h-mount-namespace-access-pilot:4c0b28ebe3b05a3c550b8ccd10b419ab4d3dd6fe \
  origin :refs/heads/experiment/m6.0-m0h-mount-namespace-access-pilot
```

Afterward: `git fetch origin --prune`, inspect `git branch -r` and the GitHub PR/branch list. Do not infer remote cleanup from local ref pruning alone.

## Documentation cleanup, non-destructive

- Root README is a short landing, while the previous long README is preserved as [historical reference](FEATURE_HISTORY.md).
- [docs/README.md](README.md) and [architecture/INDEX.md](architecture/INDEX.md) organize documents by authority and proof level.
- [Implementation status](IMPLEMENTATION_STATUS.md) is a dated ledger; the [Blueprint](PROJECTCTL_BLUEPRINT.md) remains the single overall architecture and roadmap authority and [PROJECT_STATE.yaml](PROJECT_STATE.yaml) remains the active-milestone authority.
- Historical ADRs, experiments and frozen evidence should be **annotated**, not silently deleted or given retroactive statuses.
- Clean-up PR #128, bug PR #129 and preexisting decision Draft #125 must be reviewed independently, with CI at the exact head, before merging or deleting their branches.
