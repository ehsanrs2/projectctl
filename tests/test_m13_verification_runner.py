import sys
from pathlib import Path

from projectctl.core.enums import VerificationCheckStatus
from projectctl.schemas.verification import VerificationCommand, VerificationProfile
from projectctl.verification.runner import run_verification_commands


def test_runner_uses_argv_and_captures_digests(tmp_path: Path):
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    run_dir = tmp_path / "run"
    profile = VerificationProfile(
        id="default",
        commands=[
            VerificationCommand(
                id="ok",
                argv=[sys.executable, "-c", "print('hello')"],
                timeout_seconds=10,
            )
        ],
    )
    results = run_verification_commands(
        worktree,
        run_dir=run_dir,
        run_id="run-1",
        profile=profile,
    )
    assert results[0].status == VerificationCheckStatus.PASSED
    assert results[0].exit_code == 0
    assert results[0].stdout_digest.startswith("sha256:")
    assert (run_dir / "verification" / "ok.stdout.log").read_text().strip() == "hello"


def test_runner_times_out_without_shell(tmp_path: Path):
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    profile = VerificationProfile(
        id="default",
        commands=[
            VerificationCommand(
                id="timeout",
                argv=[
                    sys.executable,
                    "-c",
                    "import time; time.sleep(5)",
                ],
                timeout_seconds=1,
            )
        ],
    )
    results = run_verification_commands(
        worktree,
        run_dir=tmp_path / "run",
        run_id="run-1",
        profile=profile,
    )
    assert results[0].status == VerificationCheckStatus.TIMED_OUT
