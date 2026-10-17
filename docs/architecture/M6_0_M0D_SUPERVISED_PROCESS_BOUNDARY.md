# M6.0 M0d — Supervised Legacy-v2 Process Drain and Restart-Bypass Rehearsal

**Status:** Linux/POSIX test-only experiment. **NO-GO** for a production v2→v3 migration or operational service shutdown.
**Baseline:** `main@121ee92d55eccef5a7c71f3348495874f9d0ddc2` (PR #73 M0c merged).
**Evidence:** M0b proves that v2 RunStore does not honor a future maintenance lock. M0c sets an offline-only cutover policy with no production admission method. This M0d step exercises a small part of that missing exclusion problem against real disposable v2 clients.
**Changed files:** This document and `tests/test_m60m0d_supervised_process_boundary.py` only.

## Explicit security conclusion

A Linux test can **stop processes the test itself created and enrolled**. It cannot prove that *all* ProjectCTL writers have stopped, because unmodified v2 processes started elsewhere do not participate in its fixture launcher. A launcher `closed` flag is voluntary and prevents only that launcher's own calls; it does not prevent untracked local processes, other accounts, already-open SQLite handles, provider subprocess trees, systemd restart, container entry points, network filesystem clients or external JSON publishers.

**This PR therefore proves a bounded success and deliberately reproduces an unbounded failure.** The strongest synthetic decision is `LAB_EVIDENCE_ONLY`, never production `GO`. Unmanaged database and artifact writers yield `NO_GO_UNMANAGED_WRITER_SCOPE` even if all supervised children stopped.

The design must not be read as an approved Linux process-control mechanism, because `/proc` sampling, per-PID signaling, process lists, pidfiles, `SIGTERM`, fixture launcher checks and an empty lease table cannot by themselves form a trusted all-writer exclusion protocol.

## Experimental boundary and tests

The tests create one new ProjectCTL v2 database and RunStore under pytest `tmp_path`; each spawned Linux process constructs a real legacy RunStore **before** any simulated maintenance action. All signal operations go **only to `multiprocessing.Process` objects directly spawned by the fixture**, never to discovered or existing system PIDs.

- **Enrolled writer drain.** Two previously created processes (database writer and independent JSON publisher) are enrolled. The test checks their Linux `/proc/<pid>/stat` start-tick identities, disables the fixture launcher, sends `terminate()` to both, joins them with bounded waits and proves no fixture DB/event or JSON change occurred after exit. Exit proves only those two fixture processes ended.
- **Controlled relaunch refusal.** The fixture launcher declines a new spawn when closed, without creating a new process. This is explicitly a cooperative launcher-level behavior, not an OS start ban.
- **Unmanaged real-v2 bypass.** Another process with a preconstructed RunStore, deliberately *outside* enrollment, successfully appends an event or replaces independent dummy JSON **after** the tracked writer was stopped and the launcher closed. A second test spawns a fresh untracked legacy process **after** the fixture launcher is closed, and it can still write. Both cases must return `NO_GO_UNMANAGED_WRITER_SCOPE`.
- **Bounded termination timeout.** One fixture child deliberately ignores SIGTERM. After an observed timeout, the decision is `NO_GO_UNDRAINED_PROCESS`; only test cleanup may subsequently `kill()` its own child. Real maintenance must not silently force-kill an arbitrary process to claim quiescence.
- **PID identity fail-closed.** Altering the Linux birth-time witness refuses a stop operation before signaling; an unknown/invalid process identity returns `NO_GO_IDENTITY_UNCERTAIN`. A start gate not held returns `NO_GO_RESTART_ALLOWED`. The PID/start-time sample is a limited identity observation, not a proof of ownership or global process inventory.

Tests are skipped outside Linux or without `/proc/self/stat`. No privileges, cgroup operations, signals to real ProjectCTL installations, mutations to source projects or network calls are used. Cleanup kills only children owned by this test.

## Why M0d is not production admission

| Proven inside fixture | Remains unproven in a real deployment |
| --- | --- |
| A tracked, pre-existing RunStore child can be terminated and reaped | Complete inventory of processes, descendants, detached children and open handles |
| Fixture launcher rejects calls once closed | An **OS-enforced** ban on all future writer startups/exec/reopens |
| Linux PID plus `starttime` changes can be detected for tracked children | Authenticated process lineage and system-wide writers across namespaces and hosts |
| Unenrolled legacy child bypass is reproducible | Writer isolation for shared-UID users, different UIDs, root, containers and remote mounts |
| A timeout blocks admission | Secure and durable crash/restart exclusion ownership and recovery |
| RunStore v2 stays unchanged | A safe v2→v3 production schema/RunStore/Verifier cutover |

Especially important: killing a process does not imply killing its independently running descendants. Removing filesystem write permission is also insufficient if already-open writable file descriptors survive. Stopping a systemd unit does not prove no other unmanaged client is running. None of these incomplete controls should be presented as one portable admission gate.

## Candidate supported deployment for a *future* M0e feasibility proof

Propose a **single-host Linux-only, owner-managed project service boundary** as a *candidate*, not an implemented or approved solution:

1. Define a dedicated operator-controlled service identity and **one contained service/cgroup per selected project**. Inventory *all* RunStore/CLI/worker/heartbeat and independent JSON publishers; separately identify background provider trees and any external processes outside the service. Record executable/config deployment, project realpath/filesystem identity and model of all start channels.
2. Demonstrate a platform-enforced stop and start embargo over **all** relevant entry points before admission. A systemd service stopping alone is not enough; demonstrate no jobs, timers, socket activation, direct CLI use, inherited open handles, arbitrary same-UID clients, separate containers or network mounts can reach the project while the gate is held. Do not implicitly rely on `mask` or `KillMode=control-group` without actual adversarial tests and independently audited launch permissions.
3. Run two-process and spawned-descendant adversarial tests against unmodified v2 RunStore and a separate JSON writer. Include alternative entry-point attempts after embargo, a writer already initialized before it, a failed stop, process restart, cgroup escape, supervisor death and removal of the startup embargo. If any client outside the gate can write, admission stays **NO-GO**.
4. Require descriptor-anchored project/backup identities, confinement of mutable authority to that project (DB+WAL+SHM+JSON), operator identity, durable admission/commit/recovery evidence, fail-closed ambiguity, and explicit handoff to a *separate reviewed* M0 migration.
5. Restrict support to deployment/filesystem configurations actually proven under test. Unknown privileged writers, remote clients, shared credentials, unbounded process namespace/mount aliases, unsupported process supervision or unreliable directory fsync must be refused rather than silently downgraded.

Alternative B from M0b remains a separately approved cooperative pre-v3 rollout, but cannot retrofit already-running v2 processes without a trusted external exclusion method.

## Acceptance / next gates

**M0d acceptance:** focused local Linux smoke against disposable DB, clean PR diff, GitHub Actions exact-head green pytest/compile/schema-export and pinned Codex SDK; review the tests for leaked children and for false positive admission claims. A green CI result is only characterized test evidence.

```bash
git fetch origin
git switch --track origin/experiment/m6.0-m0d-supervised-offline-boundary
source .venv/bin/activate
python -m pytest -q tests/test_m60m0d_supervised_process_boundary.py
GIT_PAGER=cat git diff --check origin/main...HEAD
git rev-parse HEAD
python --version
```

**M0e candidate:** choose/prove one externally enforced per-project process and filesystem access boundary under operator control. Record proof against unmodified v2 writers, including process descendants, other launch channels and outside-scope clients. Until that proof, all operational migration admission remains **NO-GO**. B3a4 backup, M0a SQL, W1 fencing/Seal producer and R1 source-WAL reader are still independent gates.

**Governance:** Keep Draft, do not merge without owner review/instruction. No `projectctl/` code, database version, production migration, Worker authorization, future Seal publication or Trace Collector is changed.
