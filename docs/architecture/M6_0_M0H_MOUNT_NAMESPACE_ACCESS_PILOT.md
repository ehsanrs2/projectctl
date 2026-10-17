# M6.0 M0h — Disposable Linux Mount-Namespace Read-only View and Alias Bypass Pilot

**Status:** TEST-ONLY, **NO-GO** for all-writer exclusion and operational v2→v3 migration.
**Baseline:** `main@5be3ddf87fe9191c593a3744dc6cfd44bf0453a9` (PR #77 M0g merged).
**Governing:** ADR-039/040 Path A; M0a unified v3 candidate, M0b legacy bypass, M0c offline admission/backup contract, M0d supervised processes, M0e Landlock confinement, M0f session/pidfd escape, M0g cgroup v2/systemd observational gate.
**Scope:** exactly one test file plus this document; no `projectctl/` production files changed.

## What is proved (and what is not)

M0g only *observed* cgroup-v2/systemd properties. M0h attempts an **actual Linux VFS write restriction** inside a disposable, unprivileged child user+mount namespace. The child takes an explicitly named temporary ProjectCTL v2 source directory, bind-mounts it onto a second temporary directory, remounts **that view** read-only, and tries to append a real RunStore v2 event or publish a dummy JSON leaf through the restricted path.

On a host supporting the precise `unshare --user --map-root-user --mount --fork` arrangement and mount operations, these writes should be denied by Linux. That is **only a view-scoped enforcement observation**, not a universally read-only SQLite database or project. The same underlying source remains writable through its original alias (even inside that mount namespace), and an independent old v2 interpreter that never entered the namespace still has its ordinary access.

Thus this experiment intentionally reproduces the bypass that blocks operational maintenance admission. The best synthetic gate result is `OPERATOR_REVIEW_ONLY`, never GO. No false equation between a kernel sandbox and a complete external writer/start embargo is permitted.

## Exactly bounded mechanism

The implementation is `tests/test_m60m0h_mount_namespace_access_pilot.py`. All fixtures are freshly initialized real ProjectCTL project-state **v2** under pytest `tmp_path` with a real RunStore/Run event. A separate, explicitly owned Python child is invoked via unprivileged util-linux `unshare` for the optional kernel checks:

1. Create a private **user + mount namespace in the child**. If user namespaces, capabilities, or namespace/mount operations are blocked by host security policy, **skip those kernel-specific tests with a reason**. Do not downgrade to unconfined execution, and never count skipped tests as successful isolation evidence.
2. Switch mount propagation recursively to `MS_PRIVATE` *before* bind mounting, preventing private-child mount operations from propagating to the parent. Bind-mount only the disposable source onto the disposable view, then `MS_REMOUNT|MS_BIND|MS_RDONLY` the view. This sets the VFS read-only flag **only on that mount point**, not the original source mount or its underlying filesystem.
3. Attempt a real v2 `RunStore.append_event` using the restricted view, or dummy JSON creation and replacement under `.projectctl` through that view. Reject unexpected errors instead of treating any exception as proof of kernel enforcement.
4. Deliberately attempt the same SQLite and JSON writes via the *unrestricted original source path* **within the same sandbox**. These must remain possible, demonstrating that read-only bind mounts do not revoke other aliases.
5. Investigate an already-open writable JSON descriptor at the bind view before the remount. Depending on kernel/mount semantics, remount may refuse or the post-remount write may succeed or fail; **none** is sufficient proof of closing all old open writable handles. The test refuses to claim universal access revocation from this experiment.
6. Separately launch an independent, unsandboxed Python interpreter that constructs real v2 RunStore and appends an event after the disposable sandbox experiment. This negative proof remains enabled even on hosts that skip optional mount-namespace checks.
7. Keep all prototype decision flags explicitly untrusted. Every missing gate (all aliases, preopened descriptors, all legacy processes, independently enforced startup embargo, supervisor lifecycle, namespace/host identity, and WAL+JSON backup/recovery) yields a specific `NO_GO_...`. Even if all are asserted true, the result is **OPERATOR_REVIEW_ONLY**.

No installed systemd unit, host PID, privileged host mount, cgroup, service account, network share, worker, credential or production file is modified. No `projectctl migrate`, schema v3 DDL, RunStore API, version constant, public Trace reader, Seal writer or release change is introduced.

### Threat matrix

| Attempt | Experimental expected outcome | Admission interpretation |
| --- | --- | --- |
| New SQLite event through child-only read-only bind view | Linux denies if kernel pilot supported | Read-only **path view** only |
| New JSON staging/publish through view | Linux denies if supported | Does not fence external JSON writers outside namespace |
| Same underlying SQLite through original source alias | Allowed even while view is read-only | **NO-GO:** alias bypass |
| JSON through original source alias | Allowed even while view is read-only | **NO-GO:** sidecar bypass |
| Writable descriptor opened before view remount | Refusal, denial, or continued write depending on kernel | **NO-GO:** not proof of FD exhaustion |
| Independent interpreter outside namespace | Allowed to append event | **NO-GO:** no startup/external-writer embargo |
| No user namespace/mount privilege or utility | Host-specific kernel tests skipped | **NO-GO:** no actual supported-host enforcement observation |
| Every hypothetical external gate marked true | `OPERATOR_REVIEW_ONLY` | Unauthenticated claims never authorize migration |

The traditional mount(2) bind+remount sequence is **not an atomic security transition**. A temporary window between bind and read-only remount can allow writes. Nor does a nonrecursive remount make arbitrary nested submounts readonly; the experiment uses a fresh directory with no declared nested mounts. Source ancestry, hardlink/symlink aliases, different mount namespaces, shared UIDs, remote clients and privileged processes remain unexcluded. These are blockers, not optional hardening.

Reference kernel semantics: [mount(2), MS_REMOUNT+MS_BIND](https://man7.org/linux/man-pages/man2/mount.2.html), [mount(8), read-only bind is per-mount](https://man7.org/linux/man-pages/man8/mount.8.html), and [unshare(1), user/mount namespace and propagation](https://man7.org/linux/man-pages/man1/unshare.1.html).

## Required next decision: M0i, separately approved

**M0h cannot legitimately certify a real closed-world access embargo** on an unspecified machine. Before considering operational M0/W1, the owner must pick a *concrete* Linux host, local filesystem, service manager, dedicated project authority account and deployment topology, and explicitly consent to bounded disposable isolation tests on that host. Required gates:

- Enforce a full-process/start-and-filesystem boundary: no separate same-UID direct import/CLI, independent unit/timer/socket, provider subprocess, `setsid` descendant, outside cgroup/namespace, mount alias or remote writer can access source DB/WAL/SHM **or** independent Verification/Evidence JSON.
- Demonstrate exact scope binding and source/backup path ownership, including all parent ancestors, existing write FDs, handles, symlinks/hardlinks, nested mounts, mount propagation, and supervisor restart/stop/failure semantics. Verify a *real* admission and restart prevention rather than a sampled unit/cgroup state or a synthetic checklist.
- Hold that external exclusion continuously across quiescent source preflight, private WAL-inclusive durable backup, future unified v3 migration transaction, ambiguous outcome reconciliation and operator-approved release. Prevent old v2 clients from reopening; no automatic restore/retry after unknown COMMIT.
- If real enforcement depends on privileged systemd/cgroup/mount policy, implement it **only** under an separately reviewed operator-run acceptance plan. This PR deliberately has no host-control commands and makes no claim that CI runners match the future deployment.
- Production schema version v3, all-writer generation/token fencing and single trusted Verification Seal transaction are still separately reviewed W1/M0 gates. R1 source-WAL reader and public Trace assessments remain independently NO-GO.

If no closed-world single-host deployment is available, return **NO-GO** and reconsider M0b Option B's explicit cooperative rollout; a new voluntary lock cannot fence existing old clients.

## CI and governance

Require exact-head GitHub Actions pytest, Python compile, public schema/export policy and pinned SDK. Record **number and reasons for skipped namespace tests**. A green suite with all optional namespace tests skipped proves only the unconditional negative/policy cases, not the read-only kernel behavior.

Operator-local focused smoke, with no host privilege or service mutation:

```bash
git fetch origin
git switch --track origin/experiment/m6.0-m0h-mount-namespace-access-pilot
source .venv/bin/activate
python -m pytest -q -rs tests/test_m60m0h_mount_namespace_access_pilot.py
GIT_PAGER=cat git diff --check origin/main...HEAD
git rev-parse HEAD
python --version
```

**Keep Draft pending exact-head CI, operator-supported host review, and owner approval. Do not merge automatically.** M0h's result is an intentionally narrow view-enforcement pilot and negative counterexamples, NOT a working migration gate.
