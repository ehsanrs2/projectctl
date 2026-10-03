from __future__ import annotations

import hashlib
import os
import signal
import subprocess
import time
from pathlib import Path

from projectctl.core.enums import VerificationCheckStatus
from projectctl.core.errors import VerificationError
from projectctl.core.paths import resolve_inside_repo
from projectctl.schemas.verification import (
    VerificationCheckResult,
    VerificationProfile,
)


def _file_digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _kill_process(process: subprocess.Popen) -> None:
    try:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()
    except ProcessLookupError:
        pass


def run_verification_commands(
    worktree: Path,
    *,
    run_dir: Path,
    run_id: str,
    profile: VerificationProfile,
) -> list[VerificationCheckResult]:
    log_dir = run_dir / "verification"
    log_dir.mkdir(parents=True, exist_ok=True)
    results: list[VerificationCheckResult] = []

    for command in profile.commands:
        cwd = worktree
        if command.cwd is not None:
            cwd = resolve_inside_repo(worktree, command.cwd, must_exist=True)
            if not cwd.is_dir():
                raise VerificationError(
                    f"Verification cwd is not a directory: {command.cwd}"
                )

        stdout_path = log_dir / f"{command.id}.stdout.log"
        stderr_path = log_dir / f"{command.id}.stderr.log"
        started = time.monotonic()
        exit_code: int | None = None
        status = VerificationCheckStatus.ERROR

        env = os.environ.copy()
        env["PROJECTCTL_RUN_ID"] = run_id
        env["PYTHONUNBUFFERED"] = "1"

        with stdout_path.open("wb") as stdout_handle, stderr_path.open("wb") as stderr_handle:
            try:
                process = subprocess.Popen(
                    command.argv,
                    cwd=cwd,
                    env=env,
                    stdin=subprocess.DEVNULL,
                    stdout=stdout_handle,
                    stderr=stderr_handle,
                    shell=False,
                    start_new_session=(os.name == "posix"),
                )
                try:
                    exit_code = process.wait(timeout=command.timeout_seconds)
                    status = (
                        VerificationCheckStatus.PASSED
                        if exit_code == 0
                        else VerificationCheckStatus.FAILED
                    )
                except subprocess.TimeoutExpired:
                    _kill_process(process)
                    process.wait()
                    status = VerificationCheckStatus.TIMED_OUT
            except OSError as exc:
                stderr_handle.write(
                    f"ProjectCTL could not start verification command: {exc}\n".encode(
                        "utf-8", errors="replace"
                    )
                )
                status = VerificationCheckStatus.ERROR

        duration_ms = max(0, int((time.monotonic() - started) * 1000))
        results.append(
            VerificationCheckResult(
                id=command.id,
                argv=command.argv,
                status=status,
                exit_code=exit_code,
                duration_ms=duration_ms,
                stdout_digest=_file_digest(stdout_path),
                stderr_digest=_file_digest(stderr_path),
            )
        )

    return results
