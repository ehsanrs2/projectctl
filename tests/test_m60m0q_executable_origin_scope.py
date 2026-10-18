"""M6.0 M0q: real unprivileged Python entrypoint origin counterexamples.

These tests do NOT use sudo, AppArmor profile loading, systemctl, host PIDs
or production ProjectCTL state. They demonstrate that a pinned *interpreter*
executable alone cannot authenticate runtime module/entrypoint bytes.

All executed or swapped source files belong to the private pytest tmp_path.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from scripts import m0q_execution_context_inspect as m0q
from scripts.m0q_execution_context_inspect import (
    BoundaryDecision, ExecutionSnapshot, review,
)


def _execute(args: list[str], *, cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, *args],
        cwd=cwd, env=env, check=True, capture_output=True,
        text=True, timeout=12,
    )


def test_same_python_binary_resolves_attacker_controlled_pythonpath_module(tmp_path):
    trusted = tmp_path / "trusted"
    attacker = tmp_path / "attacker"
    trusted.mkdir()
    attacker.mkdir()
    package = "m0q_disposable_entrypoint"
    (trusted / f"{package}.py").write_text(
        'print("trusted-module")\n', encoding="utf-8",
    )
    (attacker / f"{package}.py").write_text(
        'print("attacker-module")\n', encoding="utf-8",
    )
    # Both invocations execute the *same* Python interpreter binary.
    executable_digest = hashlib.sha256(Path(sys.executable).read_bytes()).hexdigest()
    env = os.environ.copy()
    env["PYTHONPATH"] = str(trusted)
    trusted_run = _execute(["-S", "-m", package], cwd=tmp_path, env=env)
    env["PYTHONPATH"] = os.pathsep.join((str(attacker), str(trusted)))
    attacker_run = _execute(["-S", "-m", package], cwd=tmp_path, env=env)
    assert trusted_run.stdout.strip() == "trusted-module"
    assert attacker_run.stdout.strip() == "attacker-module"
    assert hashlib.sha256(Path(sys.executable).read_bytes()).hexdigest() == (
        executable_digest
    )


def test_sitecustomize_injection_executes_before_selected_c_code(tmp_path):
    attacker = tmp_path / "attacker-site"
    attacker.mkdir()
    marker = tmp_path / "site-injected.marker"
    (attacker / "sitecustomize.py").write_text(
        f"from pathlib import Path\nPath({str(marker)!r}).write_text("
        "'site-hook', encoding='utf-8')\n",
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["PYTHONPATH"] = str(attacker)
    out = _execute(["-c", 'print("intended-entry")'], cwd=tmp_path, env=env)
    assert out.stdout.strip() == "intended-entry"
    assert marker.read_text(encoding="utf-8") == "site-hook"

    marker.unlink()
    isolated = _execute(
        ["-I", "-c", 'print("isolated-entry")'],
        cwd=tmp_path, env=env,
    )
    assert isolated.stdout.strip() == "isolated-entry"
    assert not marker.exists()
    # -I thwarts THIS env injection, not arbitrary code execution by an
    # already credentialed interpreter or all writable module paths.


def test_checked_script_path_can_be_replaced_before_separate_launch(tmp_path):
    script = tmp_path / "m0q-fixture-script.py"
    script.write_text('print("original-reviewed")\n', encoding="utf-8")
    approved_hash = hashlib.sha256(script.read_bytes()).hexdigest()
    replacement = tmp_path / "m0q-fixture-replacement.py"
    replacement.write_text('print("replacement-executed")\n', encoding="utf-8")
    os.replace(replacement, script)  # all paths private tmp_path only
    out = _execute([str(script)], cwd=tmp_path, env=os.environ.copy())
    assert out.stdout.strip() == "replacement-executed"
    assert hashlib.sha256(script.read_bytes()).hexdigest() != approved_hash


def _all_seen() -> ExecutionSnapshot:
    return ExecutionSnapshot(
        linux=True,
        apparmor_module_flag="Y",
        caller_profile="m0q-demo-profile (enforce)",
        pid1_comm="systemd",
    )


def test_even_enforced_caller_and_systemd_pid1_never_authorize():
    assert review(_all_seen()) == BoundaryDecision(
        "NO_GO_WRITER_ENTRYPOINT_SCOPE_UNPROVEN",
        authorizes_migration=False,
    )


@pytest.mark.parametrize(
    "snapshot,decision", [
        (replace(_all_seen(), linux=False), "NO_GO_UNSUPPORTED_OS"),
        (replace(_all_seen(), apparmor_module_flag="N"),
         "NO_GO_APPARMOR_NOT_VERIFIED_ENABLED"),
        (replace(_all_seen(), apparmor_module_flag="unknown"),
         "NO_GO_APPARMOR_NOT_VERIFIED_ENABLED"),
        (replace(_all_seen(), caller_profile="unconfined"),
         "NO_GO_CALLER_CONFINEMENT_NOT_OBSERVED"),
        (replace(_all_seen(), caller_profile="m0q-demo-profile (complain)"),
         "NO_GO_CALLER_CONFINEMENT_NOT_OBSERVED"),
        (replace(_all_seen(), caller_profile="unknown"),
         "NO_GO_CALLER_CONFINEMENT_NOT_OBSERVED"),
        (replace(_all_seen(), pid1_comm="python"),
         "NO_GO_SYSTEMD_PID1_NOT_OBSERVED"),
        (replace(_all_seen(), linux=1),
         "NO_GO_INVALID_EXECUTION_SNAPSHOT"),
        (None, "NO_GO_INVALID_EXECUTION_SNAPSHOT"),
        ({}, "NO_GO_INVALID_EXECUTION_SNAPSHOT"),
    ],
)
def test_probe_uncertainty_and_type_fail_closed(snapshot, decision):
    actual = review(snapshot)
    assert actual.decision == decision
    assert actual.authorizes_migration is False


def test_read_only_inspect_emits_explicit_no_go_and_never_calls_mutator(
    monkeypatch, capsys,
):
    monkeypatch.setattr(m0q, "inspect", _all_seen)
    assert m0q.main(["--inspect"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["authorizes_migration"] is False
    assert report["decision"] == "NO_GO_WRITER_ENTRYPOINT_SCOPE_UNPROVEN"
    assert report["scope"] == "read_only_self_context_not_writer_attestation"


@pytest.mark.parametrize("raw", [
    "", "\n", " " * 300, "a\nb", "Y\x00", "\x7f",
])
def test_kernel_probe_rejects_ambiguous_or_control_bytes(tmp_path, raw):
    fixture = tmp_path / "probe"
    fixture.write_text(raw, encoding="utf-8")
    assert m0q._read_limited(fixture) == "unknown"


def test_unreadable_kernel_probe_means_unknown(tmp_path):
    assert m0q._read_limited(tmp_path / "missing") == "unknown"
