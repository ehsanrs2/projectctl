# M6.0 M0n — Owned Writable-FD Inode Witness, Verified pidfd Exit and Independent Restart Bypass

**Status: test-only Linux bounded executable evidence; no accepted all-writer migration admission. Production v2→v3 NO-GO.**

**Base:** merged M0m PR #83 at `main@f9f3d6f5bf5429fb820ddb577215c933d399df0f`.
**M0m operator-reported lab:** on disposable Debian/KVM ext4 the exact eight observations were `true`, with decision `NO_GO_PREOPENED_FD_REMAINS_WRITABLE` and `authorizes_migration=false`. This showed root-owned DAC can block ordinary *new* opens for the test UID but does not revoke preexisting file descriptions. M0m provided neither process drainage nor a kernel start embargo.

## Distinct contribution versus M0d, M0f, M0g, M0l and M0m

- M0d already showed that a voluntary launcher can be closed and owned processes stopped while a v2 writer started outside its scope still writes. M0f tested pidfd/process-group boundaries including `setsid` escape. M0g established that cgroup/systemd metadata snapshots are not an enforced all-client admission gate. **M0n does not claim those are solved or repeat a full host-process census.**
- M0n demonstrates a *new paired positive witness* on **specific owned processes and file inodes**: a spawned child has an `O_RDWR` descriptor referring to a disposable **real v2 state.sqlite** inode, and an `O_WRONLY` descriptor referring to dummy project JSON. `/proc/<owned-pid>/fd/<fd>` `st_dev/st_ino` must match the target inode, and `fdinfo.flags` must confirm an actual writable access mode. It is not enough to match text path strings or PID alone.
- For the test-owned process only, first close its voluntary launcher, send SIGTERM via its **`Popen` handle**, wait, then verify a previously obtained **pidfd exit notification**. This is evidence only that *this process* exited and cannot continue using its own former FDs, not proof that no file descriptions were duplicated to descendants, sent over Unix sockets or retained by outsiders.
- A separate writer opened **both writable file descriptions** before the managed drain but was not registered in the launcher. It remains alive and later writes to the same dummy JSON FD and publishes a real v2 `RunStore.append_event`. A **new independent** v2 interpreter can also launch after the voluntary gate closes and write. Both are deliberately required negative results: `NO_GO_UNMANAGED_FD_AND_START_BYPASS`.
- An owned SIGTERM-ignoring test child must cause `NO_GO_UNVERIFIED_OWNED_PROCESS_EXITED_VIA_PIDFD`, not a false drain success; cleanup signals only the test-owned `Popen` child. Wrong inode, readonly FD, invalid fd, missing witness, mistaken truthy integers/strings must fail closed.

**This is an owned-process FD identity and exit pilot, not a kernel/supervisor start embargo.** It cannot enumerate every process capable of accessing the project, establish global FD drainage, prove a closed UID/mount/cgroup namespace, or fence old clients that already hold FDs. In particular Linux pidfds identify the process, **not all possible consumers** of an inherited/duplicated open file description. An apparently quiet tracked PID set cannot prove all writers absent.

## Implementation scope

Three added files only:

1. `scripts/m0n_owned_fd_exit_witness.py`: pure fail-closed decision plus narrow Linux file-descriptor and pidfd observations tied to a *live, test-owned `subprocess.Popen`*. No process creation or host mutation in the module.
2. `tests/test_m60m0n_owned_fd_drain_restart_scope.py`: Linux, unprivileged real-v2 `RunStore` under pytest `tmp_path`, bounded child processes, fdinfo/inode and exit witnesses, resistant-child refusal, external preopened FD and new independent writer bypass.
3. This architecture and guest test procedure.

No changes to `projectctl/` runtime, SQLite schema v2, old M0i/M0j pin, production database, systemd unit, cgroup, userns, mount namespace, AppArmor, actual service, restore, migration CLI or export CLI. No sudo/root needed and no general host-PID enumeration is performed. CI skips the actual Linux tests if pidfds are unavailable; that skip is **not positive proof**. Strict positive kernel evidence must come from a supported Linux runner with real pidfd and `/proc` access.

### Review gates

- Complete exact-head GitHub Actions test/compile/schema-source/export/pinned SDK jobs; review actual pytest skip counts, not only green checks.
- Test scope refuses malformed/wrong inode/wrong writable-mode fdinfo, SIGTERM resistance, failed/unknown exit, and invalid observation values.
- Check for any surviving fixture child after test teardown. Never use `pkill`, uncontrolled `killpg`, whole-system `/proc` scans, production process discovery, or service changes.
- A passing M0n suite shows only bounded controlled FD drain and uncontrolled bypasses, **not authorized offline migration**.

After owner-reviewed merge, on the existing independently confirmed disposable Debian/KVM guest as ordinary `ehsan` (NO sudo):

```bash
cd "$HOME/projectctl-m0k-lab"
git fetch origin
git status --short
git switch --detach origin/main
source .venv/bin/activate
export TMPDIR="$HOME/m0k-ext4-tmp"
python -m pytest -q -rs tests/test_m60m0n_owned_fd_drain_restart_scope.py
```

A *green* M0n negative test does **not** require or permit re-running the root-mode M0m experiment, touching systemd services, or changing production files.

## Architectural decision needed next — avoid endless negative labs

M0n should be the final narrow **diagnostic-only** writer-scope lab before choosing an actual supported deployment and admission method:

- **Path A (selected architecture):** define an *externally enforced, closed-world* offline maintenance procedure on one supported Debian VM deployment, with a dedicated writer UID and supervisor/cgroup ownership, controlled independent restart sources and verified FD/descendant drainage **before** any v2→v3 maintenance. Owner must document explicit operator downtime, accessible mounts/aliases, other UIDs, privileged access and remote writers, and choose a secure way to hold the gate through backup, WAL/JSON recovery and release. Real systemd/cgroup policy belongs in a **separately approved guest-only implementation**, not hidden in this PR.
- **Option B fallback:** ship a v2-compatible cooperative fencing release first and require every legacy binary to be replaced, then execute a separately reviewed cutover; this still cannot forcibly fence preexisting uncooperative processes.
- The owner must select the actual supported topology and external authority before authorizing operational M0, W1 or R1. Unknown actor/FD/alias/remote scope, unsupported kernel, or insufficient privileges always gives **NO-GO**. The exporter still requires independent live-WAL nonmutating reader proof, trusted as-of writer Seal, meaningful assessment and CLI integration.

**The protocol never authorizes migration: `authorizes_migration=false` by construction. PR stays Draft until owner review.**
