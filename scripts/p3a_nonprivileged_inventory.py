"""M6.0 P3a: bounded, unprivileged, non-authorizing host metadata inventory.

Only lstat/listxattr of an explicitly named directory and its ancestors, plus
bounded /proc/self reads. No ProjectCTL state access, subprocesses or writes.
Never use this observation as a credential, durability or anti-rollback proof.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import re
import stat
from pathlib import Path

_DECISION = "P3A_INVENTORY_ONLY_NO_GO"
_REFUSAL = "P3A_INVENTORY_REFUSED"
_MAX_PATH = 1024
_MAX_COMPONENTS = 32
_OCTAL_ESCAPE = re.compile(r"\\([0-7]{3})")
_UNSAFE_PARTS = frozenset({".projectctl", "projectctl-m0k-lab", "state.sqlite"})


class P3aRefusal(ValueError):
    """Fixed, path-free diagnostic; never leaks the supplied path."""


def _refuse() -> None:
    raise P3aRefusal(_REFUSAL)


def _bounded_read(path: Path, limit: int) -> str:
    try:
        with path.open("r", encoding="utf-8", errors="strict") as stream:
            data = stream.read(limit + 1)
        if len(data) > limit:
            _refuse()
        return data
    except (OSError, UnicodeError):
        _refuse()


def _path_components(raw: str) -> list[str]:
    if (not isinstance(raw, str) or not raw.startswith("/")
            or len(raw) > _MAX_PATH or raw == "/" or "\x00" in raw):
        _refuse()
    parts = raw.split("/")[1:]
    if (len(parts) > _MAX_COMPONENTS
            or any(p in ("", ".", "..") or p in _UNSAFE_PARTS for p in parts)):
        _refuse()
    return parts


def _acl_observation(path: str) -> str:
    try:
        names = os.listxattr(path, follow_symlinks=False)
        return "ACL_XATTR_PRESENT" if "system.posix_acl_access" in names else "ACL_XATTR_NOT_SEEN"
    except (OSError, AttributeError, NotImplementedError):
        return "UNKNOWN"


def _ancestry(raw: str, *, euid: int, egid: int, groups: set[int]) -> list[dict]:
    parts = _path_components(raw)
    result = []
    current = "/"
    for i, part in enumerate([None, *parts]):
        if part is not None:
            current = os.path.join(current, part)
        try:
            info = os.lstat(current)
        except OSError:
            _refuse()
        if not stat.S_ISDIR(info.st_mode):
            _refuse()  # Includes every symlink ancestor and non-directory.
        bits = stat.S_IMODE(info.st_mode)
        result.append({
            "position": "candidate" if i == len(parts) else "ancestor",
            "owner_is_effective_uid": info.st_uid == euid,
            "group_matches_process": info.st_gid in (groups | {egid}),
            "owner_write_bit": bool(bits & stat.S_IWUSR),
            "group_write_bit": bool(bits & stat.S_IWGRP),
            "other_write_bit": bool(bits & stat.S_IWOTH),
            "sticky_bit": bool(bits & stat.S_ISVTX),
            "acl": _acl_observation(current),
        })
    return result


def _mount_observation(raw: str, text: str) -> dict:
    best = None
    best_len = -1
    for line in text.splitlines()[:4096]:
        before, separator, after = line.partition(" - ")
        if not separator:
            continue
        left, right = before.split(), after.split()
        if len(left) < 6 or len(right) < 3:
            continue
        mountpoint = _OCTAL_ESCAPE.sub(lambda m: chr(int(m.group(1), 8)), left[4])
        if not mountpoint.startswith("/") or "\x00" in mountpoint:
            continue
        if raw == mountpoint or raw.startswith(mountpoint.rstrip("/") + "/"):
            if len(mountpoint) > best_len:
                best = (right[0], left[5].split(","))
                best_len = len(mountpoint)
    if best is None:
        return {"filesystem_type": "UNKNOWN", "mount_readonly_observed": None}
    fs, opts = best
    # No source device, mount point, mount options or host path is emitted.
    return {
        "filesystem_type": fs if re.fullmatch(r"[A-Za-z0-9_.+-]{1,40}", fs) else "UNKNOWN",
        "mount_readonly_observed": True if "ro" in opts else False if "rw" in opts else None,
    }


def _capability_observation(text: str) -> str:
    values = re.findall(r"^CapEff:\s*([0-9a-fA-F]+)\s*$", text, re.MULTILINE)
    if len(values) != 1 or len(values[0]) > 32:
        return "UNKNOWN"
    return "PRESENT" if int(values[0], 16) else "NONE_OBSERVED"


def collect_inventory(candidate_dir: str, *, proc_root: Path = Path("/proc/self")) -> dict:
    """Collect an observation; its success never authorizes deployment."""
    if (os.getuid() == 0 or os.geteuid() == 0
            or os.getuid() != os.geteuid() or os.getgid() != os.getegid()):
        _refuse()
    parts = _path_components(candidate_dir)
    groups = set(os.getgroups())
    ancestry = _ancestry(candidate_dir, euid=os.geteuid(), egid=os.getegid(), groups=groups)
    status = _bounded_read(proc_root / "status", 65536)
    mounts = _bounded_read(proc_root / "mountinfo", 1048576)
    return {
        "schema_kind": "projectctl.m6_0.p3a.nonprivileged_inventory",
        "schema_version": 1,
        "classification": "UNTRUSTED_READ_ONLY_OBSERVATION",
        "decision": _DECISION,
        "candidate": {"path_disclosed": False, "depth": len(parts), "existing_directory": True},
        "process": {
            "effective_uid": os.geteuid(), "effective_gid": os.getegid(),
            "supplementary_group_count": len(groups),
            "effective_capabilities": _capability_observation(status),
        },
        "platform": {"os": platform.system(), "kernel_release": platform.release()},
        "ancestry": ancestry,
        "mount": _mount_observation(candidate_dir, mounts),
        "unknowns": [
            "OWNER_AND_CODE_ORIGIN_NOT_PROVEN", "INHERITED_FD_AND_GROUP_BYPASS_NOT_TESTED",
            "MOUNT_ALIASES_AND_NAMESPACE_NOT_VERIFIED", "ACL_AND_DAC_ARE_NOT_ENFORCEMENT_TESTS",
            "NO_INDEPENDENT_CREDENTIAL", "NO_DURABLE_COMMIT_OR_ANTIROLLBACK",
            "NO_SOURCE_EPOCH_OR_PRODUCER_AUTHENTICATION", "NO_REBOOT_TEST",
        ],
        "authorization": {
            "trial_with_privileges": False, "provision_custodian": False,
            "trusted_source_export": False, "real_db_access": False,
            "writer_reader_collector_cli": False, "worker_task_expansion": False,
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="P3a read-only inventory; prints sanitized JSON only")
    parser.add_argument("--candidate-dir", required=True,
                        help="Existing absolute disposable directory; never a ProjectCTL state path")
    args = parser.parse_args(argv)
    try:
        result = collect_inventory(args.candidate_dir)
    except P3aRefusal:
        parser.exit(2, _REFUSAL + "\n")
    print(json.dumps(result, sort_keys=True, separators=(",", ":"), ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
