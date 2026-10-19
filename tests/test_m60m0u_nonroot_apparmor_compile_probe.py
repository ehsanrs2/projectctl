"""M0u fixed-path nonroot AppArmor --skip-kernel-load contract tests."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import m0u_nonroot_apparmor_compile_probe as probe


def _user(monkeypatch) -> None:
    monkeypatch.setattr(probe.os, "getuid", lambda: 1000)
    monkeypatch.setattr(probe.os, "geteuid", lambda: 1000)
    monkeypatch.setattr(
        probe, "_fixed_parser_path_status",
        lambda: "root_owned_executable",
    )


def test_exact_compile_only_flags_never_load_policy_or_cache():
    assert probe._ARGS[0] == "/usr/sbin/apparmor_parser"
    assert "--skip-kernel-load" in probe._ARGS
    assert "--skip-cache" in probe._ARGS
    assert "--skip-read-cache" in probe._ARGS
    assert "--names" in probe._ARGS
    # No filenames: Debian parser falls back to stdin, not a "-" path.
    assert probe._ARGS[-1] == "--names"
    assert "-" not in probe._ARGS
    assert "profile m0u-compile-only-unattached-review" in probe._PROFILE
    assert "/usr/bin/true ix," in probe._PROFILE
    assert "/var/tmp" not in probe._PROFILE
    for forbidden in ("--add", "--replace", "--remove", "--write-cache"):
        assert forbidden not in probe._ARGS


def test_nonroot_syntax_compiler_invokes_only_fixed_parser(monkeypatch):
    _user(monkeypatch)
    called = []

    def emulate(args, **kwargs):
        called.append((args, kwargs))
        return SimpleNamespace(
            returncode=0, stdout=probe._PROBE_NAME + "\n", stderr="",
        )
    monkeypatch.setattr(probe.subprocess, "run", emulate)
    result = probe.probe()
    assert result["decision"] == "NO_GO_APPARMOR_PARSE_ONLY_NOT_ENFORCEMENT"
    assert len(called) == 1
    args, kw = called[0]
    assert args == list(probe._ARGS)
    assert kw["input"] == probe._PROFILE
    assert kw["cwd"] == "/"
    assert kw["timeout"] == 10
    assert kw["env"] == {"PATH": "/usr/bin:/bin", "HOME": "/nonexistent"}
    assert kw["check"] is False
    assert not result["authorizes_root_trial"]
    assert not result["authorizes_policy_install"]
    assert not result["authorizes_migration"]


@pytest.mark.parametrize("uid,euid", [(0, 0), (0, 1000), (1000, 0)])
def test_root_mode_refuses_before_ever_calling_parser(monkeypatch, uid, euid):
    monkeypatch.setattr(probe.os, "getuid", lambda: uid)
    monkeypatch.setattr(probe.os, "geteuid", lambda: euid)
    monkeypatch.setattr(
        probe.subprocess, "run",
        lambda *_args, **_kwargs: pytest.fail("must not invoke parser"),
    )
    result = probe.probe()
    assert result["decision"] == "NO_GO_NONROOT_COMPILER_PROBE_REQUIRED"


@pytest.mark.parametrize("status", [
    "missing", "unreadable", "unexpected_inode_or_permissions",
])
def test_missing_or_unsafe_parser_path_refuses_without_execution(
    monkeypatch, status,
):
    _user(monkeypatch)
    monkeypatch.setattr(probe, "_fixed_parser_path_status", lambda: status)
    monkeypatch.setattr(
        probe.subprocess, "run",
        lambda *_args, **_kwargs: pytest.fail("must not invoke parser"),
    )
    assert probe.probe()["decision"] == "NO_GO_TRUSTED_FIXED_PARSER_NOT_AVAILABLE"


@pytest.mark.parametrize("exc", [
    OSError("parser missing"), subprocess.TimeoutExpired("parser", 10),
])
def test_compiler_tool_failure_does_not_claim_success(monkeypatch, exc):
    _user(monkeypatch)
    def fail(*_args, **_kwargs):
        raise exc
    monkeypatch.setattr(probe.subprocess, "run", fail)
    assert probe.probe()["decision"] == "NO_GO_APPARMOR_COMPILE_ONLY_FAILED"


@pytest.mark.parametrize("returncode,output,expected", [
    (1, "m0u-compile-only-unattached-review", "NO_GO_APPARMOR_COMPILE_ONLY_FAILED"),
    (0, "", "NO_GO_APPARMOR_COMPILE_OUTPUT_UNEXPECTED"),
    (0, "unexpected_other_profile", "NO_GO_APPARMOR_COMPILE_OUTPUT_UNEXPECTED"),
    (0, "m0u-compile-only-unattached-review" + "x" * 5000,
     "NO_GO_APPARMOR_COMPILE_OUTPUT_UNEXPECTED"),
])
def test_invalid_compiler_outputs_never_issue_authority(
    monkeypatch, returncode, output, expected,
):
    _user(monkeypatch)
    monkeypatch.setattr(
        probe.subprocess, "run",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=returncode, stdout=output, stderr=""
        ),
    )
    assert probe.probe()["decision"] == expected


def test_operator_cli_returns_json_no_go_with_all_authorities_false(
    monkeypatch, capsys,
):
    _user(monkeypatch)
    monkeypatch.setattr(
        probe.subprocess, "run",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=0, stdout=probe._PROBE_NAME, stderr=""
        ),
    )
    assert probe.main(["--probe-compiler"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["decision"].startswith("NO_GO_")
    assert report["authorizes_root_trial"] is False
    assert report["authorizes_policy_install"] is False
    assert report["authorizes_migration"] is False


@pytest.mark.parametrize("args", [
    [], ["--run"], ["--install"], ["--load"],
    ["--profile", "/etc/apparmor.d/python"],
])
def test_no_privileged_cli_or_any_caller_selected_profile(args):
    with pytest.raises(SystemExit) as error:
        probe.main(args)
    assert error.value.code != 0


def test_no_write_or_kernel_mutation_operations_in_nonroot_probe():
    source = Path(probe.__file__).read_text(encoding="utf-8")
    for forbidden in (
        "os.chmod(", "os.chown(", "os.setuid(", "os.setgid(",
        "apparmor_parser -r", "apparmor_parser -a",
        "shutil.rmtree(", "systemctl start", "subprocess.Popen(",
    ):
        assert forbidden not in source
