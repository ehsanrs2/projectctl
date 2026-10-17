# M6.0 M0f — Linux Process-Group Cutover, pidfd Identity and Escape Proof

**Status:** Linux-only, disposable test/architecture gate. **NOT** a deployable service controller, enforced all-writer barrier, v2→v3 migration, or authorization to start one.
**Baseline:** `main@3d343b425eeb94f64289f7126fcf8e5a6e96264e` (M0e PR #75 merged).
**Governing:** ADR-039/040 Path A; M0a unified-v3 contract, M0b legacy lock-bypass proof, M0c external offline cutover decision contract, M0d tracked PID termination, M0e Landlock per-subject child confinement.

## Precise new result

M0e proved that Landlock can restrict only processes that are *placed inside the sandbox*: it does not revoke old writable descriptors or retroactively exclude an unmodified v2 process outside its scope. M0f now tests a **different kernel process lifecycle primitive**: start a fresh Linux session/process group and stop that group by `killpg`. It observes member exit with a Linux **pidfd** tied to the kernel process identity, not a reusable PID string.

The positive result is deliberately narrow: killing the test's *owned, live, correctly identified* session group stops one preexisting unmodified v2 descendant *that has not escaped*. Two independent counterexamples are mandatory:
1. A descendant calls `setsid()` before maintenance, leaves the supervised process group, survives the group's SIGTERM and writes a v2 RunStore event or independent JSON afterwards.
2. Another program starts in a **new, unrelated process group after** the original group is stopped and writes to the same disposable v2 database.

Therefore process-group termination, process sampling, pidfds, Landlock, systemd service stop, cgroup membership and advisory locks **must not** be conflated with an all-writer startup or filesystem embargo. The strongest M0f decision is `LAB_REVIEW_ONLY` even when every hypothetical boolean is true; operational migration remains **NO-GO**.

## Experiment and safety boundaries

The only code is `tests/test_m60m0f_process_group_pidfd_boundary.py`. It creates a fresh, real ProjectCTL project-state **v2** RunStore under pytest `tmp_path`; no existing user source, installed project, systemd units, cgroups, kernel mount settings or CLI are touched.

- Each test actor is an independent Python interpreter with `start_new_session=True`; the actor constructs a real legacy `RunStore` **before** the supervisor's shutdown. It forks a descendant that waits for a file trigger in the disposable fixture, then appends an event via RunStore or publishes a dummy staged JSON file.
- The parent observes the session leader via Linux `/proc/<pid>/stat` PID, process-group ID and birth `start_ticks`, verifies the leader is a live child *it itself spawned* and refuses a forged identity before signaling. This protects the test's signal target; a `/proc` sample alone is **not** sufficient secure operator attestation for arbitrary services.
- The parent signals only the owned session's process group; **never uses arbitrary PIDs from `ps`, PID files, the project DB, user input or unrelated services**. The descendant's identity is pinned by `os.pidfd_open`; `signal.pidfd_send_signal` is used only for cleanup of that test-owned child. Unlike numeric-PID SIGKILL, the pidfd is not vulnerable to PID reuse.
- For the nonescaping group member, a successful pidfd exit observation before the test trigger demonstrates the child can no longer publish the post-stop event or JSON. It does **not** prove all DB connections, background tasks or external writers ceased.
- In the escaped descendant test, the child moves to a new session before notifying readiness; after the owned original process group has stopped, a test-owned trigger makes the descendant publish either a real v2 event or JSON. The test then verifies the exact expected change. The pidfd cleanup prevents leaving a running escaped fixture child.
- Another test launches a new independent interpreter/session after the first group is stopped. It writes despite that group's earlier shutdown. No actual restart embargo is enforced.
- A forged leader birth witness must be rejected without a signal. No operator state is modified. Tests are skipped on non-Linux or hosts lacking the pidfd Python APIs; this is **not** positive containment evidence.

Tests use only temporary local fixtures, bounded handshakes and process termination of owned test children. A naturally orphaned descendant may briefly be reparented by the OS; this remains an experimental lifecycle observation and is not a service deployment specification. All actual ProjectCTL application and DB version settings remain unchanged.

### Acceptance matrix

| Condition | Observed/required result | Security interpretation |
| --- | --- | --- |
| Group leader and descendant share a fresh owned PGID | Group SIGTERM + pidfd verifies child exit; no post-stop write | Scoped descendant stoppage for one fixture lineage only |
| Child calls `setsid()` before shutdown | Child survives and writes DB and JSON in separate tests | **NO-GO** escaped process scope |
| Fresh independent session starts after group stop | New v2 RunStore writes | **NO-GO** startup embargo absent |
| Falsified PID birth witness | Refuse `killpg` before any signal | Never signal by unverified stale PID |
| Missing external scope, descendant, fd, launch, filesystem or recovery evidence | `NO_GO_<gate>` | Refuse incomplete proof |
| All booleans supplied as true | `LAB_REVIEW_ONLY`, never production GO | No assertion authenticates itself |

The test cannot establish whether any real systemd service, cgroup, uid, path, namespace or mount is fully authoritative over a user installation. It tests **one kernel group signal** and two explicit escape mechanisms, not a real project lockdown. Equal snapshots of the SQLite DB would not substitute for that missing confinement proof, nor would a successful WAL-inclusive backup.

## Required deployment contract before any production M0

**M0g — independently operator-approved target deployment evaluation.** Pick a single, explicit supported Linux host and local filesystem, plus one *real* service/supervisor and distinct per-project authority boundary. Require, at minimum:

1. Complete writer inventory: all RunStore direct calls, CLI scripts, auto-restarts, heartbeat/Verification/Recovery/Integration, worker grandchildren, JSON publishers, already-open SQLite file and shm handles, and remote/container/mount-alias writers.
2. Externally enforced closed-world startup embargo covering every writer entrypoint, not merely new launches through one convenience wrapper or stopped systemd unit. Demonstrate denial for same-uid independent Python, different-uid where relevant, operator direct CLI, inherited writable descriptors and restarted descendants; identify privileged bypasses.
3. Supervisor lifecycle proof under actual Linux cgroup/session semantics. Test a descendant that forks, re-parents or attempts `setsid`; group SIGTERM by itself cannot complete this gate. Handle supervisor death, restart, leaks, cgroup delegation and process namespaces with explicit **NO-GO** outcomes.
4. Document and independently test actual filesystem enforcement for all project DB/WAL/SHM and independent JSON evidence leaves, anchored source identities and no path/symlink/hardlink alias bypass. Shared-UID access and remote writers must be excluded by the deployment boundary, not by observation.
5. Keep admission exclusion held continuously across source validation, owner-approved WAL-inclusive durable no-clobber backup, candidate v3 transaction, uncertainty reconciliation and controlled release. No automatic source restore, retry after ambiguous COMMIT or resumption of legacy v2 clients.
6. Produce a bounded security review and adversarial/operator-local tests for supported kernel, filesystem and systemd/cgroup configuration. If any witness is missing or out of scope, **NO-GO**. A production M0 migration and W1 trusted Seal writer require new, separately reviewed PRs. R1 safe nonmutating WAL read is independent.

A more expensive pre-v3 cooperative rollout (M0b Option B) remains an alternative, but still cannot secure already-running noncooperative v2 clients without a genuine external admission boundary.

## Validation

Require exact-head hosted full Python tests, compile, public schema-export policy, and pinned Codex SDK job. Inspect focused test counts and skips (a skipped pidfd test cannot establish Linux process enforcement). Optional operator-local Linux focused smoke:

```bash
git fetch origin
git switch --track origin/experiment/m6.0-m0f-process-group-pidfd-escape
source .venv/bin/activate
python -m pytest -q -rs tests/test_m60m0f_process_group_pidfd_boundary.py
GIT_PAGER=cat git diff --check origin/main...HEAD
git rev-parse HEAD
python --version
```

**Governance:** Keep Draft and do not merge without owner review. No `projectctl/` changes, `PROJECT_STATE_DB_VERSION` bump, production migration, client lockdown, provider/Worker rights, new Seal, Collector, CLI or release.
