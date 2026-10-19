"""M6.0 M0u — optional nonroot, NO-KERNEL-LOAD AppArmor parse probe.

Only validates an inert, embedded AppArmor syntax sample through the
root-owned Debian parser at its fixed absolute path. Never installs,
loads, replaces, caches, compiles to a file, or unloads any policy.
A parser exit-zero DOES NOT ATTEST a loaded/enforcing service profile.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path

from scripts.m0r_guest_launch_authority_preflight import (
    _fixed_parser_path_status,
)

_PARSER = Path("/usr/sbin/apparmor_parser")
_PROBE_NAME = "m0u-compile-only-unattached-review"
# This named profile has no executable attachment and is never loaded.
# It grants no write to any ProjectCTL path.
_PROFILE = (
    "profile m0u-compile-only-unattached-review {\n"
    "  /usr/bin/true ix,\n"
    "}\n"
)
_ARGS = (
    str(_PARSER), "--skip-kernel-load", "--skip-cache",
    "--skip-read-cache", "--names",
)


def probe() -> dict[str, object]:
    """One trusted-binary, nonroot, no-file-output parse; fail closed."""
    result: dict[str, object] = {
        "stage": "M6.0-M0u",
        "scope": "unattached_fixed_syntax_sample_no_kernel_load_no_cache",
        "decision": "NO_GO_APPARMOR_COMPILE_PROBE_NOT_EXECUTED",
        "parser_standard_path_status": _fixed_parser_path_status(),
        "authorizes_root_trial": False,
        "authorizes_policy_install": False,
        "authorizes_migration": False,
    }
    if os.getuid() == 0 or os.geteuid() == 0:
        result["decision"] = "NO_GO_NONROOT_COMPILER_PROBE_REQUIRED"
        return result
    if result["parser_standard_path_status"] != "root_owned_executable":
        result["decision"] = "NO_GO_TRUSTED_FIXED_PARSER_NOT_AVAILABLE"
        return result
    try:
        process = subprocess.run(
            list(_ARGS),
            input=_PROFILE,
            text=True,
            capture_output=True,
            check=False,
            timeout=10,
            cwd="/",
            env={"PATH": "/usr/bin:/bin", "HOME": "/nonexistent"},
        )
    except (OSError, subprocess.TimeoutExpired):
        result["decision"] = "NO_GO_APPARMOR_COMPILE_ONLY_FAILED"
        return result
    # Do not publish potentially unbounded tool output or file paths.
    if process.returncode != 0:
        result["decision"] = "NO_GO_APPARMOR_COMPILE_ONLY_FAILED"
    elif _PROBE_NAME not in process.stdout or len(process.stdout) > 4096:
        result["decision"] = "NO_GO_APPARMOR_COMPILE_OUTPUT_UNEXPECTED"
    else:
        result["decision"] = "NO_GO_APPARMOR_PARSE_ONLY_NOT_ENFORCEMENT"
    return result


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--probe-compiler", action="store_true", required=True)
    p.parse_args(argv)
    print(json.dumps(probe(), sort_keys=True))
    return 0  # Nonprivileged probe outcome stays NO_GO even on parse success.


if __name__ == "__main__":
    raise SystemExit(main())
