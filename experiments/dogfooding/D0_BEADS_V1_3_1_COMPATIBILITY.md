# D0 Beads 1.3.1 compatibility review

**Status: installation confirmed; adapter lifecycle UNVERIFIED; D1 remains NO-GO.**
2026-10-18, research-only. No ProjectCTL runtime or M6.0 changes.

## Operator evidence

The owner pulled research commit `41d23fb` and completed 10/10 D0 tests. The initial Preflight v2 had a single environment blocker `BLOCKED_TASK_AUTHORITY` because it was run **before** installation. Later `npm install -g @beads/bd` returned success; `bd version` reported `1.3.1 (c1c4b642a)`; `bd help` displayed the command catalog. The npm postinstall warning did not prevent the observed binary from running. Run Preflight again, in the same shell where `bd` is available.

## Actual ProjectCTL adapter command boundary

See `projectctl/integrations/beads/client.py`, `claim.py`, and `completion.py`.

| ProjectCTL operation | Beads command |
| --- | --- |
| version | `bd --version` |
| task enumeration | `bd list --json`, `bd ready --json`, `bd blocked --json` |
| issue show | `bd show ID --json` |
| create | `bd create TITLE --description TEXT --type task --priority 2 --json` |
| claim | `bd update ID --claim --json` |
| validate claim | `bd show ID --json` and check status/assignee |
| release | `bd assign ID ""`, then `bd update ID --status open --json` |
| decision block | unassign, then `bd update ID --status blocked --json` |
| complete | `bd close ID --reason TEXT` |

Top-level `bd help` shows the key commands. The actual **flag, JSON payload, and mutation** compatibility with bd 1.3.1 is NOT verified merely by help text. In particular, the adapter treats claimed status `in_progress` and assignee equality as ownership evidence and has no integration with the new provider lease model.

## New provider lease risk

Beads 1.3.1 carries expiring claim leases (documented default TTL approximately five minutes), `bd heartbeat`, and `bd reclaim`/`bd unclaim`. The pinned ProjectCTL Beads adapter does not invoke `bd heartbeat`; its own run-state heartbeat is a different authority and does not renew a Beads claim. A run lasting beyond the provider lease or recovered after expiry needs an explicit compatibility policy and a genuine disposable-provider test. No change to ProjectCTL production ownership semantics is authorized by this research finding.

## Telemetry and privacy

Beads anonymous command telemetry is enabled by default. Preflight now passes `BD_DISABLE_METRICS=1`, `DO_NOT_TRACK=1`, and `DOLT_DISABLE_EVENT_FLUSH=1` to its `bd version` metadata probe. For future **manual** checks, set `BD_DISABLE_METRICS=1` and `DOLT_DISABLE_EVENT_FLUSH=1` in the operator shell. This avoids relying on changing a global preference. Do not claim that the ProjectCTL adapter sets those variables itself: it inherits the shell environment.

## Next operator step (help inspection only)

From the research worktree root:

```bash
git pull --ff-only origin research/advisory-skills-eval
D0_VENV="$HOME/.local/share/projectctl-dogfood-d0/venv"
export PATH="$D0_VENV/bin:$PATH"
export BD_DISABLE_METRICS=1 DOLT_DISABLE_EVENT_FLUSH=1 DO_NOT_TRACK=1
"$D0_VENV/bin/python" -m unittest -v experiments/dogfooding/test_d0_tools.py
"$D0_VENV/bin/python" experiments/dogfooding/preflight.py
bd version
bd init --help
bd create --help
bd update --help
bd assign --help
bd close --help
bd unclaim --help
bd heartbeat --help
```

None of these help/version calls should initialize a task store. Review the exact flags for `--claim`, `--status`, `--json`, and role/lease behavior. A subsequent *separately scheduled disposable-state compatibility smoke* will use only new external fixture repositories, no remotes or production data, to test create, ready, claim, release, block, close, and source-level JSON normalization.

## Interpretation

- Environment dependency gap: likely resolved (re-run offline Preflight to document).
- Beads 1.3.1 adapter lifecycle: not proved.
- Python SDK `gpt-6-luna` model resolution: not proved.
- D1 task execution: still `NO_GO`; continue the isolated static/smoke compatibility track before real paid inference.
