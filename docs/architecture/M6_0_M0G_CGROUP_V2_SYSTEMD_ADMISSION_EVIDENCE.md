# M6.0 M0g — Linux cgroup-v2 and systemd Admission Evidence Gate

**Status:** read-only OS observation/negative characterization on disposable v2; **NOT** an operational maintenance controller or a proven full-writer exclusion boundary.
**Baseline:** `main@b16327ca4ad21ebe04514d2cd1201b219107b395` (PR #76, M0f merged).
**Authority:** accepted ADR-039/040 Path A; M0a contract, M0b legacy-process bypass, M0c offline policy, M0d tracked-process stop, M0e Landlock per-subject enforcement, M0f process-group/pidfd escape.
**Files:** `tests/test_m60m0g_cgroup_v2_evidence_gate.py` and this document. No code under `projectctl/`.

## Decision

M0f confirmed that a descendant escaping a process group with `setsid()` can still write through a real old v2 RunStore. A cgroup has different kernel membership semantics: a plain `setsid()` changes the process's session/group, **not its cgroup**. M0g makes this distinction executable on a Linux test host and adds strict *read-only* observation parsing for unified cgroup v2 and an explicitly selected systemd unit.

**This does not make a stopped unit, an empty `cgroup.procs`, a masked unit, or a cgroup snapshot an OS-enforced global embargo.** A sibling cgroup, same-UID interpreter invoked directly, other service, detached process, mount alias, separate namespace or remote writer can still access project authority if file permissions and deployment do not independently prevent it. An existing writable database handle also survives observational checks. There is no universal method to retroactively restrain uncooperative old v2 writers using only cgroup sampling.

The model may return `OPERATOR_REVIEW_ONLY` if *all untrusted claims* are supplied as true, **never** production GO. Production v2→v3 admission remains **NO-GO**.

## Concrete implementation

The two newly added files are confined to `tests/` and `docs/architecture/`.

1. A strict unified-cgroup-v2 parser accepts only exactly one `0::/absolute/scope` line. It rejects v1/hybrid entries, missing/duplicate entries, traversal, malformed paths and control characters instead of guessing a service scope.
2. A parser for `cgroup.events` requires unambiguous `populated` and `frozen` flags and explicitly rejects invalid/duplicate data. `populated=1` blocks even when direct `cgroup.procs` is empty: descendant cgroups can contain live processes.
3. The direct PID-list parser refuses malformed, duplicate or excessively large enumerations. A strict systemd property parser requires `ActiveState`, `SubState`, `ControlGroup`, `Restart`, `TriggeredBy` and `UnitFileState` on one owner-selected synthetic fixture. Unknown/absent properties cannot silently become proof.
4. The admission review refuses unit/cgroup identity mismatch, populated/frozen scope, active/not-dead unit, restart policy, known activating dependencies and missing independent evidence about source identity, external writers, new launch paths, preopened FDs, namespace/mount aliases, supervisor restarts or recovery.
5. **Real Linux host experiment:** an independent Python child constructs an actual ProjectCTL **v2 RunStore** for a disposable `tmp_path` database. One variant calls `os.setsid()`, another does not. Both compare their `/proc/self/cgroup` membership before/after and write an event successfully because neither has been placed under an enforcing maintenance embargo. On an unavailable/non-unified cgroup interface this host-dependent case **skips**; it does not claim a green isolation proof.
6. There are **no `systemctl`, `cgroup.kill`, `cgroup.freeze`, cgroup.procs writes, mount/unshare, privilege changes, signals, service restarts, firewall changes, chmod changes or migrations**. Systemd properties are only synthetic, not fetched by executing a host command. No host process is enrolled/stopped or affected by child tests.

## Why the evidence is insufficient

| Observation | What it can actually establish | What it CANNOT establish |
| --- | --- | --- |
| `/proc/PID/cgroup` exact v2 membership | One sampled PID's cgroup path in its visible namespace | All writer processes or future launch admission |
| `setsid()` preserves cgroup | Process group/session is different from cgroup membership | That processes cannot leave a delegated cgroup or be independently created outside |
| `cgroup.procs` empty | No directly listed PIDs at that sample | Emptiness of subtree; race freedom; no alternative launch |
| `cgroup.events populated=0` | No populated descendants *at sampling instant* | Continuous barrier, remote writers, alternate cgroups, preopened handles |
| `systemd ActiveState=inactive` | A sampled unit-state field | All services/processes touching source stopped |
| `UnitFileState=masked` | A sampled unit file property | All same-UID direct CLI, socket/timer/other launcher and pre-existing writers prevented |
| Source DB v2 + matching backup sample | Historical/observed database state | A consistent cross-store epoch or complete WAL-inclusive recovery admission |

`frozen=1` is **not** accepted as stopped; a frozen process can resume. Rechecking unit/cgroup state twice cannot authenticate total authoritativeness or continuity during the future SQLite backup, v3 COMMIT, outcome reconciliation or service handoff. Do not use this parser from the read-only R1 Trace Collector; it is not a safe live-WAL source reader.

## Future deployment acceptance: M0h, separately approved

M0g intentionally stops at observation. The next *meaningfully different* implementation must choose one owner-approved, **concrete** deployment (Linux distribution/kernel, systemd version/manager, local filesystem, per-project service account, cgroup v2 delegation rules, identities and start channels). Prove a real closed-world barrier on a disposable project, in an **operator-controlled sandbox** with independent admission/restart and filesystem controls:

1. Establish a complete source-verified inventory of every direct RunStore/CLI, Worker/heartbeat, verifier, integration, recovery and external JSON writer, including descendants, DB/WAL/SHM FDs, mounts, remote/NFS and alternate PID namespaces.
2. Show a **real** enforced startup embargo independent of a cooperative Python flag. Attempts from already-running v2, independent same-UID direct Python, another authorized user, alternate systemd unit/timer/socket, delegated cgroup and `setsid` escape must each be refused or force an explicit NO-GO. Document privileges needed; no global modification on an unreviewed host.
3. Establish a filesystem authority boundary that excludes those writers from **both** SQLite and independent JSON leaves, including alias paths and preopened writable descriptors. Stopping just one service unit is not enough. Unknown outside clients, privileged bypass or remote writers mandate NO-GO.
4. Keep the barrier enforced without gaps through anchored source preflight, durable owner-private WAL-inclusive backup, v2→v3 migration, ambiguity reconciliation and controlled release. Add crash/power-loss, fsync, full disk, watchdog restart, process leak and partial commit failure tests; never auto-restore on ambiguous COMMIT.
5. Produce machine-verifiable bound host/supervisor/source evidence and a security review that clearly distinguishes actual kernel enforcement from asserted checklist values. **Only after separate owner approval** may an operational migration and trusted W1 writer be considered. R1 safe nonmutating WAL Reader remains independently blocked.

If this supported deployment cannot provide enforceable isolation, retain the M0b Option A **NO-GO** and consider the explicitly reviewed two-stage cooperative pre-v3 rollout (Option B); neither can turn old noncooperative processes into trusted writers retroactively.

## Acceptance and governance

Require exact-head hosted GitHub Actions full pytest, compile, public schema policy/export and pinned Codex SDK. Record test pass/skip counts; a skipped Linux process test is not a successful kernel acceptance. The focused operator-local test may be run without privileges or service changes:

```bash
git fetch origin
git switch --track origin/experiment/m6.0-m0g-cgroup-v2-evidence-gate
source .venv/bin/activate
python -m pytest -q -rs tests/test_m60m0g_cgroup_v2_evidence_gate.py
GIT_PAGER=cat git diff --check origin/main...HEAD
git rev-parse HEAD
python --version
```

**Keep Draft until code/architecture review, exact-head CI and owner-controlled merge.** Neither this PR nor its merge may authorize `projectctl migrate` v2→v3, any production service action, a DB version bump, new W1 Seal authority, privileged Worker access, or R1 WAL Trace export.
