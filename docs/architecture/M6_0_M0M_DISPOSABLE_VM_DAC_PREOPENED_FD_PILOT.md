# M6.0 M0m — KVM-only Disposable DAC New-Open Boundary and Preopened-FD Leakage

**Status:** bounded **REAL OS DAC LAB** proposal only; operator-controlled root execution inside a disposable, independently reviewed Debian/KVM guest is optional and must be separate from CI. **NO-GO** for any production v2→v3 migration.
**Baseline:** merged M0l PR #82, `main@c24eecd7bf3c94e80d444399a85394c57bbf4b67`.
**Files:** `scripts/m0m_vm_dac_embargo_pilot.py`, `tests/test_m60m0m_vm_dac_embargo_contract.py`, this architecture note. No changed production `projectctl/` modules, migrations, services, mount rules, cgroups or CLI registration.

## Why M0m is different from another negative policy model

M0l showed that a new *unmodified v2* writer may open `state.sqlite` and publish JSON after a sampled "zero active writers" observation, and that a previously opened JSON fd may survive `chmod`. M0m adds an **opt-in, actual Linux DAC enforcement trial** with a *newly created* ProjectCTL v2 fixture under `/var/tmp/projectctl-m0m-<random>` in a KVM guest.

It tests a controlled, externally applied **ownership boundary** rather than asking the legacy RunStore to obey a new lock:

1. Verify KVM/QEMU Linux VM, guest-local **ext4** for `/var/tmp`, root invoked via `sudo` from a real **nonroot** UID/GID, and an explicit, exact disposable-lab acknowledgment. There is **no user-specified source path**.
2. Create a temporary root-owned top directory (mode 0711, so test actor can traverse but never rename the root), initialize **real disposable ProjectCTL v2** `.projectctl/state.sqlite` and a dummy JSON leaf; reject unusual symlink/hardlink/device entries before ownership transitions.
3. Transfer **only the freshly created child `.projectctl` tree** to the nonroot invoking actor; demonstrate its unchanged legacy `RunStore.append_event` and independent staged JSON replacement both work *before* the barrier.
4. Spawn an owned legacy actor that has **already opened** a writable descriptor for one fixture JSON file. Keep that descriptor open across the following state change; only this test-owned child can be killed during cleanup.
5. The root-controlled lab takes back ownership of the **entire fixture `.projectctl` tree**, setting directories 0700 and regular files 0600. This is a *real DAC new-open denial* for the nonroot actor, not just an advisory lock or simulated claim. The root-owned project top directory remains protected.
6. Start fresh independent actor processes *after* the DAC change. Probe `open(O_WRONLY)` on a real dummy file and require `EACCES`/`EPERM`; independently attempt real `RunStore.append_event` and staged JSON replacement; verify both fail and the SQLite event count / dummy JSON bytes remain unchanged.
7. Resume the **previously opened** JSON FD and observe it remains writable despite root ownership/mode changes. The strongest normal result is deliberately **`NO_GO_PREOPENED_FD_REMAINS_WRITABLE`**, with `authorizes_migration=false`.

This is **NOT a kernel-enforced process start embargo**: a new process can still run but cannot open **this fixture state directory** through its ordinary UID. It does not close existing fds; it does not prove a complete project writer inventory; it cannot exclude a writer with different filesystem credentials, root/CAP_DAC_OVERRIDE, remote mounts, a privileged helper or missing artifact paths. Future policy must also prevent attempts to modify a yet-unprotected file set, and establish drain/quiescence *before* applying this barrier. Do **not** generalize this private fixture to a current project.

## VM-only invocation after separate operator review of code and PR merge

**Do not run root mode on the Ubuntu host, production machine, project directory or mount. Never invoke the whole pytest suite with sudo.**

Inspect from the existing unprivileged Debian VM, after merging this PR and updating main:

```bash
cd "$HOME/projectctl-m0k-lab"
git fetch origin
git status --short
git switch --detach origin/main
source .venv/bin/activate
python -B -m scripts.m0m_vm_dac_embargo_pilot --inspect
findmnt -T /var/tmp -no SOURCE,FSTYPE,TARGET
systemd-detect-virt --vm
```

Expected `--inspect` status: `OWNER_MUST_REVIEW_DISPOSABLE_GUEST`; this is *not* an attestation. Confirm VM is disposable and has **no connected production host mounts**. No `--run` until the owner has independently checked this. Root execution is **only** for a dedicated and reviewed guest:

```bash
sudo "$PWD/.venv/bin/python" -B -m \
  scripts.m0m_vm_dac_embargo_pilot \
  --run \
  --acknowledge DISPOSABLE_KVM_GUEST_ROOT_DAC_LAB
```

A successful bounded **negative** experiment emits a single JSON result with these exact facts, never `GO`: baseline v2 DB & JSON writes worked; new actor's direct file opens were denied by DAC; new legacy DB/JSON writes were denied and data unchanged; **old FD still wrote**. The top-level `decision` is `NO_GO_PREOPENED_FD_REMAINS_WRITABLE`, `authorizes_migration` is `false`. Unexpected results, refusal or incomplete actor observations are `NO_GO_*` and nonzero exit.

The lab handles normal cleanup of *its own random temp tree and children*; it cannot promise cleanup after a crash, SIGKILL, power loss or root interruption. If interrupted, **do not bulk delete files matching a glob**; inspect exact leftover fixture directory identity/content before any manual cleanup. No production authority ever enters the trial.

## Exact CI and limits

Ordinary nonroot GitHub CI runs only nonprivileged refusal/decision unit tests. It **must not** invoke `--run`, elevate permissions, modify `/var/tmp` content, signal unrelated PIDs or claim positive kernel proof from mock checks. CI success does not replace an operator-reviewed guest run. A later, separate VM evidence collection may record real observation outputs with a pinned SHA and private evidence bundle, but the M0i/M0j/M0k provenance pin applies to M0h only and MUST NOT be reused for M0m without a dedicated reviewed protocol.

**Next architecture decision AFTER M0m:** Choose a concrete operator-supported deployment and *independent start/stop and FD-drain authority* (supervisor/service manager + dedicated UID and filesystem boundary). Without a complete actor/fd/alias/remote-path inventory, our strongest claim remains that **fresh nonprivileged opens to a narrowly scoped root-owned fixture were denied**, not that arbitrary old v2 clients are globally fenced.

**Production M0, W1 trusted writer Seal, R1 WAL Reader, Collector/CLI and migration remain NO-GO. Keep this PR Draft until exact-HEAD CI + owner review; never auto-merge.**
