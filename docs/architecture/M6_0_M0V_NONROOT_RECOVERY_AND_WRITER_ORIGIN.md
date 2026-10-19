# M6.0 M0v — nonroot private recovery witness and credential-origin closure

**Status:** Focused **nonprivileged** real SIGKILL/file-journal experiment, plus strictly nonauthorizing writer-origin claims. **NO** privileged policy installation, actual systemd unit, AppArmor profile loading, migration, W1 Seal, R1 WAL reader, Collector or public CLI work.

**Baseline:** merged M0u #93 at `main@5158211afcf7cbb25387c40c6da8ec80565e7114`. Operator-reported Debian KVM tests and the fixed-path nonroot AppArmor parser smoke both passed in their narrow scope; M0u is a *hypothetical* global kernel-policy fault model with no actual persistent recovery process. Earlier M0s root experiment showed old synthetic code **with both candidate UID and private writer GID can still write**. Prior operator authorization to run M0s with root does **not** extend to any systemd/AppArmor/M0v global change.

## 1. What actual behavior is observed here

M0v replaces one narrow *hypothetical* M0u recovery transition with a **real nonroot filesystem test**:

1. Create only a new random `/var/tmp/projectctl-m0v-*` directory owned by the ordinary caller, permissions 0700; neither CLI path nor identity is caller-configurable. The parent directory must be non-symlink. The test also accepts a private `pytest tmp_path` **internally**, not through CLI.
2. `fsync` the parent directory, exclusively create a mode-0600 journal containing a fixed format, the exact private directory name, a checksum of a fixed harmless effect marker, and explicit nonauthorization flags; `fsync` journal **and directory**.
3. Launch a fixed embedded Python child with `-I -B -c`, limited environment and inherited one-way pipe. It creates **only** `m0v-effect.marker` in that private directory, `fsync`s file + directory, acknowledges, and waits.
4. After acknowledgement, the parent **actually sends SIGKILL only to its own child subprocess handle**; it verifies the wait status. The parent remains alive and independently attempts recovery of the private journal/marker after the worker has died.
5. Recovery refuses unknown children, symlinks, hardlinks, wrong owner/mode, unexpected contents, changed directory identity and missing/inconsistent journal. Known leaves alone are unlinked, their parent directory synced, then the newly created directory is removed and its base directory synced. No blind recursion/glob deletion.
6. Regardless of success, report **NO_GO_PRIVATE_SIGKILL_RECOVERY_OBSERVED**, `authorizes_root_trial=false`, `authorizes_policy_install=false`, `authorizes_migration=false`.

The test contract injects wrong journal bytes, modified effect bytes, unknown files, journal symlink, effect hardlink, unsafe mode and arbitrary project path; **all refuse destructive cleanup**. A real child SIGKILL test runs in ordinary-user Linux CI and in the optional operator `--exercise` mode; all other nonroot tests run on disposable `tmp_path` trees.

**Important durability nuance:** Linux `fsync` on a file is not sufficient to persist its directory entry; the containing directory also requires `fsync` ([Linux fsync(2)](https://man7.org/linux/man-pages/man2/fsync.2.html)). The lab explicitly performs both. Successful calls and SIGKILL recovery **do not prove power-loss, host crash, storage controller flush, reboot replay, external controller survival or durability of real AppArmor/systemd global state**. The recovery parent survives its worker; it is not an independent boot-persistent root restoration agent. A same-UID concurrent attacker/race is outside this private-fixture test, not a proven secured production boundary.

## 2. What it explicitly does NOT do

- No `sudo`, credentials changes, UID/GID actor operations, systemd service/manager interaction, AppArmor parser or kernel policy load/unload.
- No SQL, actual v2/v3 database, WAL/SHM or JSON publication, global FD enumeration, system reboot, power-loss simulation, or guest process-kill search.
- No filesystem writes outside one fresh random **ordinary-user-owned** test fixture. The fixed `/var/tmp` is only used after explicit opt-in. All path/mount/privilege authorities remain NO-GO.
- It does **not** install or supervise an independent recovery agent. An incomplete or corrupted fixture may remain following process death, abnormal stop or untrusted entry. There is intentionally **no general-purpose cleanup command** in the CLI. Do not manually delete unknown residue or rerun automatically; inspect ownership and leaf set independently.
- Nonroot CI does not authorize root usage; `--exercise` strictly rejects root and requires an exact acknowledgement. `--inspect` reads neither the filesystem nor external process state.

## 3. Credential/code-origin gates — separate from private-file cleanup

`scripts/m0v_credential_origin_review.py` defines eleven untrusted review assertions, all NO-GO. The hard stop is a reachable **untrusted old program with candidate UID plus private supplementary writer GID**: the M0s experiment showed the raw Linux DAC write capability. Even if someone marks all other assertions true, the result is `NO_GO_CREDENTIAL_AND_EXECUTION_ORIGIN_NOT_INDEPENDENTLY_ATTESTED`, never an admission.

| Surface | Required independent future witness | Unsafe condition |
| --- | --- | --- |
| Guest/root trust | Confirmed isolated VM plus explicit trusted admin scope | Unbounded root or shared host/production mount |
| GID distribution | All routes via root, polkit/sudo, systemd-run and group-delegation helpers audited | Untrusted code can request both UID/GID |
| Unit provenance | Root-owned exact unit/drop-in/trigger bytes, env, ExecStart and immutable actor closure | Unit changes or nonreviewed actor inherits group |
| Interpreter/import provenance | Actual executed interpreter/binary, dependencies, dynamic libraries, PYTHONPATH/sitecustomize and native imports pinned at run time | Hash-check/exec race or writable imports |
| Independent startup | Old Python -m/-c/script or alternative interpreter cannot acquire writer credentials | Direct same-UID + group writer available |
| FD and mount world | Preopen descriptors, SCM_RIGHTS transfers, WAL/SHM/JSON staging directories, namespaces and restart paths all covered | Writable inherited FD or alias |
| MAC verification | Kernel loaded enforcing AppArmor policy plus actual target PID label and bounded execution transitions | Merely profile load or service status |
| Recovery owner | Dedicated trusted owner independently handles reboot/crash; durable journal and proof of cleanup | Only parent/try-finally survives |
| Cleanup attestation | Independently verified absence of named unit/profile, credentials and all fixture artifacts | Stale global LSM/unit resource |

**M0v provides NO real witness for any of those.** Only a limited nonroot fixture recovery is exercised. M0t T0–T12 remain UNVERIFIED; the threat model that includes actors capable of obtaining both UID and GID is not solved by unit-local AppArmor.

## 4. Operator runbook after human review/merge

First, **ordinary-user only** and with a clean checkout:

    cd "$HOME/projectctl-m0k-lab"
    git fetch origin
    git status --short
    git switch --detach origin/main
    source .venv/bin/activate
    python -m pytest -q -rs tests/test_m60m0v_private_recovery_lab.py tests/test_m60m0v_credential_origin_review.py
    python -B -m scripts.m0v_private_recovery_lab --inspect

The optional actual nonroot SIGKILL private-fixture experiment is **only** for the previously reviewed isolated disposable Debian VM, without host/production mounted data:

    python -B -m scripts.m0v_private_recovery_lab --exercise --acknowledge NONROOT_PRIVATE_M0V_SIGKILL_RECOVERY_LAB

It writes only to a newly created private directory beneath `/var/tmp` and sends SIGKILL only to its own test child. **Never prepend sudo.** If the result is `QUARANTINE_PRIVATE_FIXTURE_REVIEW_REQUIRED` or fails to remove its fixture, stop; do not automatically run cleanup. Verify any residual directory with a read-only listing:

    find /var/tmp -maxdepth 1 -type d -name 'projectctl-m0v-*' -print

Expected bounded result: `NO_GO_PRIVATE_SIGKILL_RECOVERY_OBSERVED`, all authority flags false, `fixture_absent_after_recovery=true`. That is *completion of the nonroot private fixture experiment* only, not approval of a systemd/AppArmor installer.

## 5. Separate next authority boundary

Any **real guest-global root** pilot must be an independently reviewed and explicitly authorized new PR, ideally on an expendable restored VM snapshot, and must include **a surviving recovery owner external to the test process**, immutable actor/dependency closure, collision-resistant root-only installation, kernel/AppArmor enforce-state evidence, direct old-code both-credential tests, and audited cleanup **after simulated reboot or service crash**. If crash-safe recovery and exact scope cannot be established, reject the installer and retain NO-GO.

**Acceptance ceiling:** `M0V_NONROOT_PRIVATE_SIGKILL_RECOVERY_REVIEW_ONLY`. M0o P0–P9, M0r R0–R9 and M0t T0–T12 remain unverified. Production v2→v3 migration, trusted W1 Seal, R1 WAL reader, Collector and public CLI remain **NO-GO**.
