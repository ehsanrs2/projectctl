# D1 disposable ProjectCTL brownfield adoption — operator evidence

**Observed 2026-10-18. State:** `PROJECTCTL_INITIALIZED` on external disposable `ctl` fixture. **No paid execution, run preparation, or worker call.**

## Source and task identities

- Frozen application fixture baseline: `da9379c70571c9366f5adfccecdfab148c814fc2` (`ctl` and `direct`).
- Shared SPEC digest: `aac3d5e847cd24849e92860553459bae9f7cbf70cbf00073eba140270160253d`.
- Beads setup commit (only a 7-line `.gitignore` added): `1b38e7526c00009fd44a910e438d74969f00b3c9`; original application baseline remains a Git ancestor, so control and direct Git HEADs are no longer equal by design.
- Beads task `d1ctl-lh4` remained the **sole ready** task after ProjectCTL initialization, status `open` and no dependencies. This is not a Worker claim.
- `projectctl inspect` returned `classification=existing_unmanaged`, `dirty=false`, `detected_task_systems=[beads]`, `unresolved_decisions=[]`, no remote or conflict.
- A fresh `PROJECTCTL_HOME=$HOME/.local/state/projectctl-dogfood-d1/ctl-home` was set with a nonexistence guard before the `init` invocation.
- `projectctl init CTL --non-interactive --yes --task-store beads --code-transport local --code-delivery local --json` returned `status=initialized`, `mode=brownfield`, `unresolved_decisions=[]`, preserved `.beads`.
- New **untracked** control-plane files: `.projectctl/adoption.yaml`, `.projectctl/config.yaml`, `.projectctl/state.sqlite`, `.projectctl/telemetry.sqlite`, and `docs/PROJECT_STATE.yaml`. Empty `docs/generated` and `evidence` directories also created.

## Follow-up policy and safety

1. Treat `.projectctl/` as *local operational state*, not application source history. Add an explicit `.projectctl/` entry to this **disposable fixture's** `.gitignore`; never Git-add SQLite, accounts, run records or secrets.
2. Human-managed `docs/PROJECT_STATE.yaml`, `projectctl.scope.yaml`, and `projectctl.verification.yaml` are appropriate to track in a **fixture-local** setup commit, together with `.gitignore`. Do not modify the ProjectCTL source checkout's similarly named files.
3. Ensure the scope catalog binds exactly `d1ctl-lh4`, exact tracked inputs (SPEC, implementation stub and fixed tests/policy), and an exact `user_id.py` write allowance. Configure `scope_governance.mode=required` in the disposable local `.projectctl/config.yaml`.
4. Configure deterministic human-managed independent verification running `python3 -B -m unittest -v test_user_id.py`; test and policy files are protected. Set all enabled fixture model profiles explicitly to `gpt-6-luna` with `medium` reasoning **before** scheduling because the initialized defaults have `model: null` and may use other reasoning defaults.
5. Record final fixture config/policy digests and the new setup HEAD; keep the original `da9379c` semantic base identity separate for fair analysis.
6. Before `run prepare`, independently check real quota admission and status/next decision, single owner, task readiness, correct scope/verifier sources and Git cleanliness. Do not invent quota values, override admission or call any worker in this setup step.

Warning `beads.role not configured` is advisory in the observed `bd ready --json` read: the command returned the one ready task. `BD_JSON_ENVELOPE` v2 warning is forward-looking; do not switch formats in the middle of D1.

**D1 inference state:** NOT STARTED. **Only fixture `ctl` was adopted; `direct` remains untouched.**
