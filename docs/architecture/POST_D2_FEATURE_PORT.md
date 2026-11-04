# Post-D2 lifecycle feature port

> **Integration status addendum (2026-11-04):** This is a frozen selective-port preparation log. [PR #126](https://github.com/ehsanrs2/projectctl/pull/126) was subsequently merged into `main` at `82f576632f35b68adced2e529768d72f7017fd3b`; [postmerge CI](https://github.com/ehsanrs2/projectctl/actions/runs/41785470901) succeeded. The log's final `PR_PENDING` label refers only to the time this file was authored. Do not rerun D2 or reinterpret research timing. See [current status](../IMPLEMENTATION_STATUS.md).


Worktree: `/home/ai/project/My/projectctl-lifecycle-integration`.
Branch: `feature/post-d2-lifecycle-observability`.
Frozen base: `4b3ce59f9f2f6daa9bb5b7e4dd77cf3eb49e12b4`.
Implementation/corrections: `d8114b1459da22ea687480f57c7d4a686b23968d` /
`4bf59132099cb798e0ccf5c49d936197aa220e44`.

## Preflight, dependencies and selective integration

The integration worktree was clean on the exact requested branch and base.
Research ancestry `6acee5f -> d8114b1 -> 4bf5913` was verified. Every path in
that complete source range was inventoried and reviewed. All existing modified
files were compared against the frozen base before applying the scoped patch.
The only source-baseline differences in these existing files were execution.py
and the Codex adapter; all other existing source files matched the research base.

The eight new source/test modules are preserved byte-for-byte from corrected
commit 4bf5913. They depend on existing schema parsers, RunStore enums, canonical
digests, trace snapshot/validation/WAL file primitives and the WorktreeManager
path contract. Tests reuse existing disposable Integration and Codex fixtures.
No package or dependency changes were needed; the isolated environment imports
ProjectCTL from this integration checkout and has openai-codex 0.160.0 installed.

For existing modules, only observability hunks were applied to current frozen
main versions. No whole-file replacement, branch merge or cherry-pick was used.
Compatibility-sensitive adaptations preserve:

- Main's direct `task.resource_class` quota/preflight/checkpoint semantics. The
  research-only effective-resource-class strategy was not imported.
- Main's `WorkerOutputPayload.model_json_schema()` adapter output behavior. The
  research-only strict output-schema normalizer was not imported.
- All existing dispatch, checkpoint, recovery, lease, task ownership,
  verification and integration semantics. Timing wraps existing boundaries;
  without capture enabled it does not call the measurement clock.

Audit is a read-only derived view and never grants stage authorization or
implicit retry. Corrected frozen-HEAD, checkpoint-workspace, candidate-diff and
SDK subset checks are included. Expected post-integration cleanup is supported.
Optional measurement files retain their existing opt-in, exclusive telemetry
behavior, separate last/total scopes and no subset double-counting.

Operational documentation and ADR-041 were adapted to feature-port preparation.
The synthetic JSON example was copied unchanged. Historical D2 artifacts and
research qualification reports were excluded; they are not production dependencies.
The blueprint records the bounded interface without changing the M6 milestone,
requirements, verification policy or trace Collector/Seal gates.

## Offline test transcript

Interpreter: `/home/ai/.local/share/projectctl-dogfood-d0/venv/bin/python`.
All runs used `-B` and pytest cache disabled. No live SDK was opened.

```
python -B -m pytest -o addopts= -q -p no:cacheprovider \
  tests/test_lifecycle_audit.py tests/test_lifecycle_measurements.py \
  tests/test_lifecycle_usage.py
83 passed in 9.28s

python -B -m pytest -o addopts= -q -p no:cacheprovider \
  tests/test_m11_worktrees.py tests/test_m11_run_store.py \
  tests/test_m12b_codex_adapter.py tests/test_m12b_codex_sdk_contract.py \
  tests/test_m13_verify_e2e.py tests/test_m14_integration_recovery.py \
  tests/test_m22_checkpointing.py tests/test_m60b1_readonly_snapshot.py \
  tests/test_m60b1b_artifact_validation.py
86 passed in 3.04s

python -B -m pytest -o addopts= -q -rs -p no:cacheprovider tests
SKIPPED [5] tests/test_m60m0h_mount_namespace_access_pilot.py:234:
  M0h OS namespace unshare denied; NO-GO for this host
2369 passed, 5 skipped in 37.23s
```

The focused suite covers all lifecycle statuses, clean wrong HEADs, checkpoint
and workspace drift, incomplete candidate Git evidence, valid stage previews,
completed/cleaned Runs, subset violations in both SDK scopes, absent usage,
interruption, opt-in behavior and byte-for-byte read-only invariants for Git,
RunStore, Beads files and durable evidence. Existing Execution/Integration/
Verification, Worktree, RunStore, CLI and SDK contract behavior is covered by
the named compatibility checks and full suite.

The known historical D2 combined-pytest module-cache isolation failure remains
a limitation, not a passing claim. Historical tests were not transplanted or
modified to mask it; no combined D2 pytest run or historical live stage was used
as a qualification gate for this port.

## Remaining limits and next gate

Live-WAL RunStore snapshots remain unsupported and explicitly unknown. Repeated
observations are not an atomic snapshot or authenticated history. There is no
durable dispatch journal: telemetry cannot establish that an uncertain action
never ran, authorize recovery, or permit retry. Separate owner authorization is
required for every live stage. SDK scopes are not summed or differenced across
resumes and timings are host elapsed boundaries, not pure model/GPU time.

No real workers, paid calls, provider sessions, live Prepare/Start/Resume/Verify/
Integrate/Recovery, D3, push, PR creation or merge into main occurred. Only
disposable synthetic fixtures exercised state-changing routines in tests.

Original refs to preserve:
`main=f67192c7291a7f60ab077ebe2a9e766af8ad4515` and
`research/advisory-skills-eval=4bf59132099cb798e0ccf5c49d936197aa220e44`.
The requested frozen base remains an ancestor of main; this task does not
rebase the port onto a moving main ref. The next gate is owner review and a
separately authorized PR. This task does not publish it.

## Exact changed paths

```
docs/PROJECTCTL_BLUEPRINT.md
docs/architecture/POST_D2_FEATURE_PORT.md
docs/architecture/POST_D2_LIFECYCLE_OBSERVABILITY.md
docs/architecture/examples/post_d2_lifecycle_audit.synthetic.json
docs/decisions/ADR-041-offline-lifecycle-audit-and-measurements.md
projectctl/application/execution.py
projectctl/application/integration.py
projectctl/application/lifecycle_audit.py
projectctl/application/lifecycle_git.py
projectctl/application/verification.py
projectctl/cli/m11.py
projectctl/git/worktrees.py
projectctl/telemetry/lifecycle.py
projectctl/telemetry/lifecycle_reader.py
projectctl/trace/snapshot.py
projectctl/workers/codex/adapter.py
projectctl/workers/codex/usage.py
tests/test_lifecycle_audit.py
tests/test_lifecycle_measurements.py
tests/test_lifecycle_usage.py
```

The final feature commit SHA is reported in the handoff rather than recorded
self-referentially here.

Result: `POST_D2_FEATURE_PORT_OFFLINE_QUALIFIED__PR_PENDING`.

The original research worktree has an unrelated untracked `uv.lock` at final
inspection. It was preserved; the research ref and tracked files are unchanged.
