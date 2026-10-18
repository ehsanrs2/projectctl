# D0 independent review and environment recovery

**2026-10-18. Research-only. NO-GO for D1.** Based on the operator-supplied `dogfooding.zip` D0 package (not yet imported to this Git branch at the time of review).

The package has `preflight.py`, `build_fixture.py`, `test_d0_tools.py`, `D0_REPORT.md`, and `D1_PLAN.md`. The reported 4 unit tests passed, and an independent isolated rerun of those same four tests and Python compile also passed. This does **not** constitute a ProjectCTL SDK runtime, task authority, or D1 readiness proof.

## Specific audit corrections before D1

- **False CLI negative:** `preflight.py` invokes `projectctl --version`. ProjectCTL implements `projectctl version` as a subcommand. Replace the probe and add a regression test for an installed mock CLI.
- **Beads probe:** current Beads documentation advertises `bd version` / `bd help`. Check this format and verify actual locally installed version, not only `bd --version`.
- **Unsafe test deletion:** `test_d0_tools.py` deletes the fixed `.selftest-output` directory on setup/teardown. Use unique temporary directories with owned cleanup. Never erase a preexisting directory to run unit tests.
- **Nested Git isolation:** `build_fixture.py` currently writes `fixture-output/` within the ProjectCTL research worktree. Switch to an explicit operator-selected *external* disposable root; reject paths within source checkout and existing unrelated data.
- **Unreachable READY:** `preflight.inspect` unconditionally marks `SDK_MODEL_RUNTIME_UNVERIFIED`. Differentiate **offline environment readiness** from the still pending **explicit runtime-model compatibility gate**, preserving fail-closed D1 without pretending offline analysis can prove network model acceptance.
- **Task-spec fidelity:** `SPEC.md` says lowercase ASCII letters; strengthen fixed acceptance tests to cover non-ASCII characters, internal whitespace, and malformed inputs; do not accidentally test generic Unicode `.lower()` as compliant.
- **Test-gate coverage:** add regression tests for these exact false negatives, output-root containment, safe cleanup, and readiness/status logic. Existing 4/4 success cannot catch those gaps.

## Host environment repair (no D1 inference)

The D0 report used Python 3.14.0 and inspected the **active** environment, not every installed Python venv. The user had previously executed Codex CLI 0.163.0 successfully; SDK availability is a separate question.

Use a new dedicated Python 3.12 virtual environment **outside** the ProjectCTL worktree. From the repository root:

```bash
D0_VENV="$HOME/.local/share/projectctl-dogfood-d0/venv"
uv venv --python 3.12 "$D0_VENV"
uv pip install --python "$D0_VENV/bin/python" -e '.[codex,dev]'
"$D0_VENV/bin/projectctl" version
"$D0_VENV/bin/python" -c 'import importlib.metadata as m; print(m.version("openai-codex"))'
command -v codex
command -v bd
bd version
```

Installation uses package indexes and is an explicit, operator-run dependency setup, **not** an offline D0 preflight or model run. The `bd` command must already be installed, or follow its official installation instructions (and verify it afterward) **without initializing Beads inside the source repository**. Use the new venv's PATH when rerunning preflight; never treat a `bd`-missing observation in one isolated Codex shell as proof of absence in the operator's ordinary shell.

## Git handoff without losing local D0 files

The uploaded D0 package has not been pushed here by this document. Before pulling changes, explicitly stage and commit only its five new deliverables on the operator's research branch, inspect `git diff --cached --name-only` and `git diff --cached --check`; **do not stage generated fixture directories, Python caches, virtualenvs or local logs**. Then `git pull --rebase origin research/advisory-skills-eval` and push the operator's D0 commit. Subsequent small fixes can be committed directly to this same research branch, minimizing additional agent prompting and avoiding ZIP exchanges.

## Next decision

Maintain `D1_NO_GO` until controlled SDK model verification, local Beads authority availability, real ProjectCTL CLI help/contract checks, isolated state roots, clean external fixture repositories and fixed preflight/test safety checks are recorded. The initial model verification may be a **separately authorized, bounded first D1 runtime probe**: do not create an impossible requirement that offline D0 must prove an external service accepts the model.

No modifications to ProjectCTL runtime, M6.0 or its active worktrees are authorized.
