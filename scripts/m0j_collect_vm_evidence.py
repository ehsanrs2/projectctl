"""M6.0 M0j: optional owner-invoked disposable-VM M0h evidence collector.

This CLI does NOT create or authenticate a VM, enable namespaces,
alter AppArmor/systemd/cgroups, touch a production project, or authorize
migration. It runs the pinned M0h tests ONLY after an explicit operator
review acknowledgement, against an operator-supplied clean checkout.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import stat
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from scripts.m0i_verify_vm_evidence import (
    M0H_HEAD, M0H_MODULE, PROTOCOL, _read_bounded, review,
)

ACK = "DISPOSABLE_VM_REVIEWED_NO_PRODUCTION_MOUNTS"
TIMEOUT_SECONDS = 180


class PilotRefused(ValueError):
    """Local operator preflight refused; never continue opportunistically."""


@dataclass(frozen=True)
class PilotOutcome:
    decision: str
    evidence_dir: str | None = None
    passed: int = 0
    skipped: int = 0
    failed: int = 0

    def as_dict(self) -> dict:
        return {
            "stage": "M6.0-M0j",
            "decision": self.decision,
            "evidence_dir": self.evidence_dir,
            "passed": self.passed,
            "skipped": self.skipped,
            "failed": self.failed,
            "authorizes_migration": False,
        }


def _git(checkout: Path, *args: str) -> str:
    try:
        process = subprocess.run(
            ["git", "-C", str(checkout), *args],
            capture_output=True, text=True, check=False, timeout=12,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise PilotRefused("git_probe_unavailable") from error
    if process.returncode != 0:
        raise PilotRefused("git_probe_failed")
    return process.stdout.strip()


def _check_checkout(checkout: Path) -> Path:
    """Refuse stale, dirty, symlinked and wrong-repository checkouts."""
    if checkout.is_symlink() or not checkout.is_dir():
        raise PilotRefused("checkout_missing_or_symlinked")
    root = checkout.resolve(strict=True)
    if _git(root, "rev-parse", "--show-toplevel") != str(root):
        raise PilotRefused("checkout_not_repository_root")
    if _git(root, "rev-parse", "HEAD") != M0H_HEAD:
        raise PilotRefused("m0h_commit_not_pinned")
    if _git(root, "status", "--porcelain", "--untracked-files=all"):
        raise PilotRefused("checkout_dirty")
    if _git(root, "ls-files", "--error-unmatch", M0H_MODULE) != M0H_MODULE:
        raise PilotRefused("pinned_module_missing")
    return root


def _private_parent(parent: Path) -> Path:
    """Ensure supplied parent is an existing, owner-only directory.

    This is NOT a descriptor-anchored security boundary against a local
    malicious process sharing the same UID: the target is a private VM.
    """
    if parent.is_symlink():
        raise PilotRefused("output_parent_symlink")
    try:
        info = parent.stat()
    except OSError as error:
        raise PilotRefused("output_parent_missing") from error
    if not stat.S_ISDIR(info.st_mode):
        raise PilotRefused("output_parent_not_directory")
    if info.st_uid != os.geteuid() or (stat.S_IMODE(info.st_mode) & 0o077):
        raise PilotRefused("output_parent_not_owner_private")
    return parent.resolve(strict=True)


def _field(value: str, field: str) -> str:
    if not isinstance(value, str) or not 1 <= len(value) <= 128:
        raise PilotRefused("invalid_" + field)
    if any(ord(c) < 32 or ord(c) > 126 for c in value):
        raise PilotRefused("invalid_" + field)
    return value


def _environment(scope_id: str, filesystem: str, userns_policy: str) -> dict:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{2,63}", scope_id):
        raise PilotRefused("invalid_scope_id")
    return {
        "kind": "disposable_vm",  # operator claim, NEVER authenticated
        "kernel_release": _field(platform.release(), "kernel_release"),
        "filesystem": _field(filesystem, "filesystem"),
        "scope_id": scope_id,
        "userns_policy": _field(userns_policy, "userns_policy"),
    }


def _write_private(path: Path, blob: bytes) -> None:
    # Directory is mkdtemp(0700), umask is 0077. Refuse overwrite.
    with path.open("xb") as output:
        output.write(blob)
        output.flush()
        os.fsync(output.fileno())


def _sync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def collect(
    checkout: Path, output_parent: Path, *,
    acknowledge: str,
    scope_id: str,
    filesystem: str,
    userns_policy: str,
) -> PilotOutcome:
    # Permission and VM selection are external to this user-side script.
    if platform.system() != "Linux" or os.geteuid() == 0:
        raise PilotRefused("non_linux_or_privileged_execution_refused")
    if acknowledge != ACK:
        raise PilotRefused("operator_vm_review_missing")
    source = _check_checkout(checkout)
    env = _environment(scope_id, filesystem, userns_policy)
    parent = _private_parent(output_parent)
    old_umask = os.umask(0o077)
    try:
        folder = Path(tempfile.mkdtemp(prefix="m0j-", dir=parent))
        junit = folder / "m0h-junit.xml"
        args = [
            sys.executable, "-B", "-m", "pytest", "-q", "-rs",
            "--junitxml=" + str(junit), M0H_MODULE,
        ]
        child_env = os.environ.copy()
        # Don't allow caller's module/plugin arguments to reinterpret the
        # pinned test source. Running on a clean, reviewed VM is still vital.
        child_env.pop("PYTHONPATH", None)
        child_env.pop("PYTEST_ADDOPTS", None)
        child_env["PYTHONNOUSERSITE"] = "1"
        child_env["PYTHONDONTWRITEBYTECODE"] = "1"
        try:
            run = subprocess.run(
                args, cwd=source, env=child_env,
                capture_output=True, text=True, timeout=TIMEOUT_SECONDS,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return PilotOutcome("NO_GO_TEST_TIMEOUT", str(folder))
        except OSError:
            return PilotOutcome("NO_GO_TEST_LAUNCH_FAILED", str(folder))
        if not junit.is_file() or junit.is_symlink():
            return PilotOutcome("NO_GO_MISSING_JUNIT", str(folder))
        try:
            junit_bytes = _read_bounded(junit)
        except (OSError, ValueError):
            return PilotOutcome("QUARANTINE_JUNIT_UNREADABLE", str(folder))
        os.chmod(junit, 0o600)
        manifest = {
            "protocol": PROTOCOL,
            "m0h_commit": M0H_HEAD,
            "test_module": M0H_MODULE,
            "junit_sha256": hashlib.sha256(junit_bytes).hexdigest(),
            "environment": env,
        }
        manifest_bytes = (
            json.dumps(manifest, sort_keys=True, separators=(",", ":"))
            + "\n"
        ).encode("utf-8")
        _write_private(folder / "manifest.json", manifest_bytes)
        _sync_directory(folder)
        reviewed = review(manifest_bytes, junit_bytes)
        decision = (
            reviewed.decision if run.returncode == 0
            else "NO_GO_PYTEST_NONZERO_EXIT"
        )
        return PilotOutcome(
            decision, str(folder),
            passed=reviewed.passed,
            skipped=reviewed.skipped,
            failed=reviewed.failed,
        )
    finally:
        os.umask(old_umask)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Collect pinned M0h evidence ONLY in a reviewed disposable VM."
    )
    parser.add_argument("--checkout", required=True, type=Path)
    parser.add_argument("--inspect", action="store_true")
    parser.add_argument("--collect", action="store_true")
    parser.add_argument("--output-parent", type=Path)
    parser.add_argument("--acknowledge")
    parser.add_argument("--scope-id")
    parser.add_argument("--filesystem")
    parser.add_argument("--userns-policy")
    args = parser.parse_args(argv)
    if args.inspect == args.collect:
        parser.error("select exactly one of --inspect or --collect")
    try:
        if args.inspect:
            source = _check_checkout(args.checkout)
            output = PilotOutcome("CHECKOUT_PINNED_REVIEW_VM_SEPARATELY")
        else:
            if (args.output_parent is None or args.scope_id is None
                    or args.filesystem is None or args.userns_policy is None):
                raise PilotRefused("missing_explicit_vm_or_evidence_arguments")
            output = collect(
                args.checkout, args.output_parent,
                acknowledge=args.acknowledge,
                scope_id=args.scope_id,
                filesystem=args.filesystem,
                userns_policy=args.userns_policy,
            )
    except PilotRefused as error:
        output = PilotOutcome("NO_GO_" + str(error).upper())
    print(json.dumps(output.as_dict(), sort_keys=True))
    return 0 if output.decision in (
        "CHECKOUT_PINNED_REVIEW_VM_SEPARATELY", "LAB_REVIEW_ONLY"
    ) else 2


if __name__ == "__main__":
    sys.exit(main())
