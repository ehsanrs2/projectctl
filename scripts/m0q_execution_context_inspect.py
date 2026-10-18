"""M6.0 M0q: unprivileged, read-only AppArmor/systemd context snapshot.

A present LSM or systemd daemon does NOT attest effective restrictions on
the v2/v3 writer identity, on direct Python execution, or on project files.

This is NEVER an admission tool. No sudo, mount, chmod, systemd modification,
AppArmor profile loading, arbitrary process enumeration or user-controlled
filesystem path; every possible decision is NO_GO and authorizes_migration
is always False.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ExecutionSnapshot:
    linux: bool
    apparmor_module_flag: str
    caller_profile: str
    pid1_comm: str


@dataclass(frozen=True)
class BoundaryDecision:
    decision: str
    authorizes_migration: bool = False


def _read_limited(path: Path) -> str:
    """Read only fixed kernel introspection nodes; refuse ambiguous output."""
    try:
        value = path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        return "unknown"
    if not value or len(value) > 256 or any(
        ord(char) < 32 or ord(char) == 127 for char in value
    ):
        return "unknown"
    return value


def inspect() -> ExecutionSnapshot:
    return ExecutionSnapshot(
        linux=sys.platform == "linux",
        apparmor_module_flag=_read_limited(
            Path("/sys/module/apparmor/parameters/enabled")
        ),
        caller_profile=_read_limited(Path("/proc/self/attr/current")),
        pid1_comm=_read_limited(Path("/proc/1/comm")),
    )


def review(snapshot: ExecutionSnapshot) -> BoundaryDecision:
    """Only a negative/read-only observation can be returned."""
    if type(snapshot) is not ExecutionSnapshot or type(snapshot.linux) is not bool:
        return BoundaryDecision("NO_GO_INVALID_EXECUTION_SNAPSHOT")
    if not snapshot.linux:
        return BoundaryDecision("NO_GO_UNSUPPORTED_OS")
    if snapshot.apparmor_module_flag != "Y":
        return BoundaryDecision("NO_GO_APPARMOR_NOT_VERIFIED_ENABLED")
    if not snapshot.caller_profile.endswith(" (enforce)"):
        # Even an enforced *caller* label would not attest all writer paths.
        return BoundaryDecision("NO_GO_CALLER_CONFINEMENT_NOT_OBSERVED")
    if snapshot.pid1_comm != "systemd":
        return BoundaryDecision("NO_GO_SYSTEMD_PID1_NOT_OBSERVED")
    return BoundaryDecision("NO_GO_WRITER_ENTRYPOINT_SCOPE_UNPROVEN")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inspect", action="store_true", required=True)
    options = parser.parse_args(argv)
    if not options.inspect:
        parser.error("--inspect is required")
    snapshot = inspect()
    decision = review(snapshot)
    print(json.dumps({
        "stage": "M6.0-M0q",
        "decision": decision.decision,
        "authorizes_migration": False,
        "scope": "read_only_self_context_not_writer_attestation",
        "apparmor_module_flag": snapshot.apparmor_module_flag,
        "caller_profile": snapshot.caller_profile,
        "pid1_comm": snapshot.pid1_comm,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
