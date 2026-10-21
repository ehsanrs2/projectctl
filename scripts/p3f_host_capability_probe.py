"""P3f bounded read-only *host planning hint*, never trial authorization.

Can run as ordinary user on the current development Debian machine. Cannot
establish that it is a VM host or that a separately administered guest exists.
"""
from __future__ import annotations

import json
import os
import platform
import re
import stat
import sys
from pathlib import Path

_ACK = "--inspect-current-host-readonly"
_REFUSAL = "P3F_HOST_PROBE_REFUSED"
_DECISION = "P3F_NO_GO_HOST_CAPABILITY_ONLY"
_CPUINFO = "/proc/cpuinfo"
_CPUINFO_LIMIT = 262144
_KVM = "/dev/kvm"
_EXECUTABLES = {
    "qemu_x86_64": "/usr/bin/qemu-system-x86_64",
    "qemu_aarch64": "/usr/bin/qemu-system-aarch64",
    "libvirt_virsh": "/usr/bin/virsh",
    "virt_install": "/usr/bin/virt-install",
    "virtualbox": "/usr/bin/VBoxManage",
}


def _cpu_hint() -> str:
    """Read just one fixed procfs file, never reveal CPU model/flags."""
    try:
        with Path(_CPUINFO).open("rb") as stream:
            raw = stream.read(_CPUINFO_LIMIT + 1)
    except OSError:
        return "CPUINFO_UNKNOWN"
    if not raw or len(raw) > _CPUINFO_LIMIT:
        return "CPUINFO_UNKNOWN"
    # Look only at lines named flags / Features; never expose raw lines.
    for line in raw.splitlines():
        if b":" not in line:
            continue
        key, value = line.split(b":", 1)
        if key.strip() not in (b"flags", b"Features"):
            continue
        if any(token in (b"vmx", b"svm") for token in re.split(rb"\s+", value.strip())):
            return "VMX_SVM_CPU_FLAG_HINT"
    return "NO_VMX_SVM_FLAG_OBSERVED"


def _kvm_hint() -> str:
    """lstat+access check; never open /dev/kvm or issue ioctl."""
    try:
        mode = os.lstat(_KVM).st_mode
    except OSError:
        return "KVM_DEVICE_NOT_OBSERVED"
    if not stat.S_ISCHR(mode):
        return "KVM_DEVICE_UNEXPECTED_FILE_TYPE"
    return (
        "KVM_DEVICE_DAC_ACCESS_HINT"
        if os.access(_KVM, os.R_OK | os.W_OK)
        else "KVM_DEVICE_NO_DAC_ACCESS_HINT"
    )


def _binary_hints() -> dict[str, str]:
    """No PATH lookup and no executable invocation, only fixed lstat calls."""
    result = {}
    for name, path in _EXECUTABLES.items():
        try:
            mode = os.lstat(path).st_mode
        except OSError:
            result[name] = "NOT_OBSERVED"
            continue
        result[name] = "FILE_OR_SYMLINK_HINT" if (stat.S_ISREG(mode) or stat.S_ISLNK(mode)) else "NOT_OBSERVED"
    return result


def observe() -> dict:
    return {
        "schema_kind": "projectctl.m6_0.p3f.host_capability_hint",
        "schema_version": 1,
        "classification": "LOCAL_SELF_OBSERVATION_NOT_SECURITY_ATTESTATION",
        "decision": _DECISION,
        "inspected_machine_role": "UNDETERMINED_DEV_MACHINE_NOT_TRIAL_GUEST",
        "platform_hint": "LINUX_OBSERVED" if platform.system() == "Linux" else "NON_LINUX_OBSERVED",
        "cpu_virtualization_hint": _cpu_hint(),
        "kvm_device_hint": _kvm_hint(),
        "virtualization_tool_hints": _binary_hints(),
        "separate_disposable_guest_identified": False,
        "independent_administrator_verified": False,
        "target_disk_and_mount_verified": False,
        "guest_creation_or_service_changes_authorized": False,
        "root_and_hypervisor_rollback": "IN_TRUSTED_COMPUTING_BASE",
        "p3_f01_to_f28_executed": 0,
        "operational_authorizations": {
            "create_or_modify_vm": False,
            "use_root_or_sudo": False,
            "provision_custodian": False,
            "modify_guest_or_host_policy": False,
            "access_real_project_source": False,
            "enable_v3_w1_r1_collector_cli": False,
            "expand_worker_task": False,
        },
    }


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if (args != [_ACK] or os.getuid() == 0 or os.geteuid() == 0
            or os.getuid() != os.geteuid() or os.getgid() != os.getegid()):
        print(_REFUSAL, file=sys.stderr)
        return 2
    try:
        output = observe()
    except OSError:
        print(_REFUSAL, file=sys.stderr)
        return 2
    print(json.dumps(output, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
