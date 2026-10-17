# M6.0 M0e — Linux Kernel Write-Containment Scope Feasibility (Landlock Pilot)

**Status:** disposable Linux test-only proof and negative threat characterization. **NO-GO** for actual maintenance admission, startup embargo or v2→v3 migration.
**Baseline:** `main@318bb568375d56a9c730d2dc9a0b7eeca63aaec4` (PR #74 M0d merged).
**Accepted architecture:** ADR-039/040 Path A, M0a unified v3 candidate, M0b nonparticipating-writer bypass, M0c offline gate, M0d supervised PID-drain experiment.
**Files:** `tests/test_m60m0e_linux_landlock_scope_feasibility.py` and this document. No code under `projectctl/` changes.

## What is new, and what is NOT established

M0d's launcher flag and process exit status were not a real OS-enforced access boundary. M0e advances one strictly bounded portion of the threat model: **Linux Landlock LSM access restrictions on new filesystem writes in a spawned test child and its descendants**. The child constructs a real v2 RunStore before confinement, then calls Linux `landlock_create_ruleset` and `landlock_restrict_self` with `PR_SET_NO_NEW_PRIVS`; it adds no path allow rules, so its handled filesystem-write rights are denied. Restrictions are applied only to the spawned disposable test process lineage, never to pytest, the host session, existing services, or actual ProjectCTL projects.

This is **not** a system-wide maintenance gate. In particular, Landlock cannot be applied retroactively to another already-running process or revoke writable file descriptors it opened earlier. It cannot constrain independently launched v2 clients that never enter the sandbox. It is only defense-in-depth for controlled future launches, not a substitute for the operator-enforced all-writer stop + prevent-start boundary required by M0c. A systemd/cgroup service with supervised shutdown is still a separate candidate: cgroup membership alone does not force all independent writers to join or block them from files.

The eventual real exclusion design needs *both* lifecycle enforcement **and** access isolation of all DB, WAL/SHM and separately published artifact writers. An isolated child and a passing test must never be conflated with source quiescence.

## Exact implementation and kernel semantics

- Linux only: direct syscall numbers 444/446 are used only on explicitly allowlisted `x86_64` and `aarch64` architectures. ABI probing uses `LANDLOCK_CREATE_RULESET_VERSION`; a missing/blocked kernel interface yields `LandlockUnavailable` and a recorded optional-test **skip**, not fallback-to-no-restriction and not operational success.
- A child-only ruleset handles filesystem write/open-for-write, remove and create rights on ABI v1; file reparenting `REFER` on ABI v2+ and explicit `TRUNCATE` on ABI v3+. No allow rules are installed. No global security settings, cgroups, mount flags, process termination or host permissions are changed.
- Since the calls run after the child is already created, **only later path-based accesses** are restricted. An already-open writable descriptor remains writable, even under successful Landlock.
- `multiprocessing.get_context("spawn")` creates isolated child actors using **real legacy ProjectCTL v2 RunStore** against freshly initialized databases under `pytest.tmp_path`. A bounded Pipe handshake keeps the caller's write attempt after the confinement step. Cleanup kills **only directly spawned child processes**, if needed. The fork-descendant case exits immediately and is reaped by its own test parent.
- Exact source `APPLICATION_ID`/version checks remain v2; no candidate DDL or operational migration runs. No provider operations, real delivery, network requests, authority updates, production service changes or tracing are involved.

### Test acceptance matrix

| Test | Expected laboratory observation | Implication |
| --- | --- | --- |
| Confined legacy RunStore event append | Denied (if Landlock supported) | Kernel can block *new* path-based DB writes in a confined child |
| Confined separate JSON staging/publish | Denied (if supported) | Kernel also prevents this confined child's artifact publication |
| Forked descendant attempts JSON publication | Denied (if supported) | Landlock rule inherited by that child lineage, not unrelated ones |
| Child opens writable JSON descriptor **before** restriction | Write **succeeds** after restriction (if supported) | Filesystem sandbox alone cannot retrofit protection on already-held fds |
| Independent unsandboxed v2 process writes DB / JSON | Both succeed in disposable fixture | Other launch channels and old clients remain wholly unconfined |
| Kernel unavailable, denied by container seccomp, or unsupported architecture | Optional kernel-specific tests skipped with reason; policy remains NO-GO | CI success cannot be cited as containment proof unless actual kernel cases ran |
| Candidate operator claims with one missing dependency | Refused with a specific NO-GO reason | No admission from incomplete/unknown scope |
| All untrusted claim fields set to true | `LAB_REVIEW_ONLY`, **never GO** | This test policy does not authenticate claims or grant migration authority |

Landlock restricts a Linux **subject process**. It is not an all-writer project capability in a system where other processes can access the source directly. A successful child proof says nothing about remote filesystem clients, cross-namespace mounts, privileged bypasses, symlink/hardlink aliasing by outsiders, existing writable SQLite connections, or journal/sidecar coherence.

## Hard blockers for an enforceable cutover

### 1. Closed-world writer inventory and startup ownership

Select a single supported Linux deployment with an owner-controlled dedicated service identity and per-project supervised process scope. Establish the actual complete writer graph: projectctl CLI/direct imports, RunStore event/lease/transition, worker, heartbeat, scheduler, recovery, verifier, integration, external JSON publishers, descendants and inherited descriptors; assess privileged and separate users, containers, other mounts, remote hosts, timers/socket activation and operator shell launches. Require a proved, *independent* startup embargo that covers all launch paths. Unknown clients imply **NO-GO**.

### 2. Quiescence with no legacy fd retained

Before ever considering backup or migration, enforce the stop/drain barrier for all already-running v2 clients; demonstrate that source-writable descriptors, map/shm writers, forked descendants and accidental restart cannot survive or resume. A process simply frozen/paused or placed in a new cgroup is not considered excluded when it can later write. All admissions must be bound to an explicit project/source filesystem identity and maintained across the **entire** backup, migration, outcome-reconciliation and controlled release period. `/proc`, `systemctl`, pidfile and lease snapshots are auxiliary observations, not standalone proofs.

### 3. Filesystem authority and recovery remain distinct

Future M0 must independently specify anchored no-follow path/parent identity for DB+WAL+SHM+JSON, and a private durable WAL-inclusive backup with validated retention and exact recovery. Existing B3a4 lab is not a privileged backup protocol. If publication/fsync/COMMIT is ambiguous, stop, retain evidence, prevent restart and require operator-guided recovery; no automatic retry/restore or replacement of live DB/WAL/SHM.

### 4. Compatibility and trust

Production v3 initialization, M0a v2→v3 schema, v1→v2→v3 compatibility, legacy v2 refusal before mutation, new W1 token/generation fencing, single-transaction verification Seal and R1 read-only WAL snapshot are all **separate** reviewed requirements. A kernel process sandbox does not make the Trace Collector ready and cannot turn `snapshot_proven=False` into true.

## Follow-up operator acceptance: M0f (requires separate approval)

**Candidate:** design and prove an operator-managed **per-project Linux service + filesystem access control** boundary on one declared host/filesystem. Unlike M0e, the test must establish start embargo **outside** the cooperative test launcher, forced/no-leak exit or refusal when processes survive, independent v2 CLI and JSON writers across distinct launch contexts, fork/exec descendant coverage, service-manager death/restart and pre-open fd exhaustion. Include a failure case for each uncontrolled process/namespace/mount/user, and a gate that cannot emit GO on unknown inputs. Test only on disposable fixtures; do not mutate the real installation without separate owner authorization.

Do not assume systemd `mask`, cgroup freezer, chmod or Landlock each independently suffices. If the candidate deployment cannot prove closed-world exclusion, retain **NO-GO** or evaluate M0b's separately governed pre-v3 cooperative rollout.

## Checks and governance

Require exact-HEAD GitHub Actions pytest, compile, public schema-export policy and pinned Codex SDK. The **actual count** of Landlock tests run vs skipped must be reviewed; skipped kernel cases are not a positive isolation result. Linux operator-local smoke is warranted on the intended filesystem/host:

```bash
git fetch origin
git switch --track origin/experiment/m6.0-m0e-landlock-scope-feasibility
source .venv/bin/activate
python -m pytest -q -rs tests/test_m60m0e_linux_landlock_scope_feasibility.py
GIT_PAGER=cat git diff --check origin/main...HEAD
git rev-parse HEAD
python --version
```

**Keep Draft pending owner review, exact-head CI and supported-host test evidence; do not merge without instruction.** Even after merge, production offline admission and migration remain **NO-GO**.
