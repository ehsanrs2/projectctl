# D2 single local Beads authority — operator evidence (2026-10-20)

**Observed status:** `D2_BEADS_LOCAL_READY__REVIEW_GIT_CHANGES_BEFORE_PROJECTCTL_INIT`. This is a local metadata/task setup pass; **no ProjectCTL init, worker claim or paid inference has occurred**. Direct-arm baseline is preserved.

The owner fast-forwarded `research/advisory-skills-eval` from `cf1d1a1` to `9f547f7`, passed `bash -n`, and manually invoked `experiments/dogfooding/d2/d2_beads_setup_manual.sh --init-local-task` once.

Observed outputs:

- `FROZEN_PAIR_MANIFEST_VALIDATED`: the paired D2 fixture baseline remains source SHA `32836ea5633230e50fb9d907dcdba83e357bcfc6`; original SPEC SHA-256 `8264746827bbb7300bf234023e6617324c78f37aecf524f2427a686925da8815`.
- `BEADS_INIT_PASS`: Beads 1.3.1 local authority initialized **only** under `$HOME/.local/state/projectctl-dogfood-d2/fixtures/ctl`, prefix `d2ctl`, hooks/agent edits skipped; no published remote.
- `ONE_D2_TASK_CREATED: d2ctl-g4q`, frozen SPEC description.
- `D2_SOLE_BEADS_TASK_READY_UNCLAIMED`: one `open`, ready/unassigned canonical Task.
- `git status --short` on ctl: **` M .gitignore`**, a tracked file change attributable to the Beads setup phase. This change **has not** been committed or semantically inspected in the user-visible log; its contents were captured by the Beads script for later review. Do not presume it is safe before reading its diff.
- `D2_BEADS_SETUP_EXIT=0` and evidence directory `$HOME/.local/state/projectctl-dogfood-d2/observations/beads-setup-v1/`.
- Direct fixture still at the frozen base, no Beads or ProjectCTL state. No other Git status changes were displayed.

## Next bounded step

The review/adoption script `experiments/dogfooding/d2/d2_adopt_projectctl_manual.sh` provides **read-only** `--preview` and **operator-acknowledged** `--adopt --ack-local-git-commit` modes. It requires the exact known initial state, compares all unchanged D2 files with the frozen baseline manifest, validates that the base `.gitignore` rules were preserved and any added patterns are only narrowly enumerated local Beads ignore patterns (including `.dolt/`; never `.beads/` as a blanket rule), checks the sole canonical Task is still ready/unclaimed, and prints the actual Git diff. Unexpected ignore rules cause a **fail-closed stop** before any mutation.

Only after these gates, an expressly approved adoption locally commits **one** `.gitignore` file, calls `projectctl inspect`, and then performs `projectctl init --non-interactive --yes --task-store beads --code-transport local --code-delivery local` with `PROJECTCTL_HOME=$HOME/.local/state/projectctl-dogfood-d2/ctl-home`. This ProjectCTL adoption necessarily creates ignored operational state and may create untracked human-managed configuration, which must be reviewed at the next gate. The setup commit is a local ctl-only metadata commit, distinct from the shared application baseline and from any future worker code changes.

**Stop if** a preview reports an unexpected ignore rule, Task/ownership drift, wrong Git status, a different runtime/schema, or unexpected ProjectCTL state. Do not rerun `bd init` or `bd create` and do not overwrite, reset, or delete local evidence. The `direct` arm must remain pristine.

**Scientific status:** `D2_BEADS_TASK_READY / ADOPTION_PENDING / NO_PAID_EXECUTION`. Production main, D1 records and direct D2 source are untouched.
