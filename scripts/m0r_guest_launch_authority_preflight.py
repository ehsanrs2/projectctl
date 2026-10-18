"""M6.0 M0r: read-only guest capability *hints*, never security admission.

Provides no AppArmor/systemd unit installation, profile compilation/loading,
sudo, PID signaling, UID switching, project access or filesystem mutation.

AppArmor policy is process-scoped: attaching a profile to a systemd unit
cannot confine an independently spawned same-UID old interpreter. A
dedicated-UID launch assumption needs external proof before kernel mutation.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import stat
import subprocess
import sys
from dataclasses import dataclass, fields
from pathlib import Path


@dataclass(frozen=True)
class GuestHints:
    linux: bool
    nonroot: bool
    virtual_machine: str
    var_tmp_fstype: str
    apparmor_enabled: str
    own_apparmor_label: str
    pid1_name: str
    parser_on_path: bool
    parser_standard_path_status: str


@dataclass(frozen=True)
class BoundaryClaims:
    """Claims about a FUTURE disposable guest, NOT trusted observations.

    Even all True values cannot authenticate global policy or authorize
    root execution. Explicitly test the independent same-UID bypass FIRST.
    """

    exact_guest_identity_reviewed: bool | None = None
    complete_credential_routes_reviewed: bool | None = None
    code_and_dependency_closure_immutable: bool | None = None
    exact_root_owned_entrypoint_reviewed: bool | None = None
    profile_enforced_for_approved_unit: bool | None = None
    legacy_uid_still_denied_after_release: bool | None = None
    direct_same_uid_old_program_denied: bool | None = None
    direct_same_uid_python_import_denied: bool | None = None
    sqlite_wal_shm_json_all_scoped: bool | None = None
    old_fds_and_descendants_drained: bool | None = None
    continuously_held_maintenance_barrier: bool | None = None
    independent_kernel_witness_reviewed: bool | None = None


@dataclass(frozen=True)
class Decision:
    status: str
    authorizes_migration: bool = False
    authorizes_policy_install: bool = False


def assess_claims(claims: BoundaryClaims) -> Decision:
    """Useful for review triage only; it never accepts or issues authority."""
    if type(claims) is not BoundaryClaims:
        return Decision("NO_GO_INVALID_BOUNDARY_CLAIMS")
    # An affirmative bypass must be reported BEFORE incomplete other gates.
    # An old process is not denied if a claimed 'denial' is literally False.
    if claims.direct_same_uid_old_program_denied is False:
        return Decision("NO_GO_DIRECT_SAME_UID_OLD_PROGRAM_BYPASS")
    if claims.direct_same_uid_python_import_denied is False:
        return Decision("NO_GO_DIRECT_SAME_UID_PYTHON_IMPORT_BYPASS")
    for gate in fields(BoundaryClaims):
        if getattr(claims, gate.name) is not True:
            return Decision("NO_GO_UNVERIFIED_" + gate.name.upper())
    return Decision("NO_GO_INDEPENDENT_ENFORCEMENT_NOT_ATTESTED")


def _fixed_read(path: Path) -> str:
    """Bounded fixed kernel read, never an arbitrary supplied path."""
    try:
        raw = path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        return "unknown"
    if not raw or len(raw) > 256 or any(
        ord(char) < 32 or ord(char) == 127 for char in raw
    ):
        return "unknown"
    return raw


def _fixed_command(args: list[str]) -> str:
    try:
        result = subprocess.run(
            args, check=False, capture_output=True, text=True, timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"
    if result.returncode != 0:
        return "unknown"
    value = result.stdout.strip()
    if not value or len(value) > 80 or "\n" in value:
        return "unknown"
    return value


def _classify_parser_inode(info: os.stat_result) -> str:
    """This is a local file hint, NOT package provenance or MAC proof."""
    mode = info.st_mode
    if (not stat.S_ISREG(mode) or info.st_uid != 0
            or (mode & 0o022) != 0 or not (mode & stat.S_IXUSR)):
        return "unexpected_inode_or_permissions"
    return "root_owned_executable"


def _fixed_parser_path_status(
    path: Path = Path("/usr/sbin/apparmor_parser"),
) -> str:
    """Caller cannot select paths via CLI; path arg only for fixture tests."""
    try:
        info = path.lstat()  # no symlink traversal
    except FileNotFoundError:
        return "missing"
    except OSError:
        return "unreadable"
    return _classify_parser_inode(info)


def inspect() -> GuestHints:
    """Do not use this result as VM isolation or LSM policy attestation."""
    return GuestHints(
        linux=sys.platform == "linux",
        nonroot=os.getuid() != 0 and os.geteuid() != 0,
        virtual_machine=_fixed_command(["systemd-detect-virt", "--vm"]),
        var_tmp_fstype=_fixed_command(["findmnt", "-T", "/var/tmp", "-no", "FSTYPE"]),
        apparmor_enabled=_fixed_read(
            Path("/sys/module/apparmor/parameters/enabled")
        ),
        own_apparmor_label=_fixed_read(Path("/proc/self/attr/current")),
        pid1_name=_fixed_read(Path("/proc/1/comm")),
        parser_on_path=shutil.which("apparmor_parser") is not None,
        parser_standard_path_status=_fixed_parser_path_status(),
    )


def assess_hints(hints: GuestHints) -> Decision:
    if type(hints) is not GuestHints:
        return Decision("NO_GO_INVALID_GUEST_HINTS")
    if hints.linux is not True or hints.nonroot is not True:
        return Decision("NO_GO_NONROOT_LINUX_INSPECT_REQUIRED")
    if hints.virtual_machine not in ("kvm", "qemu"):
        return Decision("NO_GO_GUEST_VIRTUALIZATION_UNVERIFIED")
    if hints.var_tmp_fstype != "ext4":
        return Decision("NO_GO_GUEST_LOCAL_EXT4_UNVERIFIED")
    if hints.apparmor_enabled != "Y":
        return Decision("NO_GO_APPARMOR_NOT_VERIFIED_ENABLED")
    if hints.pid1_name != "systemd":
        return Decision("NO_GO_SYSTEMD_PID1_UNVERIFIED")
    if type(hints.parser_on_path) is not bool:
        return Decision("NO_GO_INVALID_GUEST_HINTS")
    if hints.parser_standard_path_status == "missing":
        return Decision("NO_GO_POLICY_PARSER_STANDARD_PATH_MISSING")
    if hints.parser_standard_path_status == "unreadable":
        return Decision("NO_GO_POLICY_PARSER_STANDARD_PATH_UNREADABLE")
    if hints.parser_standard_path_status != "root_owned_executable":
        return Decision("NO_GO_POLICY_PARSER_STANDARD_PATH_UNTRUSTED")
    if hints.parser_on_path is False:
        return Decision("NO_GO_POLICY_PARSER_PRESENT_OUTSIDE_PATH")
    # Label belongs to the *caller*, not writer; no filesystem scope check.
    return Decision("NO_GO_DIRECT_SAME_UID_LAUNCH_ENFORCEMENT_UNPROVEN")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inspect", action="store_true", required=True)
    args = parser.parse_args(argv)
    if not args.inspect:
        parser.error("--inspect required")
    hints = inspect()
    decision = assess_hints(hints)
    print(json.dumps({
        "stage": "M6.0-M0r",
        "decision": decision.status,
        "authorizes_migration": False,
        "authorizes_policy_install": False,
        "scope": "guest_hints_only_not_kernel_enforcement",
        "observations": {
            f.name: getattr(hints, f.name) for f in fields(GuestHints)
        },
    }, sort_keys=True))
    return 0  # inspect itself succeeded; this is NOT an authority exit code


if __name__ == "__main__":
    raise SystemExit(main())
