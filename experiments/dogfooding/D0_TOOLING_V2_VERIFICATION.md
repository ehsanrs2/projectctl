# D0 Tooling v2 — post-install correction record

**Status: tooling locally qualified; D1 remains NO-GO.** This is research-only and does not modify ProjectCTL runtime or M6.0.

Source context: operator pushed the D0 package to this branch at `dd051b5`. Operator then installed a dedicated Python 3.12.15 environment with `projectctl 0.41.0`, `typer 0.27.3` and pinned `openai-codex 0.160.0`. `projectctl version` and Python package-version inspection succeeded. The last `command -v bd` produced no path, so Beads availability is still unconfirmed/blocked in that shell. SDK service acceptance of `gpt-6-luna` has never been observed.

## Changes to this research folder

- `preflight.py`: fixes ProjectCTL CLI probe to the actual `projectctl version` subcommand; uses `bd version`; also locates ProjectCTL beside an explicitly selected virtualenv interpreter. Separates genuine install/environment blockers (`environment_blockers`, `environment_status`) from outstanding runtime/experiment gates (`pending_d1_gates`). Even when environment tools are all installed, `status=D1_NO_GO` until D1's independent gates are established. Schema is now `projectctl.dogfooding_d0_preflight.v2`.
- `build_fixture.py`: requires `--output-root`, an **existing, real directory outside the research checkout and outside any Git worktree**. Creates a single new fixture directory only; rejects existing data or symlink destinations and never deletes anything. Fixture tests now distinguish ASCII-only lowercasing from Unicode lowercasing and cover internal whitespace. The new baseline SHA differs from the earlier fixture by design; it remains deterministic between the paired arms.
- `test_d0_tools.py`: uses unique system temporary directories with owned cleanup rather than deleting a fixed path; adds regression cases for CLI probe, simulated environment-ready-but-D1-NO-GO, output safety, deterministic paired base, and no path leakage.
- `D1_PLAN.md`: the manual fixture commands now use a separate explicit external output root.

## Evidence

The amended versions of all three Python files were exercised together in a separate isolated local copy: **10/10 D0 tests passed**, and `python -m compileall -q` passed. These are local assistant-side checks, not owner-host confirmation, a successful real SDK model run, or proof of the Beads adapter contract.

## Operator verification — no paid execution

From the ProjectCTL research worktree root after `git pull --ff-only`:

```bash
D0_VENV="$HOME/.local/share/projectctl-dogfood-d0/venv"
export PATH="$D0_VENV/bin:$PATH"
"$D0_VENV/bin/python" -m unittest -v experiments/dogfooding/test_d0_tools.py
"$D0_VENV/bin/python" -m compileall -q experiments/dogfooding
"$D0_VENV/bin/python" experiments/dogfooding/preflight.py
"$D0_VENV/bin/projectctl" version
command -v bd || true
```

The last preflight command must continue to say `D1_NO_GO`. Its `environment_status` can switch to `READY_FOR_RUNTIME_PROBE` only after all tooling is installed, including Beads and CLI. This label is *not* permission to execute an SDK worker.

When Beads is installed, inspect `bd version`, `bd help`, local backend initialization, and the JSON task API shape used by the ProjectCTL adapter. Recent Beads versions can differ materially in persistence/backend behavior; do not automatically initialize or upgrade an existing Beads database. Installation sources and CLI help must be reviewed before operating on new disposable repos.

For future fixture setup (not performed during D0):

```bash
FIXTURE_ROOT="$HOME/.local/state/projectctl-dogfood-d1/fixtures"
mkdir -p "$FIXTURE_ROOT"
"$D0_VENV/bin/python" experiments/dogfooding/build_fixture.py ctl --output-root "$FIXTURE_ROOT"
"$D0_VENV/bin/python" experiments/dogfooding/build_fixture.py direct --output-root "$FIXTURE_ROOT"
```

If either destination already exists, the builder stops without overwriting it. Do **not** create the fixture pair until D1 preconditions and use of this external root are explicitly reviewed. Do not commit fixtures, state roots, model sessions, or raw logs to the research branch.

**Next decision:** install/locate Beads, establish its adapter compatibility offline, inspect actual ProjectCTL CLI capabilities and quota/scope policies in a disposable setting, then separately authorize a bounded SDK model runtime check. No worker execution or M6.0 edits are part of the D0 repair.
