# D2 first-pair evidence harness — offline qualification runbook (2026-10-20)

**Status:** `D2_NO_INFERENCE_PREFLIGHT_PASS / DIRECT_EVIDENCE_HARNESS_PREPARED_NOT_OPERATOR_TESTED / NO_PAID_TURN`. Source task and management freeze are untouched. The first paired trial order is **Direct CLI → ProjectCTL**.

## User-observed preflight

On the pinned research branch the operator ran all 13 `test_d2_no_inference_preflight` tests, **13/13 passing**. The read-only `d2_no_inference_preflight` returned `D2_NO_INFERENCE_PREFLIGHT_PASS`, direct prompt SHA-256 `b4aa6e48872f07d1d608bf24a5beeed45ac9e68656defc52aa8c632b63c50f65`, task `d2ctl-g4q`, fixture baseline `32836ea5633230e50fb9d907dcdba83e357bcfc6`, ctl policy HEAD `3c69dd42497acadadc5d64e7b4abe5d412b309f5`, `gpt-6-luna`/medium, SDK `0.160.0` and CLI `0.163.0`. No model was invoked.

## Research-only instrumentation prepared

`d2_direct_manual.py` is a guarded local Python harness with two **separate** modes:

- `--preview`: verifies the frozen independent source/preflight, prompt digest, ctl/direct Git state, version flags and strategy; does not create evidence paths, refresh official quota, prepare a task, or start Codex.
- `--execute --ack-paid`: **future manual choice only, NOT part of current runbook**. Before any paid call it invokes fresh official Codex App Server quota and Scheduler, checks their high-confidence, non-stale `codex` bucket, effective MEDIUM thresholds, valid snapshot age, and exact selected task. It then refuses re-use of the fixed `observations/direct-attempt-1` path, creates a local mode-0700 evidence directory and performs **one** ephemeral Direct CLI `gpt-6-luna` medium turn with apps/plugins disabled, workspace-write, approval never, network disabled. No retry, Git commit, task claim, or ctl source context.
- After the CLI exits, a local-only summary includes UTC start/end, monotonic worker wall, CLI exit, JSONL event kinds and raw provider usage if available (cached/reasoning subsets are not added to total input/output), changed and ignored file paths, protected source hash checks, Git status and diff, and the separately timed fixed **26-case** unittest run. A failure is recorded as `*_FAILED_NO_RETRY`; a successful test/scope run is still `HUMAN_REVIEW_PENDING`, not automatic acceptance. No raw evidence should be uploaded to GitHub, particularly JSONL events, stdout, prompt content or stderr that may contain sensitive data.
- `test_d2_direct_manual.py` defines **17 new offline-only tests** for account and quota fail-closed gates, stale data, missing/fake official source, MEDIUM admission, scheduler choice, no-inference Preview, explicit paid acknowledgement, token usage accounting, JSONL failure, and ignored file detection. These newly defined tests have **not yet been run on the user's machine**.

The `ctl` arm does **not** run automatically after the Direct attempt. Its own subsequent, separately prepared and owner-gated `prepare → start → verify → human adjudication → integrate` commands must capture comparable monotonic timing, the SDK's actual usage **if exposed** (otherwise `unknown`), immutable source digests, Beads/task lifecycle and reasoned outcomes. A successful Direct test does not authorize CTL worker start; the research trial must stop on any unexpected discrepancy and preserve evidence.

### Required next commands — no paid activity

```bash
cd /home/ai/project/My/projectctl-advisory-lab
git pull --ff-only origin research/advisory-skills-eval
VENV="$HOME/.local/share/projectctl-dogfood-d0/venv"
export PATH="$VENV/bin:$PATH"
export PROJECTCTL_HOME="$HOME/.local/state/projectctl-dogfood-d2/ctl-home"
export BD_ACTOR=d2-dogfood-owner
export BD_DISABLE_METRICS=1 DOLT_DISABLE_EVENT_FLUSH=1 DO_NOT_TRACK=1 PYTHONDONTWRITEBYTECODE=1
"$VENV/bin/python" -B -m unittest -v experiments.dogfooding.d2.test_d2_direct_manual &&
"$VENV/bin/python" -B -m experiments.dogfooding.d2.d2_direct_manual --preview
```

Require **17/17** passing and `D2_DIRECT_HARNESS_PREVIEW_PASS__NO_PAID_CALL`. Any failure means stop; revise the **research harness only** before any paid arm and document the deviation. Do not delete/rebuild the frozen fixtures or tamper with the captured control-plane snapshot. The frozen experimental task, 26 acceptance tests, prompt hash and allowed writes must remain unchanged.

### Ahead of any later paid authorization

- Independently inspect code, exact live CLI flags and the proposed pinned research HEAD; the source in this branch is **not itself a security boundary**. Confirm no unreviewed repository changes.
- Check fresh official quota immediately before **each** arm; do not assume the 2026-10-20 quota measurement remains valid.
- Record the start/stop of both arms without mixing time spent in preflight, worker inference, tests, review and integration. Worker wall is not end-to-end effort.
- Treat unexpected mutations/ignored application files or even out-of-scope symlink changes as failure with no in-pair hotfix.
- Only after both arms complete, independently adjudicate actual source semantics and report all failed attempts, interventions and differences (CLI 0.163 vs SDK 0.160; prompt wrappers, tool interfaces, token reporting). N=1 is descriptive, not statistically conclusive.

**Current gate:** `D2_DIRECT_HARNESS_OFFLINE_TESTS_AND_PREVIEW_PENDING`. No current request authorizes invoking `--execute --ack-paid`.
