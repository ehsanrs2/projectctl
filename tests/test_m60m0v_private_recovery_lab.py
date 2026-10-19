"""M0v: test a real nonroot child SIGKILL; never a kernel policy/service."""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

from scripts import m0v_private_recovery_lab as lab


def _new_root(base: Path) -> Path:
    root = Path(tempfile.mkdtemp(prefix=lab._PREFIX, dir=base))
    lab._fsync_directory(base)
    lab._write_exclusive(root, lab._RECORD, lab._record(root))
    return root


def test_nonroot_real_sigkill_after_fsynced_record_and_effect(tmp_path):
    if sys.platform != "linux" or os.getuid() == 0 or os.geteuid() == 0:
        pytest.skip("requires Linux nonroot process")
    result = lab.exercise(base=tmp_path)
    assert result["decision"] == "NO_GO_PRIVATE_SIGKILL_RECOVERY_OBSERVED"
    assert result["private_journal_reconciled"] is True
    assert result["child_sigkill_observed"] is True
    assert result["fixture_absent_after_recovery"] is True
    assert result["authorizes_policy_install"] is False
    assert result["authorizes_root_trial"] is False
    assert result["authorizes_migration"] is False
    assert list(tmp_path.iterdir()) == []


def test_manual_idempotent_recovery_with_effect_missing(tmp_path):
    root = _new_root(tmp_path)
    assert lab.recover_private(root, tmp_path) == (
        "NO_GO_PRIVATE_SIGKILL_RECOVERY_OBSERVED"
    )
    assert not root.exists()


def test_manual_owned_effect_recovery(tmp_path):
    root = _new_root(tmp_path)
    lab._write_exclusive(root, lab._EFFECT, lab._PAYLOAD)
    assert lab.recover_private(root, tmp_path) == (
        "NO_GO_PRIVATE_SIGKILL_RECOVERY_OBSERVED"
    )
    assert not root.exists()


def test_bad_journal_is_quarantined_without_delete(tmp_path):
    root = _new_root(tmp_path)
    journal = root / lab._RECORD
    journal.write_bytes(b'{"unsafe":true}')
    with pytest.raises(lab.Refused, match="JOURNAL_CONTENT_DRIFT"):
        lab.recover_private(root, tmp_path)
    assert journal.exists()
    assert root.exists()


def test_bad_effect_is_quarantined_without_delete(tmp_path):
    root = _new_root(tmp_path)
    lab._write_exclusive(root, lab._EFFECT, b"unexpected contents")
    with pytest.raises(lab.Refused, match="EFFECT_CONTENT_DRIFT"):
        lab.recover_private(root, tmp_path)
    assert (root / lab._EFFECT).exists()


def test_unknown_extra_file_blocks_any_cleanup(tmp_path):
    root = _new_root(tmp_path)
    (root / "unrecognized").write_text("do not touch")
    with pytest.raises(lab.Refused, match="UNKNOWN_OR_MISSING_JOURNAL"):
        lab.recover_private(root, tmp_path)
    assert (root / "unrecognized").is_file()
    assert (root / lab._RECORD).is_file()


def test_symlink_for_journal_is_quarantined_no_follow(tmp_path):
    root = _new_root(tmp_path)
    old = root / lab._RECORD
    old.unlink()
    arbitrary = tmp_path / "separate"
    arbitrary.write_bytes(lab._record(root))
    old.symlink_to(arbitrary)
    with pytest.raises(lab.Refused, match="UNTRUSTED_PRIVATE_INODE"):
        lab.recover_private(root, tmp_path)
    assert arbitrary.read_bytes() == lab._record(root)


def test_hardlink_for_effect_is_quarantined(tmp_path):
    root = _new_root(tmp_path)
    outside = tmp_path / "original"
    outside.write_bytes(lab._PAYLOAD)
    os.chmod(outside, 0o600)
    os.link(outside, root / lab._EFFECT)
    with pytest.raises(lab.Refused, match="UNTRUSTED_PRIVATE_INODE"):
        lab.recover_private(root, tmp_path)
    assert outside.read_bytes() == lab._PAYLOAD


def test_private_directory_mode_must_remain_0700(tmp_path):
    root = _new_root(tmp_path)
    root.chmod(0o777)
    with pytest.raises(lab.Refused, match="UNTRUSTED_FIXTURE_ROOT"):
        lab.recover_private(root, tmp_path)
    assert (root / lab._RECORD).exists()


def test_no_external_or_caller_selected_scope(tmp_path):
    arbitrary = tmp_path / "source-project"
    arbitrary.mkdir()
    with pytest.raises(lab.Refused, match="OUTSIDE_FIXED_PRIVATE_FIXTURE_SCOPE"):
        lab.recover_private(arbitrary, tmp_path)
    assert arbitrary.exists()


def test_wrong_permission_journal_refuses(tmp_path):
    root = _new_root(tmp_path)
    (root / lab._RECORD).chmod(0o644)
    with pytest.raises(lab.Refused, match="UNTRUSTED_PRIVATE_INODE"):
        lab.recover_private(root, tmp_path)


def test_root_execution_always_refused(monkeypatch, tmp_path):
    monkeypatch.setattr(lab.os, "getuid", lambda: 0)
    with pytest.raises(lab.Refused, match="NONROOT_LINUX_REQUIRED"):
        lab.exercise(base=tmp_path)


def test_read_only_inspection_without_exercise(monkeypatch, capsys):
    monkeypatch.setattr(
        lab, "exercise", lambda **kwargs: pytest.fail("unsafe execution")
    )
    assert lab.main(["--inspect"]) == 0
    obj = json.loads(capsys.readouterr().out)
    assert obj["decision"] == "NO_GO_PRIVATE_RECOVERY_EXERCISE_NOT_RUN"
    assert obj["authorizes_root_trial"] is False


def test_no_exercise_without_explicit_ack(monkeypatch, capsys):
    monkeypatch.setattr(
        lab, "exercise", lambda **kwargs: pytest.fail("ack required")
    )
    assert lab.main(["--exercise"]) == 1
    obj = json.loads(capsys.readouterr().out)
    assert obj["decision"] == "NO_GO_EXPLICIT_NONROOT_FIXTURE_ACK_REQUIRED"


@pytest.mark.parametrize("argv", [
    ["--run"], ["--install"], ["--load-profile"],
    ["--source", "/home/operator/real"],
    ["--exercise", "--output", "/tmp/out"],
])
def test_no_root_or_user_selected_path_cli(argv):
    with pytest.raises(SystemExit) as err:
        lab.main(argv)
    assert err.value.code != 0


def test_fixture_only_mutations_no_systemd_or_apparmor_source():
    content = Path(lab.__file__).read_text(encoding="utf-8")
    for forbidden in (
        "systemctl start", "apparmor_parser -r", "os.chown(",
        "os.setuid(", "os.setgid(", "os.setgroups(",
        "shutil.rmtree(", "/etc/systemd/system/", "/etc/apparmor.d/",
    ):
        assert forbidden not in content
