"""M0w — real nonroot fresh-interpreter reconciliation and fail-closed tests."""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

from scripts import m0w_controller_restart_recovery_lab as lab


def _fixture(base: Path, *, effect: bool = True) -> Path:
    root = Path(tempfile.mkdtemp(prefix=lab._PREFIX, dir=base))
    lab._sync_dir(base)
    lab._write_new(root, lab._JOURNAL, lab._record(root))
    if effect:
        lab._write_new(root, lab._EFFECT, lab._EFFECT_BYTES)
    return root


def test_real_controller_sigkill_then_new_python_interpreter_recovers():
    if sys.platform != "linux" or os.getuid() == 0 or os.geteuid() == 0:
        pytest.skip("actual Linux ordinary-user child needed")
    result = lab.exercise()
    assert result == {
        "stage": "M6.0-M0w",
        "decision": "NO_GO_FRESH_PROCESS_PRIVATE_RECOVERY_OBSERVED",
        "scope": "nonroot_disk_journal_new_recovery_process_after_controller_sigkill",
        "controller_sigkill_observed": True,
        "fresh_recovery_process_completed": True,
        "journal_replayed_from_disk": True,
        "fixture_absent_after_recovery": True,
        "authorizes_root_trial": False,
        "authorizes_policy_install": False,
        "authorizes_migration": False,
    }


@pytest.mark.parametrize("effect", [False, True])
def test_fresh_owned_journal_recovers_with_or_without_effect(tmp_path, effect):
    root = _fixture(tmp_path, effect=effect)
    result = lab.reconcile_private(root, tmp_path)
    assert result["decision"] == "NO_GO_FRESH_PROCESS_PRIVATE_RECOVERY_OBSERVED"
    assert result["journal_replayed_from_disk"] is True
    assert not root.exists()


def test_changed_journal_is_quarantined_without_deleting(tmp_path):
    root = _fixture(tmp_path)
    (root / lab._JOURNAL).write_bytes(b"falsified intent")
    with pytest.raises(lab.Refused, match="JOURNAL_CONTENT_DRIFT"):
        lab.reconcile_private(root, tmp_path)
    assert (root / lab._EFFECT).exists()
    assert (root / lab._JOURNAL).exists()


def test_modified_effect_is_quarantined(tmp_path):
    root = _fixture(tmp_path)
    (root / lab._EFFECT).write_bytes(b"unexpected effect")
    with pytest.raises(lab.Refused, match="EFFECT_CONTENT_DRIFT"):
        lab.reconcile_private(root, tmp_path)
    assert (root / lab._JOURNAL).exists()


def test_extra_unknown_leaf_refuses_cleanup(tmp_path):
    root = _fixture(tmp_path)
    (root / "foreign").write_text("preserve me")
    with pytest.raises(lab.Refused, match="UNEXPECTED_LEAF"):
        lab.reconcile_private(root, tmp_path)
    assert (root / "foreign").exists()
    assert (root / lab._EFFECT).exists()


def test_missing_journal_fails_closed(tmp_path):
    root = _fixture(tmp_path)
    (root / lab._JOURNAL).unlink()
    with pytest.raises(lab.Refused, match="MISSING_JOURNAL"):
        lab.reconcile_private(root, tmp_path)
    assert (root / lab._EFFECT).exists()


@pytest.mark.parametrize("name", ["m0w-intent.json", "m0w-private-effect.bin"])
def test_symlink_never_followed(tmp_path, name):
    root = _fixture(tmp_path)
    link = root / name
    original = link.read_bytes()
    link.unlink()
    target = tmp_path / ("external-" + name)
    target.write_bytes(original)
    link.symlink_to(target)
    with pytest.raises(lab.Refused, match="UNTRUSTED_PRIVATE_LEAF"):
        lab.reconcile_private(root, tmp_path)
    assert target.read_bytes() == original


@pytest.mark.parametrize("name", ["m0w-intent.json", "m0w-private-effect.bin"])
def test_hardlink_never_removed(tmp_path, name):
    root = _fixture(tmp_path)
    outside = tmp_path / ("outside-" + name)
    os.link(root / name, outside)
    with pytest.raises(lab.Refused, match="UNTRUSTED_PRIVATE_LEAF"):
        lab.reconcile_private(root, tmp_path)
    assert outside.exists()


@pytest.mark.parametrize("name", ["m0w-intent.json", "m0w-private-effect.bin"])
def test_loose_leaf_permissions_rejected(tmp_path, name):
    root = _fixture(tmp_path)
    (root / name).chmod(0o644)
    with pytest.raises(lab.Refused, match="UNTRUSTED_PRIVATE_LEAF"):
        lab.reconcile_private(root, tmp_path)


def test_unsafe_directory_mode_rejected(tmp_path):
    root = _fixture(tmp_path)
    root.chmod(0o755)
    with pytest.raises(lab.Refused, match="UNTRUSTED_PRIVATE_ROOT"):
        lab.reconcile_private(root, tmp_path)
    assert (root / lab._JOURNAL).exists()


def test_nonfixture_path_cannot_be_reconciled(tmp_path):
    ordinary = tmp_path / "real-project"
    ordinary.mkdir()
    with pytest.raises(lab.Refused, match="OUT_OF_PRIVATE_SCOPE"):
        lab.reconcile_private(ordinary, tmp_path)
    assert ordinary.exists()


def test_subdirectory_cannot_be_reconciled(tmp_path):
    root = _fixture(tmp_path)
    child = root / "child"
    child.mkdir()
    with pytest.raises(lab.Refused, match="OUT_OF_PRIVATE_SCOPE"):
        lab.reconcile_private(child, tmp_path)
    assert (root / lab._JOURNAL).exists()


def test_directory_symlink_does_not_authorize_recovery(tmp_path):
    other = _fixture(tmp_path)
    target = tmp_path / (lab._PREFIX + "linked")
    target.symlink_to(other, target_is_directory=True)
    with pytest.raises(lab.Refused, match="UNTRUSTED_PRIVATE_ROOT"):
        lab.reconcile_private(target, tmp_path)
    assert other.exists()


def test_root_identity_rejected_before_directory_creation(monkeypatch):
    monkeypatch.setattr(lab.os, "geteuid", lambda: 0)
    with pytest.raises(lab.Refused, match="NONROOT_LINUX_ONLY"):
        lab.exercise()


def test_inspect_never_runs_exercise(monkeypatch, capsys):
    monkeypatch.setattr(
        lab, "exercise", lambda: pytest.fail("inspection must be inert")
    )
    assert lab.main(["--inspect"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["decision"] == "NO_GO_PRIVATE_CONTROLLER_RECOVERY_NOT_RUN"
    assert result["authorizes_root_trial"] is False


def test_exercise_requires_exact_ack(monkeypatch, capsys):
    monkeypatch.setattr(lab, "exercise", lambda: pytest.fail("ack missing"))
    assert lab.main(["--exercise"]) == 1
    result = json.loads(capsys.readouterr().out)
    assert result["decision"] == "NO_GO_NONROOT_EXERCISE_ACK_MISSING"


@pytest.mark.parametrize("args", [
    [], ["--run"], ["--install"], ["--reboot"], ["--load-profile"],
    ["--source", "/home/operator"], ["--exercise", "--output", "/etc"],
    ["--inspect", "--exercise"],
])
def test_no_privileged_external_cli(args):
    with pytest.raises(SystemExit) as error:
        lab.main(args)
    assert error.value.code != 0


def test_internal_recovery_rejects_nonfixture_without_touching_it(tmp_path):
    foreign = tmp_path / "important"
    foreign.mkdir()
    assert lab._worker_main(str(foreign)) == 1
    assert foreign.is_dir()


def test_journal_encodes_per_fixture_scope_and_negative_authorities(tmp_path):
    a = _fixture(tmp_path, effect=False)
    b = _fixture(tmp_path, effect=False)
    assert lab._record(a) != lab._record(b)
    record = json.loads(lab._record(a))
    assert record["fixture"] == a.name
    assert record["authorizes_policy_install"] is False
    assert record["authorizes_migration"] is False
    assert record["authorizes_root_trial"] is False


def test_fixed_script_has_no_kernel_or_service_loader_interface():
    code = Path(lab.__file__).read_text(encoding="utf-8")
    for forbidden in (
        "apparmor_parser -r", "apparmor_parser -a",
        "systemctl start", "systemctl enable",
        "/etc/systemd/system", "/etc/apparmor.d",
        "os.chown(", "os.setuid(", "os.setgid(", "os.setgroups(",
        "shutil.rmtree(", "os.kill(",
    ):
        assert forbidden not in code
