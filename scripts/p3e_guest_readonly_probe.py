"""M6.0 P3e: nonprivileged, non-attesting observation on *separate* disposable VM.

Explicit opt-in before bounded reads of FIXED paths. The operator assertion is
NOT evidence of an independent VM. Always NO_GO; no privileged or project reads.
"""
from __future__ import annotations

import json
import os
import platform
import re
import sys
from pathlib import Path

_DECISION = "P3E_NO_GO_SEPARATE_VM_UNATTESTED"
_REFUSAL = "P3E_PROBE_REFUSED"
_ACK = "--i-am-on-a-separate-disposable-vm"
_DMI_PATHS = ("/sys/class/dmi/id/sys_vendor", "/sys/class/dmi/id/product_name")
_DEBIAN_VERSION = "/etc/debian_version"
_STATUS = "/proc/self/status"
_BRANDS = (
    "qemu", "kvm", "vmware", "virtualbox", "innotek", "microsoft corporation",
    "virtual machine", "xen", "bochs", "parallels", "bhyve", "openstack",
)
_BLOCKERS = (
    "VM_DISPOSABILITY_AND_HOST_ISOLATION_NOT_ATTESTED",
    "INDEPENDENT_ADMINISTRATOR_AND_OBSERVER_NOT_VERIFIED",
    "STATIC_SECOND_PRINCIPAL_AND_LEGACY_WRITER_DENIAL_NOT_TESTED",
    "CUSTODY_FS_AND_DURABLE_COMMIT_NOT_VERIFIED",
    "P3_F01_TO_F28_NOT_EXECUTED",
    "NO_OWNER_APPROVED_PRIVILEGED_TRIAL_COMMANDS",
)


def _fixed_read(path: str, limit: int) -> bytes | None:
    """Read ONLY a hardcoded OS path; no path from CLI, no raw output."""
    if path not in (*_DMI_PATHS, _DEBIAN_VERSION, _STATUS):
        raise ValueError("P3E_INTERNAL_PATH_REFUSED")
    try:
        with Path(path).open("rb") as stream:
            raw = stream.read(limit + 1)
        return raw if len(raw) <= limit else None
    except (OSError, ValueError):
        return None


def _virtual_guest_hint() -> str:
    observations: list[str] = []
    for path in _DMI_PATHS:
        raw = _fixed_read(path, 256)
        if raw is not None:
            observations.append(raw.decode("ascii", errors="ignore").strip().lower())
    if not observations:
        return "DMI_NOT_READABLE"
    if any(brand in sample for sample in observations for brand in _BRANDS):
        return "DMI_VIRTUAL_BRAND_HINT_ONLY"
    return "DMI_NO_RECOGNIZED_VIRTUAL_BRAND"


def _debian_hint() -> str:
    raw = _fixed_read(_DEBIAN_VERSION, 256)
    if raw is None:
        return "DEBIAN_LINEAGE_UNKNOWN"
    if re.fullmatch(rb"[A-Za-z0-9.~/+\-]{1,255}\n?", raw) is None:
        return "DEBIAN_LINEAGE_UNKNOWN"
    return "DEBIAN_VERSION_FILE_OBSERVED"


def _effective_caps_hint() -> str:
    raw = _fixed_read(_STATUS, 32768)
    if raw is None:
        return "CAPABILITIES_UNKNOWN"
    try:
        lines = raw.decode("ascii", errors="strict").splitlines()
    except UnicodeError:
        return "CAPABILITIES_UNKNOWN"
    candidates = [ln.split(":", 1)[1].strip() for ln in lines if ln.startswith("CapEff:")]
    if len(candidates) != 1 or re.fullmatch(r"[0-9a-fA-F]{1,16}", candidates[0]) is None:
        return "CAPABILITIES_UNKNOWN"
    return "CAPABILITIES_ZERO_OBSERVED" if int(candidates[0], 16) == 0 else "CAPABILITIES_PRESENT_OBSERVED"


def observe() -> dict:
    """Fixed enum-only output; no machine identifiers, paths or user IDs."""
    return {
        "schema_kind": "projectctl.m6_0.p3e.disposable_guest_observation",
        "schema_version": 1,
        "classification": "SELF_REPORTED_NONAUTHORITATIVE_GUEST_HINT",
        "decision": _DECISION,
        "operator_disposable_vm_assertion": "UNVERIFIED_SELF_ASSERTION",
        "operating_system": "LINUX_OBSERVED" if platform.system() == "Linux" else "NON_LINUX_OBSERVED",
        "debian_lineage": _debian_hint(),
        "virtualization_hint": _virtual_guest_hint(),
        "vm_vs_container_and_isolation": "UNVERIFIED",
        "effective_capability_observation": _effective_caps_hint(),
        "root_host_and_snapshot_rollback": "IN_TRUSTED_COMPUTING_BASE",
        "blockers": list(_BLOCKERS),
        "actual_p3_cases_executed": 0,
        "privileged_trial_authorized": False,
        "deploy_custodian_authorized": False,
        "access_real_source_authorized": False,
    }


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    # Exact opt-in token, never an unbounded path, literal command, or secret.
    if args != [_ACK] or (os.getuid() == 0 or os.geteuid() == 0
                          or os.getuid() != os.geteuid()
                          or os.getgid() != os.getegid()):
        print(_REFUSAL, file=sys.stderr)
        return 2
    try:
        output = observe()
    except (OSError, ValueError):
        print(_REFUSAL, file=sys.stderr)
        return 2
    print(json.dumps(output, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
