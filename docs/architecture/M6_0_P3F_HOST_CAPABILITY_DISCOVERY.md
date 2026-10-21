# M6.0 P3f — Read-only host capability discovery for disposable VM planning

**Baseline:** merged P3e PR #112, `main@0d4391d54d70c6cc4202af4fe7e223bd0a48b40d`.

**Status:** host-side development-machine capability hints only; **no VM or privileged trial selected or approved**.

**Decision:** `P3F_NO_GO_HOST_CAPABILITY_ONLY`.

## 1. Scope: move toward a concrete VM choice without pretending one exists

P3c selected the conditional static dual-principal T1 *topology pattern*, P3d reviewed a claimed approval dossier, and P3e added a guest-side probe that **must not** run on the ordinary development checkout without independent proof that the checkout is itself a separate disposable guest. The unanswered operational question is whether a separate disposable VM already exists and which host can provide one.

P3f deliberately takes a different path. `scripts/p3f_host_capability_probe.py` may be run as a normal user **on the present Debian development machine**. It records a tiny fixed-enum inventory of possible virtualization support. It does not label that machine a VM, does not prove it is the hypervisor, does not select a guest or independently administered Custodian, and does not make a recommendation to install or run virtualization services. Passing this script is **not** meeting any P3-CRED/BLOB/SEQ/DUR/issuer/source proof.

## 2. What the command does — and does not do

Requires exactly `--inspect-current-host-readonly`, refuses root, setuid or setgid invocation and returns fixed refusal `P3F_HOST_PROBE_REFUSED` on invalid command invocation.

Allowed observations, strictly bounded:
- `/proc/cpuinfo`: read up to 256 KiB + 1 byte, looking for exact `vmx` or `svm` tokens on standard CPU flags/Features lines. Classify the CPU flag **hint**, never output raw flags/model/identity. No flags observed does NOT prove virtualization is impossible (nested/cloud guests and non-x86 cases).
- `/dev/kvm`: use `lstat` to distinguish a character device from a missing/unexpected file type, then ordinary-user `os.access` hint only. Never open the device, call ioctl or grant access. DAC access hint does not prove permissions after namespace, SELinux/AppArmor, libvirt, host hypervisor policies or that a VM can boot.
- Fixed `lstat` metadata only for `/usr/bin/qemu-system-x86_64`, `/usr/bin/qemu-system-aarch64`, `/usr/bin/virsh`, `/usr/bin/virt-install`, `/usr/bin/VBoxManage`. These are **untrusted file/symlink presence hints**, not package verification, actual executability, installed services, security patch level, operational readiness or VM inventory. Tools in alternate installation locations may not be detected.
- `platform.system()` for a coarse Linux/non-Linux enum.

No arbitrary path or user-supplied string is read, echoed or executed. No `sudo`, VM creation, package installation, service management, subprocess, network connection, device open, guest provisioning, mount configuration, DB/WAL, keys, real project source or evidence directory writes. Output contains **no machine identifiers, hostnames, device paths, users/groups, hardware fingerprints, raw /proc rows, mount tables, existing VM names or secrets**; only fixed enum categories.

## 3. Privacy and trust ceiling

The opt-in flag authorizes **only this bounded local inspection**, not elevated operations. The operating system can lie or virtualize these observations; the process can be inside a guest/container. Reading CPU flags, finding `virsh` or seeing readable `/dev/kvm` is never evidence that a separately administered, disposable Debian VM exists.

The result always contains:

- `decision: P3F_NO_GO_HOST_CAPABILITY_ONLY`.
- `inspected_machine_role: UNDETERMINED_DEV_MACHINE_NOT_TRIAL_GUEST`.
- `separate_disposable_guest_identified: false`.
- `independent_administrator_verified: false`.
- `target_disk_and_mount_verified: false`.
- `p3_f01_to_f28_executed: 0` and all operational authorizations false.

No automatic promotion from apparently suitable KVM/VMX/QEMU hints, no claim of protection against root or full hypervisor snapshot rollback. Root, trusted guest administrator, host/hypervisor and host-disk rollback are inside TCB for the local T1 design. If hostile root/host rollback is in scope, use a separately authorized external monotonic authority or stop.

## 4. Safe Debian acceptance and optional actual observation

After reviewing the diff, run on the **ordinary existing development checkout**, without sudo:

```bash
cd "$HOME/projectctl-m0k-lab"
git fetch origin
git status --short
git switch --detach origin/experiment/m6.0-p3f-host-capability-readonly-gate
source .venv/bin/activate

python -m pytest -q -rs tests/test_m60_p3f_host_capability_probe.py
python -m json.tool docs/architecture/p3/p3f-host-capability-decision.json > /dev/null
git diff --check 0d4391d54d70c6cc4202af4fe7e223bd0a48b40d..HEAD

python scripts/p3f_host_capability_probe.py --inspect-current-host-readonly
git rev-parse HEAD
```

The final probe is an **explicitly operator-initiated metadata read**, not a synthetic fixture; execute it only after source review. Do not run the P3e `--i-am-on-a-separate-disposable-vm` guest probe in place of this host inventory. The machine can be a physical host, VM or container; P3f does not distinguish these confidently.

Tests exercise 25 synthetic/refusal cases; successful CI and live hint observation establish **zero OS-level isolation/durability/identity proofs**. No raw private hypervisor inventory should be committed to the repository.

## 5. Decision based on observed hints (human only)

- If QEMU/KVM or other tooling appears: a human checks whether the current environment is actually a VM-capable host under **independent** administration, and whether it can host a new throwaway Debian guest, with a separately approved, non-production disk. Do not execute installer/VM creation commands based on these hints alone.
- If nothing appears: **do not infer impossibility**. Choose an existing separately administered VM, explicitly review another virtualization platform, or halt the operational Custodian trial.
- The owner must name, privately, the real guest identity, hypervisor/host admin, separate observer, guest reset/teardown and privacy boundaries, guest vs legacy-writer UID/GID/fd deny surfaces, nonvolatile storage/FS, exact privileged command list, reboot/ACK/ENOSPC witness and abort plan. The original Debian checkout is not the target by default.
- Only after a separate owner/security review and explicitly bounded approval can the **future** P3-F01–F28 dual-principal fault trials be considered. The P3e guest probe may be used *in that specifically chosen guest* under its own opt-in, still with unconditional NO-GO.

**Final contract:** P3f produces a machine-planning clue, not an authorization. P0–P4, real DB/WAL, v3 migration, W1/R1, signing/Collector/public CLI and Worker/Task authority remain unchanged and NO-GO.
