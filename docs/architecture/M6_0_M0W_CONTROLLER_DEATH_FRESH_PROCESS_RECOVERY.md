# M6.0 M0w — Real nonroot controller death and independent-process journal replay

**Status: guest-only private nonroot experiment, NOT a reboot/LSM recovery system.** Based on operator-accepted M0v PR #94 (`main@4f1b96168ef1772caf8a73806d65e765ae7ecb3c`), which demonstrated a surviving parent cleaning up after killing its child. M0w moves the persistently recorded effect into a **controller process that is killed by SIGKILL**, then launches an entirely new Python interpreter to reconcile the journal from disk. The surviving ordinary-user test harness orchestrates these two processes. It is **not itself killed** and is **not an independently installed boot-time agent**.

## 1. Exact implemented experiment

- The only path affected by the optional CLI `--exercise` is one **new unpredictable, mode 0700, caller-owned** direct directory under `/var/tmp/projectctl-m0w-*`; no operator-supplied path or executable. The code refuses root on Linux and has no AppArmor, systemd, account, UID/GID, mount, ProjectCTL SQLite/v2/v3, W1/R1 or production API mutation calls.
- The harness exclusively publishes `m0w-intent.json` mode 0600 containing a fixed format, exact random fixture name, constant effect digest, and literally false policy/migration/root authorization fields; then fsyncs file and parent directory. Its fixture's parent directory entry is fsynced too.
- A distinct `python -I -B -c` controller, constrained to a fixed embedded dummy actor, exclusively writes only `m0w-private-effect.bin`, fsyncs file and directory, reports completion through an inherited one-way pipe, then waits. The harness kills only this **specific child process**, checks the SIGKILL wait status, closes the notification pipe and launches an entirely **new** Python interpreter.
- The new process starts with only the fixture's absolute path (validated under the fixed `/var/tmp` with exact prefix, owner, 0700 directory, regular 0600 single-link leaves, no-follow reads, inode identity, content/size and expected leaf names). It reads the fixed persistent journal; **no inherited in-memory journal object or controller Python state** is shared. It removes only two verified known leaves, fsyncs after each deletion, removes the fresh directory and fsyncs `/var/tmp`, returning nonauthorizing JSON.
- `--internal-recover-private` is a test-internal subprocess interface; it is callable by the same ordinary user but is intentionally constrained to **that user's own direct /var/tmp prefix fixture**, not a general cleaner. Its journal and nonce are **not cryptographic authentication**, and the test does **not** defend against arbitrary hostile same-UID actors swapping files concurrently. Do not reinterpret the checks as a MAC/LSM process-origin boundary.
- Unknown leaves, invalid journal bytes, missing journal, altered effect, symlink, hardlink, wrong modes, wrong scope and root identity result in refusal/quarantine, **not blanket cleanup**. If either harness/recovery process is killed at the wrong time, a residual fixture may remain and requires deliberate manual inspection. After the journal leaf is removed and before final directory removal, a second crash can create a **journal-less empty residual directory that this tool deliberately refuses to auto-delete**. That is an unresolved transactional window, not a proven crash-safe global recovery algorithm.

## 2. Why this is not VM reboot, power-loss or global-policy recovery

A SIGKILL of the test controller does **not** kill the surviving harness, simulate a sudden block-device power failure, reboot the VM, or establish a root-controlled recovery owner outside the test transaction. `fsync` file and directory is a necessary persistence measure, not a demonstrated power-cut guarantee on the actual VM/device. The independent fresh interpreter shows only that **a new process can reconcile a known, fixed private journal without the dead controller's memory**.

A future systemd/AppArmor guest-global pilot would need independently confirmed guest-only disposable status and external snapshot/rollback, a root-owned durable recovery record **before any global change**, an independently supervised boot-persistent recovery owner, collision-free unit/profile names, process-label/enforce and GID source evidence, aliases/open FDs/SCM_RIGHTS/restart exclusions, and clean-up observed by a separate authority. The proof obligation persists through **real VM restart** and abrupt loss of the test harness. That privileged work is **not implemented or authorized by this PR**.

The pre-existing M0s negative counterexample also remains: the same synthetic old program writes when granted candidate UID and private supplementary GID. A named systemd AppArmorProfile does not globally prohibit separately launched unconfined same-credential old code. M0w does not solve code/import provenance or group delegation.

## 3. Owner runbook (after review and merge only)

Safe ordinary-user dry inspection and focused tests:

    cd "$HOME/projectctl-m0k-lab"
    git fetch origin
    git status --short
    git switch --detach origin/main
    source .venv/bin/activate
    python -m pytest -q -rs tests/test_m60m0w_controller_restart_recovery_lab.py
    python -B -m scripts.m0w_controller_restart_recovery_lab --inspect

On the previously approved **disposable Debian KVM** guest, separately opt in to the bounded **nonroot** controller SIGKILL:

    python -B -m scripts.m0w_controller_restart_recovery_lab --exercise --acknowledge NONROOT_M0W_CONTROLLER_RESTART_PRIVATE_RECOVERY

Then only **read** the residue list:

    find /var/tmp -maxdepth 1 -type d -name 'projectctl-m0w-*' -print

Do **not** use sudo/root, run on a host/shared system, choose custom fixture paths, kill any other process, or remove unexpected residues automatically. If exit is nonzero or QUARANTINE, do not rerun automatically. The observed successful result should contain `controller_sigkill_observed=true`, `fresh_recovery_process_completed=true`, `journal_replayed_from_disk=true`, `fixture_absent_after_recovery=true`, but the **decision remains NO_GO_FRESH_PROCESS_PRIVATE_RECOVERY_OBSERVED**, and all three authorization flags are false.

## 4. Next separately gated acceptance

| Gate | Required future independent witness | Status |
| --- | --- | --- |
| W0 | No foreign/shared mounts, disposable VM source/UID/GID scope, zero host routes | UNVERIFIED for global pilot |
| W1 | Independent actual **controller-orchestrator death**, boot-time recovery authority and durable journal outside its process tree | UNVERIFIED |
| W2 | **Actual disposable VM reboot or abrupt power removal** after a root-owned prepared journal, recover and re-inspect before reuse | UNVERIFIED |
| W3 | Crash at every write/remove stage, idempotent recovery even in journal-less final unlink window | UNVERIFIED |
| W4 | Root-exclusive collision-free unit/profile publication and recovery ownership | UNVERIFIED |
| W5 | Loaded enforcing kernel AppArmor policy, actual service process label, correct executable/library/import provenance | UNVERIFIED |
| W6 | Exclusion of all untrusted group delegation, direct same-UID+GID old actors, alternative interpreter and inherited FDs | UNVERIFIED |
| W7 | Independently verified global unit/profile absence, no stale service/FD/process/namespace | UNVERIFIED |

M0w only provides a **subprocess-level**, nonroot private-fixture witness contributing to the conceptual W1 design. It does not mark W0–W7 passed for any actual guest-global policy experiment.

**Maximum acceptance:** M0W_NONROOT_FRESH_PROCESS_RECOVERY_REVIEW_ONLY. M0o P0–P9, M0r R0–R9, M0t T0–T12 remain UNVERIFIED. Operational v2→v3 M0, W1 trusted Seal, R1 WAL reader, Collector/CLI: **NO-GO**.
