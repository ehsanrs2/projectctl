# M6.0 M0u — Guest-global AppArmor/systemd transaction and recovery fault model

**Status: OFFLINE REVIEW ONLY; no kernel/service installer, no root execution.** After the M0t review-only service/LSM envelope PR #92 merged as `main@bd64f836e4605575a720346e8cfa3ccdd294b032`, the operator reported successful Debian nonprivileged tests and no visible leftover `/var/tmp/projectctl-m0s-*` directories. The earlier approved M0s **disposable root** experiment showed 9/9 expected fixture observations, including the critical negative: synthetic old code with candidate UID + private writer GID can write. That approval is **not** permission to install a guest-global kernel profile/system unit now.

M0u fills one implementation prerequisite before a future *real* independent-privilege pilot: specify, in an executable and failure-injected **model**, the ordering and persistent rollback requirements for two distinct global resources: a kernel-loaded AppArmor policy and a root-controlled systemd unit. A process-local finally block alone cannot demonstrate rollback after SIGKILL, power loss, reboot or a detached service. The model never operates on the guest kernel.

## 1. Threat model and nondelegation

An AppArmorProfile assignment for a systemd unit is limited to its launched process. It does **not** confine arbitrary independent candidate-UID old Python with the private write GID. The intended **Model A** remains a trusted-root deployment boundary: root controls every route to the private supplementary GID and a verified immutable service. This **must be proven for the declared threat actors** and does not apply against hostile/unreviewed root or uncontrolled group delegation. **Model B** (mandatory denial of old code even with both credentials) remains unsupported; do not assert that unit-local AppArmor enforces it.

Sources:
- [systemd.exec, AppArmorProfile and the + command prefix](https://www.freedesktop.org/software/systemd/man/257/systemd.exec.html): preloaded profile is required, service-child scope, bypass conditions and optional-error prefix are significant.
- [Debian AppArmor parser 4.1.0](https://manpages.debian.org/trixie/apparmor/apparmor_parser.8.en.html): `--skip-kernel-load` avoids policy load, and `--skip-cache` avoids parser cache effects. A parser success is **not** kernel enforcement proof.
- [Debian AppArmor profile language](https://manpages.debian.org/trixie/apparmor/apparmor.d.5.en.html): process profile mode and execution attachment matter; kernel features/ABI may downgrade unsupported rules.
- [Linux credentials](https://man7.org/linux/man-pages/man7/credentials.7.html) and [open file descriptions](https://man7.org/linux/man-pages/man2/open.2.html): group assignment and preopened FD issues cannot be replaced by an AppArmor unit setting.

## 2. Fixed artifacts added by this PR

- `docs/architecture/m0u/m0u-lifecycle-intent.json`: fixed **nondeployable** manifest with intentionally unresolved unique service/profile names, new guest fixture, pinned actor, durable root-only recovery journal and independent recovery owner; all privileged/install/migration authority values are literally false. No user or source path can be supplied through the model CLI.
- `scripts/m0u_policy_lifecycle_model.py`: only reads that manifest and simulates interruption at every lifecycle point. No subprocess, no kernel inspection, no policy parsing or installation, no filesystem write, no root identity change, and no cleanup action.
- `tests/test_m60m0u_policy_lifecycle_fault_model.py`: unprivileged CI tests for exact manifest drift, all strict evidence claims, cross-credential old-code counterexample, invalid/duplicate events, missing independent cleanup, each failure type at every point, and refusal of install/run/root/restore actions.
- `scripts/m0u_nonroot_apparmor_compile_probe.py` plus `tests/test_m60m0u_nonroot_apparmor_compile_probe.py`: optional **actual Debian 4.1 parser subprocess**, strictly nonroot, fixed root-owned `/usr/sbin/apparmor_parser`, embedded unattached harmless named syntax sample over stdin; flags `--skip-kernel-load --skip-cache --skip-read-cache --names -`; no kernel load, cache read/write or generated file requested. It cannot accept a caller profile/path, uses bounded time/output and always NO_GO. The test suite mocks the parser in CI; **only operator running it on Debian can obtain a real parser-exit observation**. Success cannot show a real M0t policy is valid or an AppArmor profile loaded.

**Important:** This is more precise than the M0t template check but *still does not exercise the kernel*. Every state and boolean is hypothetical. The script's exit code zero means the **offline model** ran, never that a guest policy can be installed.

## 3. Proposed forward/rollback ordering (NOT implemented on host)

| Step | Simulated phase | What a future external privileged reviewer must actually prove |
| --- | --- | --- |
| U0 | guest_scope_attested | Identified disposable KVM guest; guest-local ext4; no host/production/shared mounts or unaccounted namespace/credentials |
| U1 | namespaces_collision_checked | Fresh noncolliding profile name, unit name, private fixture and recovery journal; no existing manager resource overwritten |
| U2 | independent_recovery_agent_and_journal_ready | Trusted root-only **durable** journal written and fsynced **before** global effects; independent controller that survives test script/actor crash and reconciles reboot |
| U3 | offline_policy_compiled_without_cache | `apparmor_parser --skip-kernel-load --skip-cache` on an **independently reviewed resolved fixture-only profile**, no kernel/cache load, clear exit/warnings with kernel feature ABI checked |
| U4 | profile_loaded | Kernel-global named profile load ONLY after authorization; witness actual profile name/enforce state; collision and unsupported-feature downgrade must fail closed |
| U5 | unit_installed | Publish only reviewed unit using no-follow root-owned operations; verify exact bytes/hashes, ownership/mode, dependencies and unit manager parsing; no enable/preset/auto-start |
| U6 | service_started | Start only reviewed disposable service; independently inspect process identity, supplementary groups, AppArmor label and exact DB/JSON mutation inside new fixture |
| U7 | service_stopped | Stop/kill and reconcile actual PIDs, inherited descriptors, descendants, late restarts, sockets and timers; do not assume systemctl status is full drain |
| U8 | unit_removed | Independently attest no unit, drop-in, activated/timer/socket instance or reloadable alias remains; no existing unit replaced |
| U9 | profile_unloaded | Remove only uniquely owned named AppArmor profile, after all relevant processes are gone, **never** a shared/global Python profile |
| U10 | independent_global_absence_witness | A second authority checks no kernel policy, loaded profile, unit file/manager state, open FD, credential delegation or fixture leftovers, including reboot/namespace scope |

Each event name is model-only. **This PR performs NONE of these operations.** It cannot manufacture an independent external kernel witness by claiming U10 in JSON.

## 4. Fault and crash behavior: mandatory quarantine

The model runs six fault families (`controller_crash`, `sigkill`, `power_loss`, `reboot`, `disk_full`, `service_start_failure`) against **every interruption point**. Before any modeled policy load, an incomplete sequence is `NO_GO_PRE_KERNEL_MUTATION_INCOMPLETE`. From the moment the hypothetical kernel profile may have been loaded, any incomplete or invalid sequence becomes **`QUARANTINE_GUEST_GLOBAL_POLICY_RECONCILIATION`** and requires a trusted external, human-reviewable recovery process. This includes cases where `profile_unloaded` was *claimed* but no independent global-absence witness exists.

Even the full modeled U0–U10 sequence returns `NO_GO_SIMULATED_ABSENCE_NOT_KERNEL_ATTESTATION`: an array of event strings can never prove actual kernel or service state. Manifest, group, launch, import, FD and recovery-review claims similarly **never** produce a GO.

Do not make an installer that simply writes files under /etc, calls a parser, registers a systemd unit and relies on finally for cleanup. A correct future disposable-guest implementation must first provide *a separately reviewed independent recovery agent and durable transaction record*, prove collision-free controlled publication and power-loss recovery, and obtain explicit operator authorization for guest-global changes.

## 5. Review questions still unresolved

1. Which **root-controlled recovery agent** (independent of test caller and service manager unit) reconciles stale AppArmor policy and systemd resources after SIGKILL/reboot? How is recovery idempotent, auditable and constrained to records for exactly this test?
2. Can a disposable **fresh VM clone/snapshot** and independent revert be the only credible global rollback guarantee? Who attests no existing profiles/units and isolated storage before execution?
3. What exact trusted compiled minimal synthetic actor and read-only library closure replace the M0s generic Python `-c` child, and how are runtime imports and mutations pinned at exec time?
4. How is the no-group / with-group independent old-code challenge run **without** accidentally granting both credentials through a privileged helper or unit? The known M0s counterexample must not be reclassified as a trusted code identity.
5. What AppArmor ABI, named profile (not shared Python attachment) and unit hardening can be validated by Debian 13 **without downgrading** or leaving unconfined exec fallbacks?
6. What evidence independently verifies loaded profile enforce status and actual child label, all related DB/WAL/SHM+JSON parent scopes, aliases, FDs and restart surfaces? T0–T12 from M0t remain UNVERIFIED.

If these cannot be closed, **reject a privileged guest installer**; carry forward a NO-GO and reconsider the mandatory boundary architecture.

## 6. Safe operator checks after owner review/merge (nonroot only)

    cd "$HOME/projectctl-m0k-lab"
    git fetch origin
    git status --short
    git switch --detach origin/main
    source .venv/bin/activate
    python -m pytest -q -rs tests/test_m60m0u_policy_lifecycle_fault_model.py
    python -B -m scripts.m0u_policy_lifecycle_model --inspect
    python -B -m scripts.m0u_policy_lifecycle_model --simulate-faults
    python -B -m scripts.m0u_nonroot_apparmor_compile_probe --probe-compiler

The simulation prints many modeled cases but mutates neither system state nor files. The optional compiler probe **does** spawn the fixed Debian Parser but only as the ordinary user and only for its embedded unattached syntax sample, explicitly preventing kernel load and parser cache use; it is a strictly bounded compiler smoke test, not an installed policy or systemd runtime test. If it fails, do not retry with sudo or change AppArmor settings; report the NO_GO JSON. The `apparmor_parser --names` output is not a guarantee that future arbitrary profiles enforce the intended rules. Nothing in M0u accepts sudo, `--run`, `--install` or `--restore`; such flags must fail. Any root/policy install must be proposed and audited separately.

**M0u maximum acceptance:** offline lifecycle/fault-model contract reviewed and tested. **No** actual loaded profile, installed service, kernel attestation, independent real rollback, real v3 writer or authorized migration. M0o P0–P9, M0r R0–R9 and M0t T0–T12 remain UNVERIFIED; M0/W1/R1/Collector/CLI stay **NO-GO**.
